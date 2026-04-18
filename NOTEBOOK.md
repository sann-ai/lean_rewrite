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
