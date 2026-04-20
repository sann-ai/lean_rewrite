# 貢献ガイド

このリポジトリは **自動研究エージェントが自律的にタスクを実行する** 設計で動いています。人間の貢献者も複数の経路で参加できます。

## まず読むもの(30 分程度)

この順で読むと現状が掴めます:

1. `README.md` — プロジェクトの目的と現在の状態
2. `PLAN.md` — 実装計画、Completion criteria、**設計原理(Buzzard の教訓)**
3. `experiments/writeup.md` — Tier 4 の成果と限界の記録
4. `AGENTS.md` — 自動エージェントが従うプロトコル(仕組み理解のため)
5. `TASKS.md` 末尾 — 直近のタスクと現在 `open` のタスク
6. `NOTEBOOK.md` 末尾 ~200 行 — 直近の作業ログ

メタアーキテクチャについて: このリポジトリは「GitHub 公開リポジトリ + AGENTS.md ベースの協調プロトコル + scheduled-tasks による定期自動 fire」というテンプレート(`/auto-research`)から生成されており、同じ構造を持つ兄弟リポジトリが他にも存在します。

## 参加のしかた

### A. 閲覧・議論のみ

- **GitHub Issues**: タスク提案、バグ報告、方向性の議論
- **GitHub Discussions**: 設計上の論点、論文の読み方、雑談

### B. PR で貢献

1. このリポジトリを fork
2. 変更を実装(scope の目安は下記)
3. PR を開く。レビュー後 `main` に merge

**貢献の scope**:

| 種別 | 扱い |
|---|---|
| `src/` のバグ修正、`scripts/` の改良 | **自由**。そのまま PR |
| ドキュメント校正、誤字修正 | **自由** |
| `experiments/` への新しい事例追加 | **自由** |
| 新しい変換族、新しいメトリクス、アーキテクチャ変更 | **先に Issue で議論** してから PR |
| `AGENTS.md` の変更 | **要合意**。自動エージェントの挙動を決める規約なので、単独変更は避ける |

### C. 手動でタスクを追加する

自動エージェントが動いている(もしくは一時停止中)なので、`TASKS.md` に直接タスクを追加することで「この方向に進めてほしい」とエージェントに伝えられます:

1. `TASKS.md` の末尾に新しい `T0NN` を追記(番号は既存最大値 + 1)
2. 以下を埋める:
   - `status: open`
   - `claimed_by:` (空)
   - `claimed_at:` (空)
   - `依存:` 既に `status: done` のタスク ID のみ(前方参照は禁止)
   - `内容:` エージェントが独立に実行できる粒度で、受け入れ基準 + ファイルパス + テスト要件を明記
3. commit & push(PR 経由でも直接でも可)
4. 次の cron tick でエージェントが自動で claim して実行する

### D. 自分のマシンでエージェントを並列稼働させる(上級)

運営者に声をかけてから。必要なもの:

- 自分の mathlib4 clone(使用 SHA は `NOTEBOOK.md` T001 エントリと揃える)
- Claude Code サブスクリプション
- `gh` CLI を自分の GitHub アカウントで認証
- collaborator 権限(repo 側で招待が必要)
- `mcp__scheduled-tasks__create_scheduled_task` で自分のスケジュールを登録

**衝突処理**: `AGENTS.md` の claim 機構が `git push` の直列化を利用して衝突を自動吸収します。複数人が同時に回しても git レベルで整合します。

**identity**: commit author は自分の GitHub 名義にすること(`sann-ai` 代理は厳禁)。

## 触ってはいけないもの

- **`AGENTS.md`**: 自動エージェント群の挙動を決定する規約。変更は事前議論と合意が必要
- **`PLAN.md` の Completion criteria と設計原理セクション**: 同上
- **既存の commit 履歴を書き換える force-push / rebase**: 禁止
- **CI 設定 / branch protection の変更**: 現状 `main` 直 push 運用。変えるなら事前議論

## 命名規則とコミットメッセージ

自動エージェントとの一貫性のため、人間も同じ規則で:

- タスク claim: `claim: T0NN by <agent-id>`(人間が手動で claim することは稀だが、その場合は `claim: T0NN by human-<イニシャル等>`)
- 作業 commit: `T0NN: <短い命令形>`(72 文字以内)
- 完了 commit: `done: T0NN: <一行要約>`
- タスク追加(planning 相当): `plan: add T0NN..T0MM`
- 自動タスクと無関係な修正: `docs:` / `fix:` / `refactor:` など従来の prefix

## 自動エージェントに質問したいとき

`QUESTIONS.md` は **エージェントが人間に聞く場所** なので、人間からエージェントへの指示は違う経路を使ってください:

- **直接的な指示**: `TASKS.md` に新タスクとして追加(方法 C)
- **方針転換**: `PLAN.md` の Completion criteria を更新(ただし合意必要なので通常は Issue で提案してから)
- **エージェント自身の挙動変更**: `AGENTS.md` を議論して更新

## 質問・議論の窓口

- **GitHub Issues**: タスク提案、バグ報告、短めの質問
- **GitHub Discussions**: 設計議論、アイデア出し、論文読解
- **PR レビュー**: 実装に対する細かい指摘

何から始めればいいかわからない場合: まず `TASKS.md` を眺めて、自分が興味を持った `status: open` のタスクをコメントで宣言してから取り掛かるのが最短です。
