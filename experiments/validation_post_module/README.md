# Post-module def→abbrev Validation

Input: `data/refactor_commits_post_module.jsonl` (6 records, all post-module-system, post-2024-12)
Script: `scripts/validate_refactors_post_module.py` (original 4); `scripts/validate_t018.py` (new 2)

## Results Summary

| SHA8     | Def name                | Direction  | Builds OK         | Verdict                       | By          |
|----------|-------------------------|------------|-------------------|-------------------------------|-------------|
| 6f0e175f | SkewPolynomial          | def→abbrev | Both succeeded    | REJECTED (no unfold baseline) | T015/zv4RUw |
| 1627af05 | Q                       | def→abbrev | Both FAILED       | REJECTED (build failure)      | T015/zv4RUw |
| 65590a2c | reverseRecOn            | def→abbrev | Candidate FAILED  | REJECTED (build failure)      | T015/zv4RUw |
| 6eabe6b2 | FiniteAdeleRing         | abbrev→def | N/A (skipped)     | BLOCKED (no `def` in before)  | T015/zv4RUw |
| f3acad5a | runThe                  | def→abbrev | Both succeeded    | REJECTED (no unfold baseline) | T018/FOWSt4 |
| a04c5481 | freeGroupEmptyEquivUnit | def→abbrev | Both FAILED       | REJECTED (build failure)      | T018/FOWSt4 |

## Case Notes

### 6f0e175f — SkewPolynomial (def→abbrev, builds pass)
- Both baseline and candidate builds succeeded (`All builds succeeded: True`).
- **Pipeline says REJECTED** because `Baseline unfold count: 0` and `Unfold count delta: 0`.
- This is a *pipeline metric gap*: `is_improvement()` requires either a delta < 0 or a positive baseline unfold count.
  `SkewPolynomial` is used via typeclass instances, not `unfold` tactics, so neither condition is met.
- However, the historical refactor is legitimate — making `SkewPolynomial` an `abbrev` allows typeclass
  synthesis to look through it without `unfold`. Our metric misses this benefit entirely.
- **Conclusion**: `is_improvement()` is too conservative for typeclass-heavy definitions.
  T019 (add `instance_context_count` signal) should address this.

### 1627af05 — Q (def→abbrev, both builds fail)
- `Archive/Sensitivity.lean` fails to build with the before-state (rc=1).
- Most likely cause: the commit introduces changes beyond def→abbrev that the before-state depends on
  (e.g., removing typeclass instance declarations that conflicted with the old `def`).

### 65590a2c — reverseRecOn (def→abbrev, candidate fails)
- Baseline (original `def reverseRecOn` with explicit recursion) builds OK.
- Candidate (`abbrev reverseRecOn` with same recursive body) fails.
- The original definition uses `match` + `cast` + explicit recursion with `termination_by`.
  Making it an `abbrev` breaks the well-foundedness check.
- T020 (add `has_termination_by` safety guard) will prevent this class of failure.

### 6eabe6b2 — FiniteAdeleRing (abbrev→def, skipped)
- Before-state has `abbrev FiniteAdeleRing`, so `def_to_abbrev` finds no `def` keyword → BLOCKED.
- This is expected — our pipeline only does def→abbrev; abbrev→def commits are out of scope.

### f3acad5a — runThe (def→abbrev, builds pass)
- Before-state: `@[inline] protected def runThe (ω : Type u) (cmd : WriterT ω M α) : M (α × ω) := cmd`
- Pipeline converts to `@[inline] protected abbrev runThe ... := cmd` (preserving body). Both builds pass.
- **Pipeline says REJECTED** because `Baseline unfold count: 0` — no `unfold runThe` downstream.
- The historical commit also changes the body (`cmd` → `cmd.run`) and removes `protected`; those are
  beyond what `def_to_abbrev` captures. Even so, the reducibility benefit is real but invisible to
  the current metric.
- Same metric gap as SkewPolynomial: T019's `instance_context_count` signal may close this.

### a04c5481 — freeGroupEmptyEquivUnit (def→abbrev, both builds fail)
- Both baseline and candidate fail to build (rc=1).
- The before-state of `FreeGroup/Basic.lean` at `a04c5481^` uses the older structure syntax
  (`where toFun := ... invFun := ... left_inv := ...`) which conflicts with the current HEAD state
  of the file and its dependencies. This is the same class of failure as `1627af05/Q`.

## Tier 2 Status
- 6/6 reports generated, each with `All builds succeeded:` and `VERDICT:` lines ✓
- 0 ACCEPTED across all 6 cases, but Tier 2 acceptance criteria only requires reports with those lines.
- **Key pattern**: The 2 build-success cases (SkewPolynomial, runThe) both hit the same metric gap —
  typeclass/reducibility improvements are invisible to the unfold-count metric.
  T019 (`instance_context_count` enhancement) directly addresses this.
- **Build-failure pattern**: 3 commits fail because the before-state file, when transplanted into
  HEAD worktree, conflicts with the evolved surrounding context. This is an inherent limitation of
  the HEAD-worktree + file-swap approach for commits that change more than just the keyword.
- **Next steps**: T019 (metric improvement) and T020 (termination_by safety guard) address the
  two main classes of pipeline weakness revealed by this validation.
