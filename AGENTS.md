# エージェント向け指示書

あなたは `lean_rewrite` プロジェクトに貢献する自動研究エージェントです。**複数のエージェントが同じローカルマシン上で並列に動作し、同じリポジトリを読み書きする可能性があります**。以下のワークフローを厳守してください — これが他エージェントとの衝突を防ぐ唯一の仕組みです。

## プロジェクトの目的

mathlib4 の Lean 4 定義を受け取り、下流の証明がより扱いやすくなるような書き換え候補を生成する Python ツールを作る。Buzzard ら *Schemes in Lean* (arXiv:2101.02602) が示した「同じ定義の反復改良」を自動化するのが最終目標。現在のフェーズと具体タスクは `PLAN.md` と `TASKS.md` を参照。

## 起動時にまずやること

このリポジトリのルートに移動し、以下のループに従う。セッションは自己完結させ、以前の会話状態には依存しないこと。

### 1. 同期

常に新鮮な状態から始める。既存のローカル clone があればそれを更新し、なければ clone:

```bash
REPO=/Users/san/lean_rewrite
if [ ! -d "$REPO/.git" ]; then
  git clone https://github.com/sann-ai/lean_rewrite.git "$REPO"
fi
cd "$REPO"
git fetch origin
git checkout main
git pull --rebase origin main
```

複数エージェントが同時に動く可能性があるため、状態の汚染を避けたい場合は一時 worktree:

```bash
WT=$(mktemp -d -t lr-XXXXXX)
git worktree add "$WT" main
cd "$WT"
```

### 2. 状態を読む

必ずこの順で読む:

1. `PLAN.md` — 現在のフェーズとアプローチを把握
2. `TASKS.md` — `status: open` のタスクを探す
3. `NOTEBOOK.md` 末尾 ~80 行 — 直近エージェントの活動を確認し重複を避ける

### 3. タスクをクレーム(作業前に必須)

作業開始前に **git 経由で原子的にクレーム** する。クレームが push できるまで実作業は開始しないこと。

1. エージェント ID を生成(セッション開始時に乱数 6 文字、例 `a7f2k9`)
2. `TASKS.md` を編集: 選んだタスクの
   - `status: open` → `status: claimed`
   - `claimed_by: <agent-id>`
   - `claimed_at: <UTC ISO8601>` (例 `2026-04-18T14:30:00Z`)
3. `git add TASKS.md && git commit -m "claim: <task-id> by <agent-id>"`
4. `git push origin main`
5. non-fast-forward で push が失敗したら:
   - `git pull --rebase origin main`
   - `TASKS.md` を再確認
   - 自分のタスクがまだ `open` のまま → 再編集して再 push
   - 他者にクレームされていた → 別タスクを選んで最初からやり直す

**クレームは 90 分で失効**。失効クレームを再取得する場合は `NOTEBOOK.md` に `Re-claimed stale task <id> (previously <old-agent>)` と記録。

### 4. 作業

- タスクに集中し、スコープ外は触らない
- タスクが大きすぎるとわかったら `TASKS.md` を編集して分割(クレーム保持者は自タスクを更新できる)
- コード変更には pytest など簡単なテストを添える

**禁止事項**:

- 他エージェントの進行中作業を消す
- `git push --force`
- CI 設定やブランチ保護の変更
- 秘密情報・API キー・トークンのコミット
- `AGENTS.md` の変更(人間の承認が必要)
- 人手確認なしの `git rm -rf` や `rm -rf` の実行

### 5. 記録して解放

完了時:

1. `NOTEBOOK.md` に追記(append-only):

   ```markdown
   ## <UTC ISO8601> — <task-id> — <agent-id>
   - やったこと:
   - わかったこと(予想外の発見があれば):
   - 触ったファイル:
   - 次のステップ(必要なら):
   ```

2. `TASKS.md` のタスクを `status: done`、または `status: blocked: <理由>` に。ブロックなら follow-up タスクを新規追加。
3. 計画が変わったら `PLAN.md` を更新(小さな更新で済ませる。大きな方針転換は `blocked: needs human` で止める)。
4. `git add -A && git commit -m "<task-id>: <一行要約>"`
5. `git push origin main`。衝突したら `git pull --rebase` → 再 push。

### 6. 終了条件

以下のいずれかでセッションを終える:

- タスク完了 + push 成功
- 進展不能(`NOTEBOOK.md` にブロッカーを明記し `status: blocked: <reason>`)
- 60 分経過(途中状態を `blocked: timeout` として記録し解放)
- 人間の判断が必要な分岐に到達(`status: blocked: needs human` にして **停止**)

## 規約

- **コミットメッセージ**:
  - クレーム: `claim: <task-id> by <agent-id>`
  - 作業: `<task-id>: <短い命令形>`
  - 完了: `done: <task-id>`
- **1 セッション 1 タスク**。複数タスクを抱えない
- 迷ったら変更せず `NOTEBOOK.md` にメモして止まる
- 時刻表記は UTC ISO 8601 (`2026-04-18T14:30:00Z`)
- エージェント ID はセッション開始時に生成、そのセッション中は一貫して使う

## ファイルごとの扱い

| ファイル | 変更可? |
|---|---|
| `AGENTS.md` | 不可(人間承認が必要) |
| `README.md` | 人間承認が必要 |
| `PLAN.md` | 可(作業が計画に影響する場合のみ) |
| `TASKS.md` | 可(クレーム / 解放 / follow-up 追加) |
| `NOTEBOOK.md` | 追記のみ |
| `src/` `scripts/` `experiments/` | タスクの範囲で可 |

## 実行環境の前提

- macOS (darwin)、`elan` + `lean` + `lake` インストール済み
- `gh` CLI は `sann-ai` として認証済み(push 権限あり)
- Python 3.11+
- mathlib4 の初期状態は未クローン(T001 で `/Users/san/mathlib4` にクローン予定)

## よくある落とし穴

- **`mathlib4` をビルドすると時間がかかる**: `lake exe cache get` を先に必ず実行
- **push 衝突時の焦り**: 必ず `git pull --rebase` → 状態再確認 → 再 push。`--force` は絶対に使わない
- **タスクの再定義**: 既存の `T00X` を別物に作り変えず、新しい ID (`T0XX`) を追加する
- **クレームしたまま忘れる**: 終了時には必ず `done` か `blocked` にしてから push
