# 実装計画

最終更新: 2026-04-18 (初期ブートストラップ)

## ビジョン

mathlib4 の Lean 4 定義を自動で書き換え、下流の証明を扱いやすくする AI エージェントを作る。Buzzard ら *Schemes in Lean* (arXiv:2101.02602) の反復改良(scheme 定義の3版)を機械化するのが最終ゴール。

## 方針 (合意済み)

- **Refactor 型エージェント (option B)**: 候補生成 → ビルド検証 → メトリクスベース選別
- **実装スタック**: Python + LLM (Claude)、Lean は外部プロセス(`lake build`)
- **データセット**: 論文の Lean 3 コードではなく mathlib4 の `refactor`/`perf` commit(porting コスト回避)
- **目標 Lean**: Lean 4 + mathlib4

## アーキテクチャ

```
候補定義 (mathlib4 内)
  ↓ generator: ルール + LLM で書き換え候補を N 個生成
  ↓ builder: 各候補を worktree に適用して `lake build`
  ↓ evaluator: 下流証明のサイズ / elaboration 時間の差分を計測
  ↓ scorer: 厳密に改善した候補のみ残す
  ↓ logger: 勝敗を記録し将来のパターン抽出に使う
```

## フェーズ 1 (現在): `def → abbrev` の MVP

**スコープ**: 変換を1種類 (`def D := E` → `abbrev D := E` または `@[reducible] def`) に限定し、ループ全体を1例で動かす。

**この選択の根拠**:

- 変更が局所的で diff 検証が軽い
- elaboration 時間差として効果を測定しやすい
- bundled ↔ unbundled などの難変換より先にパイプラインを固めたい

**成果物**:

- `src/lean_rewrite/` の Python パッケージ:
  - `runner.py` — `lake build` を叩く subprocess ラッパ(時間・失敗の捕捉)
  - `candidates.py` — `def → abbrev` 変換ジェネレータ
  - `evaluator.py` — 書き換え前後の下流メトリクス差分
  - `main.py` — CLI エントリ
- `experiments/001/` — エンドツーエンドで動いた1例の記録

**完了の定義**: ある mathlib4 の `def` に対して、エージェントが自動で `abbrev` 化のパッチを生成し、ビルド成功を確認し、下流証明のメトリクスで改善 or 改悪を判定できる。

## フェーズ 2 (後で)

- 変換の追加: 暗黙⇄明示引数、引数順入れ替え、`@[simp]` 付与
- 候補を選ぶ対象定義を自動発見(手作業で選ばない)
- 複数変換の組み合わせ探索

## フェーズ 3 (ストレッチ)

- bundled ↔ unbundled 変換(論文の本質的教訓)
- mathlib4 の `AlgebraicGeometry.Scheme` の git 履歴を ground truth にエージェントを評価
- 「人間の refactor を再発見できるか」を指標に

## 完成基準 (Completion criteria)

プロジェクトは以下の 4 ティアで進む。AGENTS.md の「Planning when idle」ルーチンはこの一覧を **目標として参照する**。`TASKS.md` が空になったとき、計画エージェントは最も近い未達ティアを特定し、それを進めるためのタスクを 2〜4 個提案する。

### Tier 1 — MVP
- E2E パイプライン (`src/lean_rewrite/main.py`) が実 mathlib 定義に対して最低 1 回走り、`experiments/.../report.txt` を生成している
- レポートで baseline / candidate 両方の `All builds succeeded: True` が確認できる
- `is_improvement` が True を返して `candidate.patch` が生成されているか、メトリクスに基づいて明確に REJECTED となっている

### Tier 2 — mathlib 履歴に対する検証
- `data/refactor_commits.jsonl` の中から **既知 3 件以上** の mathlib refactor commit を再現(before 状態を与えて、パイプラインが after 状態と等価なパッチを提案)
- 再現記録を `experiments/validation/` に保存

### Tier 3 — `def → abbrev` 以外への一般化
- 追加の変換族を **最低 1 つ** 実装して E2E で検証(候補: 暗黙⇄明示 binder、引数順、`@[simp]` 付与、bundled↔unbundled など)
- 追加変換ごとに `experiments/` に再現例を残す

### Tier 4 — 非自明な実例
- **5 件以上の下流証明** を持つ定義に対して測定可能な改善を示す
- 改善が人間のレビュアーから見て妥当であると判断できる簡潔なレポートを `experiments/` に添える

### 全体として「完了」と言える条件(人間が最終判断)
Tier 1〜4 をすべて満たし、かつ Buzzard ら *Schemes in Lean* の手書き refactor との比較(定性的で可)を `experiments/writeup.md` に記す。

## モジュール契約 (実装済み)

後続タスクがこれらを呼び出すときの仕様。変更する場合は PLAN.md も同時に更新すること。

### `lean_rewrite.runner.run_lake_build(worktree, module, *, timeout, lake, extra_args)` (T003)

- `subprocess.run` で `lake build <module>` を実行し、frozen dataclass `BuildResult` を返す
- フィールド: `module`, `worktree`, `command`, `returncode`, `stdout`, `stderr`, `wall_time_sec`, `timed_out`、および `success` プロパティ
- **ビルド失敗では raise しない** — `returncode != 0` で通知
- タイムアウトは `BuildResult(timed_out=True, returncode=-1, ...)` を返す(raise しない)
- `WorktreeNotFoundError` / `LakeNotFoundError` は **セットアップ不備のときのみ** raise

### `lean_rewrite.candidates.def_to_abbrev(source, def_name)` (T004)

- 文字列として受け取った Lean ソース内の、指定名の top-level `def` を書き換えて新しい文字列を返す
- 指定名の `def` が見つからなければ `DefNotFoundError` を raise
- `noncomputable` / `partial` は `abbrev` にできないため、ヘッダ直前に `@[reducible]` を同インデントで挿入するフォールバックに切り替わる
- アトリビュート (`@[...]`)、doc コメント (`/-- ... -/`)、modifier (`protected` / `private` / `noncomputable` / `partial` / `unsafe`)、ユニバース変数 (`.{u}`, `Sort*`)、複数行バインダを保持する

## 未解決の設計論点 (人間の判断が必要)

以下はエージェント単独で決めないこと。ブロックして人間に委ねる:

- mathlib の巨大さに対するビルドのサンドボックス戦略(worktree + incremental? ccache? 部分ビルド?)
- 主要メトリクス: 証明 LOC / elaboration 時間 / unfold 回数 / LLM による質的評価 のどれを主軸にするか
- 候補生成はルールのみか、LLM + ルールか

## セットアップ前提 (初回のみ、T001 で対応)

- `/Users/san/mathlib4` に mathlib4 を clone
- `elan` + mathlib4 の `lean-toolchain` に合った toolchain
- Python 3.11+ と `uv` か `pip` での依存管理
