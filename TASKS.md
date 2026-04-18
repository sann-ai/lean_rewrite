# タスクボード

凡例: `open` | `claimed` | `done` | `blocked: <理由>`

クレーム手順は [AGENTS.md](AGENTS.md) を参照。タスクを取るときは `status`, `claimed_by`, `claimed_at` を埋めて **先に push** すること。

---

## T001 — mathlib4 をローカルにクローン

- status: done
- claimed_by: human0
- claimed_at: 2026-04-18T13:57:00Z
- done_at: 2026-04-18T14:00:56Z
- 依存: なし
- 内容: `https://github.com/leanprover-community/mathlib4` を `/Users/san/mathlib4` に clone。`lake exe cache get` を実行し、`lake build Mathlib.Logic.Basic` など小さなモジュールのビルドが通ることを確認。使用した mathlib の commit SHA を `NOTEBOOK.md` に記録する。
- 結果: SHA `896cc56a395e1615786fac56564a3fe6bfeebcc4`、toolchain `leanprover/lean4:v4.30.0-rc2`、sanity build 成功 (2.5s)。詳細は `NOTEBOOK.md`。

## T002 — refactor-commit データセット抽出

- status: open
- claimed_by:
- claimed_at:
- 依存: T001
- 内容: `scripts/fetch_refactor_commits.py` を書く。mathlib4 の git 履歴から `^refactor` または `^perf` で始まるコミットのうち、diff が1つの `def` / `structure` / `class` のみを変更するものを抽出。結果を `data/refactor_commits.jsonl` に書く(フィールド: `sha`, `message`, `file`, `before_def`, `after_def`)。最低 50 件取れることを目標に。

## T003 — Lean runner ラッパ (Python)

- status: claimed
- claimed_by: jpjwg4
- claimed_at: 2026-04-18T14:37:42Z
- 依存: なし(T001 の完了後に実動作確認可)
- 内容: `src/lean_rewrite/runner.py` を実装。mathlib worktree のパスとモジュール名を受け取り、`lake build <module>` を実行し、stdout / stderr / 終了コード / 壁時計時間を構造化して返す。タイムアウト対応必須。pytest で成功・失敗の簡単なケースを追加。

## T004 — `def → abbrev` 候補ジェネレータ

- status: done
- claimed_by: dndyij
- claimed_at: 2026-04-18T23:15:00Z
- done_at: 2026-04-18T23:30:00Z
- 依存: なし
- 内容: `src/lean_rewrite/candidates.py` に `def_to_abbrev(source: str, def_name: str) -> str` を実装。指定名の `def` を `abbrev` に書き換える(または `@[reducible]` 属性を付与)。対応すべきケース: アトリビュート保持、doc コメント保持、`noncomputable` / `protected` / `private` の保持、ジェネリクス(宇宙変数含む)の保持。各ケースにユニットテスト。
- 結果: `src/lean_rewrite/candidates.py` に `def_to_abbrev` と `DefNotFoundError` を実装。`tests/test_candidates.py` に 21 ケース (基本・属性保持・doc コメント・`protected`/`private`/`noncomputable`/`partial`・ユニバース変数 `.{u}` / `Sort*`・複数行定義・prefix 誤マッチ防止・コメント中の def 無視・`@[reducible]` 重複防止・インデント保持) を追加、全パス。`noncomputable` と `partial` は `abbrev` 化不可のため `@[reducible]` 属性をヘッダ上に挿入するフォールバック実装。`pyproject.toml` を追加してパッケージレイアウト (`src/` レイアウト + `pytest` 設定) を用意。

## T005 — evaluator: 下流証明メトリクス差分

- status: open
- claimed_by:
- claimed_at:
- 依存: T003
- 内容: `src/lean_rewrite/evaluator.py` を実装。baseline と候補の2つの mathlib worktree、および下流モジュールのリストを受け取り、両方をビルドして以下を報告:
  - (a) 壁時計ビルド時間差
  - (b) モジュールごとの elaboration 時間差 (`set_option profiler true` などを利用)
  - (c) 両方のビルドが成功したか
  - (d) 下流で使われている該当定義の unfold 回数や証明 LOC の差(可能な範囲で)

## T006 — エンドツーエンド MVP の配線

- status: open
- claimed_by:
- claimed_at:
- 依存: T001, T003, T004, T005, T007
- 内容: T003 + T004 + T005 を `src/lean_rewrite/main.py` に配線。入力: mathlib パス、対象ファイル、対象 def 名。出力: メトリクスが改善したら patch ファイル、しなかったら reject 理由レポート。

## T007 — 最初の実例を選んで記録

- status: open
- claimed_by:
- claimed_at:
- 依存: T001
- 内容: mathlib4 内で、下流の証明で 5 回以上 `unfold` または `simp only [<定義名>]` されている `def` を探す(reducibility が効きうる候補)。候補の定義、下流の使用例、なぜ `abbrev` 化が効くと期待するかを `experiments/001/README.md` にまとめる。T006 の入力になる。
