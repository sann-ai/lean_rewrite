# 作業日誌

追記専用 (append-only)。新しいエントリは末尾に。フォーマット:

```markdown
## <UTC ISO8601> — <task-id> — <agent-id>
- やったこと:
- わかったこと:
- 触ったファイル:
- 次のステップ(必要なら):
```

---

## 2026-04-18T00:00:00Z — bootstrap — human (claude 経由)

- やったこと: リポジトリ初期化。`README.md`, `AGENTS.md`, `PLAN.md`, `TASKS.md`, `NOTEBOOK.md`, `.gitignore` を作成。GitHub 公開リポジトリ `sann-ai/lean_rewrite` を作成し、初期コミットを push。
- わかったこと:
  - 設計方針は「Refactor 型 (B)」で合意
  - フェーズ 1 のターゲット変換は `def → abbrev`
  - データセットは論文の Lean 3 コードではなく mathlib4 の refactor commit を使う(porting コスト回避)
  - 実装スタック: Python + LLM (Claude)、Lean は外部プロセス
  - エージェント認証: `sann-ai` として `gh` CLI 認証済み、push 権限あり
  - mathlib4 は未クローン(T001 で対応)
- 触ったファイル: 初期構造一式
- 次のステップ: 次に動くエージェントは T001 (mathlib4 クローン) をクレームして開始

## 2026-04-18T14:00:56Z — T001 — human0

- やったこと:
  - `/Users/san/mathlib4` に mathlib4 を clone (full history, 531MB)
  - `lake exe cache get` 実行、8297 ファイル取得・展開成功、`.lake/` が 6.4GB に
  - sanity build `lake build Mathlib.Logic.Basic` が 65 jobs, 2.5s (wall) で成功
- わかったこと:
  - mathlib4 commit SHA: `896cc56a395e1615786fac56564a3fe6bfeebcc4` (2026-04-18 12:29:52 UTC, "chore: update Mathlib dependencies 2026-04-18 (#38206)")
  - lean-toolchain: `leanprover/lean4:v4.30.0-rc2`
  - cache 済み状態では末端モジュールのビルドは一瞬 → evaluator は cache 前提で設計できる
- 触ったファイル: `/Users/san/mathlib4/` 全体 (リポジトリ外)、`TASKS.md` (クレーム+解放)、`NOTEBOOK.md`
- 次のステップ: T002 (refactor-commit データセット抽出) と T003 (Lean runner ラッパ) は並列に進められる。T004 (`def → abbrev` ジェネレータ) は mathlib 不要なので即着手可能。T007 (最初の実例選定) は T001 完了後に動き出せる。

## 2026-04-18T23:30:00Z — T004 — dndyij

- やったこと:
  - `src/lean_rewrite/__init__.py`, `src/lean_rewrite/candidates.py`, `tests/__init__.py`, `tests/test_candidates.py`, `pyproject.toml` を新規作成。
  - `def_to_abbrev(source: str, def_name: str) -> str` と `DefNotFoundError` を実装。戦略: 純粋な正規表現ベースで top-level の `def <name>` を検出し、同一行および直上行の modifier トークン (`noncomputable`, `protected`, `private`, `partial`, `unsafe`) を解析。`noncomputable` または `partial` が付いているときは `abbrev` 不可なので `@[reducible]` 属性行をヘッダ直前 (同インデント) に挿入するフォールバックに切り替える。
  - 21 テストケースを pytest で実装、全パス (0.02s)。基本・属性保持・doc コメント・modifier 保持 (`noncomputable`, `protected`, `private`, `partial`)・ユニバース `.{u}` / `Sort*`・複数行定義・prefix 誤マッチ防止 (`fooBar` vs `foo`)・`-- def foo` コメント無視・`@[reducible]` 重複防止・インデント保持・複数モディファイアの組合せ。
  - 実コード (`Mathlib.Logic.Basic` の `Xor'` と `dec`) で手動サニティチェックも通過。
- わかったこと:
  - Lean 4 の `abbrev` は **computable でなければならない** ため、`noncomputable def` を単純に `noncomputable abbrev` にはできない。ここが PLAN.md のゴール記述「`abbrev` 化または `@[reducible]` 付与」が両方挙げられている理由。`partial def` も等価変換ができない(equational compiler が走らない)ため同様にフォールバック。
  - Lean 4 の modifier 語彙は `noncomputable` / `protected` / `private` / `partial` / `unsafe`。attribute (`@[...]`) はその前、doc comment (`/-- ... -/`) はさらに前に来るので、`def` キーワード置換だけで済むケースは意外に多い。
  - 名前に `'` を含む定義 (`Xor'`) は `re.escape` で安全にエスケープされる。`.` を含む dotted name (`Function.swap₂`) も同様に問題なし。
  - T004 は他タスクから独立しており、`src/lean_rewrite/` レイアウトと `pyproject.toml` の基盤を作った。これは T003 / T005 でも流用可能。
- 触ったファイル:
  - `src/lean_rewrite/__init__.py` (新規)
  - `src/lean_rewrite/candidates.py` (新規)
  - `tests/__init__.py` (新規)
  - `tests/test_candidates.py` (新規)
  - `pyproject.toml` (新規)
  - `TASKS.md` (T004 をクレーム→done)
  - `NOTEBOOK.md` (このエントリ)
- 次のステップ: T003 (runner.py) は T004 と同じ `src/lean_rewrite/` レイアウトに追加できる。T006 (E2E 配線) が T003/T004/T005/T007 の統合を担うので、次に動く agent は T003 か T007 あたりを優先すると MVP に近づく。
