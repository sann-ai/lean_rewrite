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

## 提案アルゴリズムの設計原理 (**Buzzard の教訓 = 実装依存の抽象化**)

この節は、計画エージェントが新しい変換族や評価軸を提案するときの **指針** として使う。単発の書き換えルールを足すのではなく、以下の原理を満たす方向に寄せること。

### 論文の核の教訓

Buzzard ら *Schemes in Lean* (arXiv:2101.02602) の scheme 定義の 3 版を見ると、**後の版になるほど「下流の証明が、元の定義の構造的な実装細部に依存しない形」** になっていた:

- **第 1 版**: 局所環との具体的な接着構成に下流が直接触っていた
- **第 2 版**: 局所化述語という中間層を通して、下流はそこだけ見れば良くなった
- **第 3 版**: mathlib の圏論基盤(関手・極限)経由に書き下され、scheme 固有の実装に非依存

論文の本丸は「bundled/unbundled の切替」自体ではなく、**refactor を通して下流を「どう作られているか」から「何を満たすか」だけに依存させる抽象化** である。

### この原理を提案アルゴリズムに持ち込む

良い変換候補とは、**下流のコードが元定義の実装詳細に依存する度合いを減らす** もの。判断基準:

- 変換前後で、下流証明から `unfold`, `show`, `change`, 構築子の直接参照、内部補題の陽な呼び出し — といった「実装依存の記述」が減っているか?
- 下流が characterizing lemmas(`@[simp]` 補題 / 代数的性質など)だけで書けるようになっているか?
- 定義本体を implementation detail として封じ込められたか?

単純な `def → abbrev` は **reducibility の選択** に過ぎず、この依存度をほぼ変えない(`unfold` が no-op 化するだけ)。本当に欲しい変換は、interface を取り出し、下流の表現を interface 経由に置き換え、原定義を裏側に回せるもの。

### フェーズ B の拡張指針 (planning agent 向け)

新しい変換族を提案するときは、上の原理に沿うように task を設計する。具体候補:

1. **`@[simp]` 補題の自動同定と付与**: 下流で多用される補題に `@[simp]` を付け、`unfold` を不要化する。「`unfold X; lia`」の代わりに「`simp` だけで閉じる」状態を目指す変換
2. **Characterizing lemmas の抽出**: def の「使われ方」を下流 grep で集計し、下流の全利用をカバーする最小の lemma set を同定。これを interface 候補として提案
3. **暗黙 ⇄ 明示 binder の切替**: 型推論が通るなら暗黙化して、下流の `@X (t := ...)` を削減
4. **結論の reassociation**: 下流が `show` / `change` で毎回形を整えている場合、元定義を下流が直接使える形で再表現
5. **構造抽出**: def を `{ value : T // properties }` のような Sigma/Subtype に分解し、properties を interface として切り出す

### 評価軸もこの原理に寄せる

現行メトリクス(unfold 数・ビルド成功・elaboration 時間)は必要条件ではあるが、上記原理の評価としては弱い。以下を追加候補として考える:

- **下流の「実装依存構文」総数**: `unfold`, `show`, `change`, `.1/.2` プロジェクション、内部補題名参照 — の合計
- **`simp` / `omega` / `fun_prop` など自動化タクティクで閉じる証明の割合**: 上がれば下流は interface 経由に寄った証拠
- **下流ファイルに現れる元定義のシンボル数**: 減ればより抽象化されている(ただし削除と相殺がないよう注意)

## 完成基準 (Completion criteria)

プロジェクトは以下の 4 ティアで進む。AGENTS.md の「Planning when idle」ルーチンはこの一覧を **目標として参照する**。`TASKS.md` が空になったとき、計画エージェントは最も近い未達ティアを特定し、それを進めるためのタスクを 2〜4 個提案する。**提案するタスクは上の「設計原理」に沿わせる** こと。

### Tier 1 — MVP
- E2E パイプライン (`src/lean_rewrite/main.py`) が実 mathlib 定義に対して最低 1 回走り、`experiments/.../report.txt` を生成している
- レポートで baseline / candidate 両方の `All builds succeeded: True` が確認できる
- `is_improvement` が True を返して `candidate.patch` が生成されているか、メトリクスに基づいて明確に REJECTED となっている

### Tier 2 — mathlib 履歴に対する検証
- `data/refactor_commits.jsonl` の中から **既知 3 件以上** の mathlib refactor commit を再現(before 状態を与えて、パイプラインが after 状態と等価なパッチを提案)
- 再現記録を `experiments/validation/` に保存

### Tier 3 — 「実装依存を減らす」変換族への一般化
- `def → abbrev` に加えて、**下流の実装依存度を実際に下げる** 変換族を最低 1 つ実装し、E2E で検証する(単なる別種のリネームではなく、上の「設計原理」を満たすもの)
- 有力候補: `@[simp]` 自動付与 + 下流の `unfold X` 除去 / characterizing lemma 抽出 + 下流の interface 経由書き換え / 下流の `show`/`change` が消せる形への再表現
- 追加変換ごとに `experiments/` に、**下流の実装依存指標(`unfold` / `show` / `change` / プロジェクション数など)の減少が数値として示せる** 再現例を残す

### Tier 4 — 非自明な実例で「下流の抽象化」を示す
- **5 件以上の下流証明** を持つ定義に対して、pipeline が提案した refactor で
  - ビルドが通り
  - 下流の実装依存構文(`unfold`, `show`, `change`, 内部補題参照)の合計が減り
  - 人間のレビュアーから「下流の書き方が元の構造的細部から独立した方向に進んでいる」と判断できる
  - を満たす簡潔なレポートを `experiments/` に添える

### 全体として「完了」と言える条件(人間が最終判断)
Tier 1〜4 をすべて満たし、かつ Buzzard ら *Schemes in Lean* の scheme 定義 3 版のうち、少なくとも 1 対(例: 第 2 版 → 第 3 版、または簡略化した類似例)について **「下流が実装詳細から interface 層に移った」という観点での比較**(定性的で可)を `experiments/writeup.md` に記す。

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
