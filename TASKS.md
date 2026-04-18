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

- status: done
- claimed_by: mcdr9m
- claimed_at: 2026-04-18T16:59:25Z
- done_at: 2026-04-18T17:05:02Z
- 依存: T001
- 内容: `scripts/fetch_refactor_commits.py` を書く。mathlib4 の git 履歴から `^refactor` または `^perf` で始まるコミットのうち、diff が1つの `def` / `structure` / `class` のみを変更するものを抽出。結果を `data/refactor_commits.jsonl` に書く(フィールド: `sha`, `message`, `file`, `before_def`, `after_def`)。最低 50 件取れることを目標に。

## T003 — Lean runner ラッパ (Python)

- status: done
- claimed_by: jpjwg4
- claimed_at: 2026-04-18T14:37:42Z
- done_at: 2026-04-18T14:39:02Z
- 依存: なし(T001 の完了後に実動作確認可)
- 内容: `src/lean_rewrite/runner.py` を実装。mathlib worktree のパスとモジュール名を受け取り、`lake build <module>` を実行し、stdout / stderr / 終了コード / 壁時計時間を構造化して返す。タイムアウト対応必須。pytest で成功・失敗の簡単なケースを追加。
- 結果: `src/lean_rewrite/runner.py` に `run_lake_build` と `BuildResult` データクラス、`WorktreeNotFoundError` / `LakeNotFoundError` を実装。`subprocess.run(..., timeout=...)` を使用し、`TimeoutExpired` を捕捉して `timed_out=True` / `returncode=-1` を返すフォールバック付き。`tests/test_runner.py` に 4 ケース (real mathlib `Mathlib.Logic.Basic` 成功 / 存在しないモジュールの失敗 / 不在 worktree で `WorktreeNotFoundError` / 存在しない lake バイナリで `LakeNotFoundError`) を追加、全パス (5.52s)。

## T004 — `def → abbrev` 候補ジェネレータ

- status: done
- claimed_by: dndyij
- claimed_at: 2026-04-18T23:15:00Z
- done_at: 2026-04-18T23:30:00Z
- 依存: なし
- 内容: `src/lean_rewrite/candidates.py` に `def_to_abbrev(source: str, def_name: str) -> str` を実装。指定名の `def` を `abbrev` に書き換える(または `@[reducible]` 属性を付与)。対応すべきケース: アトリビュート保持、doc コメント保持、`noncomputable` / `protected` / `private` の保持、ジェネリクス(宇宙変数含む)の保持。各ケースにユニットテスト。
- 結果: `src/lean_rewrite/candidates.py` に `def_to_abbrev` と `DefNotFoundError` を実装。`tests/test_candidates.py` に 21 ケース (基本・属性保持・doc コメント・`protected`/`private`/`noncomputable`/`partial`・ユニバース変数 `.{u}` / `Sort*`・複数行定義・prefix 誤マッチ防止・コメント中の def 無視・`@[reducible]` 重複防止・インデント保持) を追加、全パス。`noncomputable` と `partial` は `abbrev` 化不可のため `@[reducible]` 属性をヘッダ上に挿入するフォールバック実装。`pyproject.toml` を追加してパッケージレイアウト (`src/` レイアウト + `pytest` 設定) を用意。

## T005 — evaluator: 下流証明メトリクス差分

- status: done
- claimed_by: m3xq7w
- claimed_at: 2026-04-18T15:31:41Z
- done_at: 2026-04-18T15:34:14Z
- 依存: T003
- 内容: `src/lean_rewrite/evaluator.py` を実装。baseline と候補の2つの mathlib worktree、および下流モジュールのリストを受け取り、両方をビルドして以下を報告:
  - (a) 壁時計ビルド時間差
  - (b) モジュールごとの elaboration 時間差 (`set_option profiler true` などを利用)
  - (c) 両方のビルドが成功したか
  - (d) 下流で使われている該当定義の unfold 回数や証明 LOC の差(可能な範囲で)

