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
