# Tier 2 Validation — Reproducing mathlib4 Refactor Commits

**Script**: `scripts/validate_refactors.py`
**Run date**: 2026-04-18T18:57:08Z
**Agent**: o3DTOn (T010)

## Methodology

`data/refactor_commits.jsonl` (152 entries) was filtered for entries where the
`before_def` block contains a `def` keyword and the `after_def` block contains an
`abbrev` keyword (true def→abbrev refactors).  Only 1 such entry was found (`TProd`).
Two additional small `def→def` entries were added to reach 3 total, to assess
pipeline behaviour on non-abbrev historical changes.

For each case:
1. A mathlib4 worktree was created at current HEAD.
2. The target file was overwritten with `git show <sha>^:<file>` (before state).
3. `def_to_abbrev` was applied to produce the candidate.
4. Both worktrees were built with `lake build` and compared via `evaluate()`.
5. The report was saved to `experiments/validation/<sha8>/report.txt`.

## Results

| SHA      | File / def                                         | All builds | Verdict  | Notes                              |
|----------|----------------------------------------------------|------------|----------|------------------------------------|
| 3e7a1952 | `Mathlib/Data/Prod/TProd.lean` / `TProd`           | False      | REJECTED | Pre-module-system imports; build failed |
| 1d311cba | `Mathlib/Algebra/Algebra/Subalgebra/Operations.lean` / `FixedPoints.subalgebra` | True | REJECTED | Builds pass; no unfold baseline |
| d7d8b152 | `Mathlib/Data/Num/Basic.lean` / `ofNat'`           | False      | REJECTED | Pre-module-system imports; build failed |

## Key Findings

### 1. Module-system incompatibility (commits before Dec 2024)
Commits predating mathlib4's module-system migration
(commit `6a54a80825`, December 2024) use `import Mathlib.X` syntax.  The current
toolchain (`leanprover/lean4:v4.30.0-rc2`) requires `public import` / `module`
declarations.  Reverting a file to its pre-migration content causes a build
failure even in a fresh worktree.  Two of the three cases (`3e7a1952`, `d7d8b152`)
hit this issue.

**Implication**: the 152-entry dataset is mostly from the old module-system era.
Future validation tasks should filter for entries whose SHA is reachable from a
commit later than `6a54a80825` (the module-system migration).

### 2. Successful build, metric limitation (`1d311cba` — FixedPoints.subalgebra)
Both baseline and candidate built successfully.  `def_to_abbrev` correctly
converted `def FixedPoints.subalgebra` → `abbrev FixedPoints.subalgebra`.
The pipeline returned REJECTED because the downstream file contained zero
`unfold FixedPoints.subalgebra` calls — so our improvement metric did not fire.

This is consistent with the known metric design: improvement is declared when
`unfold_count_baseline > 0` OR `unfold_count_delta < 0`.  The historical refactor
(`1d311cba`) was a signature generalisation, not a def→abbrev change, so there
are no unfold calls in the downstream.

**Implication for Tier 2**: the pipeline **correctly applies** the def→abbrev
transformation and **correctly builds** both versions.  The REJECTED verdict
reflects the current metric, not a pipeline failure.

### 3. Dataset has no strict def→abbrev entries matching the original filter
`before_def` starting with the literal string `"def "` and `after_def` starting
with `"abbrev "` — 0 matches.  Relaxing to "def keyword anywhere in block AND
abbrev keyword anywhere in after block" yields 1 match (`TProd`).  The dataset
is dominated by:
- Header-only changes (doc-comments, attributes added)
- Body-only refactors (same def keyword, proof rewritten)

## Recommendations for Next Steps

1. **Filter by commit date**: restrict future validation to commits after
   `6a54a80825` (module-system migration) so file content is compatible with
   the current toolchain.
2. **Extend metric**: cases like `FixedPoints.subalgebra` (builds OK, no unfolds)
   could use elaboration-time comparison (T011) as an additional acceptance signal.
3. **Mine current mathlib for reducibility changes**: search git log after
   Dec 2024 for `def → abbrev` diffs to build a compatible validation set.
