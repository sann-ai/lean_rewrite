# lean_rewrite

mathlib4 の Lean 4 定義を自動で書き換え、下流の証明がより扱いやすくなるような候補を提案する AI エージェントの研究プロジェクト。

着想元: Buzzard, Hughes, Lau, Livingston, Fernández Mir, Morrison, *Schemes in Lean*, [arXiv:2101.02602](https://arxiv.org/abs/2101.02602)。同じ数学的対象を3通りに形式化した際、後の版ほど上に乗る証明が楽になったという経験則を機械化するのが最終目標。

## 状態

フェーズ 1 (MVP) — `def → abbrev` の書き換えパイプラインを1例で通す。詳細は [PLAN.md](PLAN.md)。

## 人間向け

- [PLAN.md](PLAN.md) — 現行の実装計画
- [NOTEBOOK.md](NOTEBOOK.md) — 作業日誌 (append-only)
- [TASKS.md](TASKS.md) — タスクボード

## 自動エージェント向け

- [AGENTS.md](AGENTS.md) — **最初にここを読むこと**
