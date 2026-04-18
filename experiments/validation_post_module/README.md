# Post-module def→abbrev Validation

Input: `data/refactor_commits_post_module.jsonl` (4 records, all post-module-system, post-2024-12)
Script: `scripts/validate_refactors_post_module.py`
Executed: 2026-04-18 by agent zv4RUw (T015)

## Results Summary

| SHA8     | Def name        | Direction    | Builds OK       | Verdict              |
|----------|-----------------|--------------|-----------------|----------------------|
| 6f0e175f | SkewPolynomial  | def→abbrev   | Both succeeded  | REJECTED (no unfold baseline) |
| 1627af05 | Q               | def→abbrev   | Both FAILED     | REJECTED (build failure) |
| 65590a2c | reverseRecOn    | def→abbrev   | Candidate FAILED| REJECTED (build failure) |
| 6eabe6b2 | FiniteAdeleRing | abbrev→def   | N/A (skipped)   | BLOCKED (no `def` in before-state) |

## Case Notes

### 6f0e175f — SkewPolynomial (def→abbrev, builds pass)
- Both baseline and candidate builds succeeded (`All builds succeeded: True`).
- **Pipeline says REJECTED** because `Baseline unfold count: 0` and `Unfold count delta: 0`.
- This is a *pipeline metric gap*: `is_improvement()` requires either a delta < 0 or a positive baseline unfold count.
  `SkewPolynomial` is used via typeclass instances, not `unfold` tactics, so neither condition is met.
- However, the historical refactor is legitimate — making `SkewPolynomial` an `abbrev` allows typeclass
  synthesis to look through it without `unfold`. Our metric misses this benefit entirely.
- **Conclusion**: `is_improvement()` is too conservative for typeclass-heavy definitions.
  A useful Tier 3 task: add a "typeclass instance count" metric or check `simp`-closure.

### 1627af05 — Q (def→abbrev, both builds fail)
- `Archive/Sensitivity.lean` fails to build with the before-state (rc=1).
- Most likely cause: the commit introduces changes beyond def→abbrev that the before-state depends on
  (e.g., removing typeclass instance declarations that conflicted with the old `def`).

### 65590a2c — reverseRecOn (def→abbrev, candidate fails)
- Baseline (original `def reverseRecOn` with explicit recursion) builds OK.
- Candidate (`abbrev reverseRecOn` with same recursive body) fails.
- Expected: the original definition uses `match` + `cast` + explicit recursion. Making it an `abbrev`
  does not change the body, but the `termination_by` proof probably breaks because `abbrev` changes
  how well-foundedness is checked. This is a legitimate case where def→abbrev is *not* safe.

### 6eabe6b2 — FiniteAdeleRing (abbrev→def, skipped)
- Before-state has `abbrev FiniteAdeleRing`, so `def_to_abbrev` finds no `def` keyword → BLOCKED.
- This is expected — our pipeline only does def→abbrev; abbrev→def commits are out of scope.

## Tier 2 Status
- 4/4 reports generated with `All builds succeeded:` and `VERDICT:` lines ✓
- 0 ACCEPTED, but acceptance criteria does not require ACCEPTED (Tier 2 only requires reports).
- Key learning: `is_improvement()` has a metric gap for typeclass-heavy definitions (SkewPolynomial).
  A future task should address this by widening the improvement criterion.
