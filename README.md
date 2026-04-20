# lean_rewrite

mathlib4 の Lean 4 定義を自動で書き換え、下流の証明がより扱いやすくなるような候補を提案する AI エージェントの研究プロジェクト。

着想元: Buzzard, Hughes, Lau, Livingston, Fernández Mir, Morrison, *Schemes in Lean*, [arXiv:2101.02602](https://arxiv.org/abs/2101.02602)。同じ数学的対象を3通りに形式化した際、後の版ほど上に乗る証明が楽になったという経験則を機械化するのが最終目標。

**このリポジトリは自動研究エージェントが自律的に進める設計** で動いています。定期的に起動する scheduled-task がタスクボード(`TASKS.md`)からタスクを claim して実行し、完了を push する — という協調プロトコルを `AGENTS.md` で規定しています。人間はレビュー・タスク追加・設計議論で参加できます。詳しくは [CONTRIBUTING.md](CONTRIBUTING.md)。

## 現在の状態(スナップショット)

- **フェーズ 1 MVP 完了**: `def → abbrev` の E2E パイプラインが動作
- **Tier 4 の具体的成果**: `Nat.dist` に対して実装依存指標 −32(詳細 [`experiments/writeup.md`](experiments/writeup.md))
- **既知の限界**:
  - `@[simp]` 自動付与は実 mathlib 定義では `simp` ループを起こして全件失敗
  - Tier 2 の広い検証は 1/8 ACCEPTED — 一般化力が弱い
  - characterizing lemma の自動抽出(設計原理の本丸)は未着手
- **スケジューラ**: idle 検出により **一時停止中**。再開基準の見直し中

33 タスク完了、79→162 テスト pass。[Buzzard 原理に基づく設計方針](PLAN.md#提案アルゴリズムの設計原理-buzzard-の教訓--実装依存の抽象化) を見ると全体像が掴めます。

## 人間向けドキュメント

- [CONTRIBUTING.md](CONTRIBUTING.md) — **貢献のしかた**(読む順・参加経路・規約)
- [PLAN.md](PLAN.md) — 実装計画、Completion criteria、設計原理
- [experiments/writeup.md](experiments/writeup.md) — Tier 4 成果の研究報告
- [TASKS.md](TASKS.md) — タスクボード
- [NOTEBOOK.md](NOTEBOOK.md) — 作業日誌(append-only)
- [QUESTIONS.md](QUESTIONS.md) — 自動エージェントから人間への問い合わせ欄

## 自動エージェント向け

- [AGENTS.md](AGENTS.md) — **最初にここを読むこと**(claim / 依存遵守 / Planning when idle / Auto-pause など)