## T006 — エンドツーエンド MVP の配線

- status: done
- claimed_by: l4m3ai
- claimed_at: 2026-04-18T16:39:15Z
- done_at: 2026-04-18T16:42:30Z
- 依存: T001, T003, T004, T005, T007
- 内容: T003 + T004 + T005 を `src/lean_rewrite/main.py` に配線。入力: mathlib パス、対象ファイル、対象 def 名。出力: メトリクスが改善したら patch ファイル、しなかったら reject 理由レポート。
- 結果: `src/lean_rewrite/main.py` を新規作成。`run_pipeline()` が `def_to_abbrev` → `git worktree add` → `evaluate` → 判定の順で実行。`is_improvement()` は `all_succeeded AND total_unfold_count_delta < 0` を条件とする。CLI は `--mathlib / --file / --def-name / --downstream / --timeout / --lake / --output-dir` を受け取る。`tests/test_main.py` に 16 ケースを追加、全 57 テスト pass。

## T007 — 最初の実例を選んで記録

- status: done
- claimed_by: 2ldxuc
- claimed_at: 2026-04-18T16:21:19Z
- done_at: 2026-04-18T16:37:22Z
- 依存: T001
- 内容: mathlib4 内で、下流の証明で 5 回以上 `unfold` または `simp only [<定義名>]` されている `def` を探す(reducibility が効きうる候補)。候補の定義、下流の使用例、なぜ `abbrev` 化が効くと期待するかを `experiments/001/README.md` にまとめる。T006 の入力になる。
- 結果: `Nat.dist` を選定。`Mathlib/Data/Nat/Dist.lean` に `def dist (n m : ℕ) := n - m + (m - n)` として定義されており、同ファイル内で `unfold Nat.dist; lia` パターンが 16 件、`Archive/Imo/Imo2024Q5.lean` に 11 件の参照。`abbrev` 化で全 `unfold` 呼び出しが削除可能と期待。詳細は `experiments/001/README.md`。

## T008 — `is_improvement` メトリクス修正: baseline unfold カウントを改善シグナルに使う

- status: done
- claimed_by: k9Xm2P
- claimed_at: 2026-04-18T18:14:25Z
- done_at: 2026-04-18T18:17:33Z
- 依存: T006
- 内容:
  `experiments/001/run1` の E2E 実行で判明した問題: `is_improvement()` が `unfold_count_delta < 0` を条件にしているが、`def → abbrev` 変換では下流ソースを書き換えないため delta は常に 0 になり、REJECTED が常に返る。
  修正方針:
  1. `src/lean_rewrite/evaluator.py` の `ModuleMetrics` / `ModuleComparison` / `EvalResult` に `unfold_count_baseline` フィールドを追加 (baseline ダウンストリームファイル内の `unfold <def_name>` 出現数の合計)。
  2. `src/lean_rewrite/main.py` の `is_improvement()` を更新: `all_succeeded AND (total_unfold_count_delta < 0 OR total_unfold_count_baseline > 0)` を条件にする。論拠: baseline に N > 0 件の `unfold` がある場合、`abbrev` 化でそれらは冗長な no-op になる — これは潜在的改善であり ACCEPTED が妥当。
  3. `format_report()` に `Baseline unfold count: N` 行を追加。
  4. `tests/test_evaluator.py` と `tests/test_main.py` に新条件のユニットテスト追加。`Nat.dist` シナリオ(baseline unfold=16)が ACCEPTED になることを mocked テストで確認。
  受け入れ基準: 全既存テストがパス、かつ `total_unfold_count_baseline=16` のシナリオで `is_improvement` が True を返す。

## T009 — 第2段変換: ダウンストリームの冗長 `unfold` 呼び出しを自動除去

- status: open
- claimed_by:
- claimed_at:
- 依存: T006
- 内容:
  `abbrev` 化後、ダウンストリームの `unfold <def_name>` 呼び出しは意味論的に不要になる。これを自動除去してビルドが通るか確認することで、パイプラインが「実際に証明を簡略化できる」ことを実証する。
  実装:
  1. `src/lean_rewrite/candidates.py` に `remove_redundant_unfolds(source: str, def_name: str) -> str` を追加。パターン: 行頭(任意インデント)の `unfold <def_name>` または `unfold <def_name>;`(セミコロン区切り戦術行)を除去。注意: `unfold Foo.bar` の後に改行がある場合、その行を丸ごと削除。`unfold Foo.bar; tac` の場合は `unfold Foo.bar; ` 部分のみ削除して残りのタクティクを保持。
  2. `src/lean_rewrite/main.py` の `run_pipeline()` にオプション `--remove-unfolds` フラグを追加。有効時: 候補 worktree に abbrev パッチを適用した後、指定ダウンストリームファイルにも `remove_redundant_unfolds` を適用してから `evaluate()` を呼ぶ。
  3. `tests/test_candidates.py` に `remove_redundant_unfolds` の単体テスト追加(パターン: 単独行、セミコロン後ろ付き、複数 unfold、インデント付き、別定義は触らない)。
  4. `tests/test_main.py` に `--remove-unfolds` 経路の mocked テスト追加。
  受け入れ基準: 全テストパス。`Nat.dist` ケースで `remove_redundant_unfolds` を適用した後のソースに `unfold Nat.dist` が含まれないこと。

## T010 — Tier 2 検証: `data/refactor_commits.jsonl` から def→abbrev 事例を再現

- status: open
- claimed_by:
- claimed_at:
- 依存: T002, T006
- 内容:
  `data/refactor_commits.jsonl` (152件) の中から `before_def` が `def ` で始まり `after_def` が `abbrev ` で始まるエントリを絞り込む。上位 3 件(ファイルサイズ小・定義行数少を優先)を選び、パイプラインに通して再現を試みる。
  手順:
  1. Python スクリプト `scripts/validate_refactors.py` を書く: jsonl をフィルタし、候補 3 件を選んで、各ケースに対して `run_pipeline()` を呼ぶ(mathlib4 の対象ファイルを before 状態に一時的に戻した worktree を使う — `git worktree add` + `git checkout <before_sha>^ -- <file>` で実現)。結果を `experiments/validation/<sha_prefix>/report.txt` に保存。
  2. 最低 1 件で pipeline が ACCEPTED を返すか、あるいは明確な失敗理由(ビルドエラー、変換不可など)が記録されること。
  3. `experiments/validation/README.md` に 3 件の結果サマリを記述。
  受け入れ基準: `experiments/validation/` に 3 件以上のレポートが存在し、各レポートに `All builds succeeded:` 行と verdict 行がある。

## T011 — elaboration 時間メトリクス: `lake build` 詳細ログから per-file タイミングを取得

- status: open
- claimed_by:
- claimed_at:
- 依存: T005
- 内容:
  現状の evaluator は壁時計時間しか計れず揺らぎが ±20% ある。`lake build` の詳細出力から per-file の elaboration 時間を取り出すことで、より安定したメトリクスを得る。
  調査 & 実装:
  1. `/Users/san/mathlib4` で `lake build --verbose Mathlib.Logic.Basic 2>&1 | head -200` を実行し、出力フォーマットを確認。`elaborated` / `compiled` などのキーワードを含む行を探す。
  2. `set_option profiler true` をモジュールのソース先頭に一時挿入してビルドし、stdout から elaboration 時間行を抽出するパーサを試す。
  3. 実現可能なほうを選んで `src/lean_rewrite/evaluator.py` に `_parse_elaboration_times(stdout: str) -> dict[str, float]` を追加。`ModuleMetrics` に `elaboration_time_sec: float | None` フィールドを追加(取得できない場合は None)。
  4. `tests/test_evaluator.py` にパーサのユニットテスト追加(実際の lake 出力サンプルを fixture として使う)。
  受け入れ基準: `_parse_elaboration_times` が最低 1 件の実 lake build 出力から数値を取り出せること。既存テスト全パス。
