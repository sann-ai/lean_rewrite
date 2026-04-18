# Tier 2 Validation v2 — Post-Module def↔abbrev (T021)

Pipeline: T019 (instance_context_count signal) + T020 (termination_by guard).

| sha8 | def_name | All builds succeeded | Baseline instance ctx | VERDICT |
|------|----------|---------------------|----------------------|---------|
| 6f0e175f | SkewPolynomial | True | 6 | ACCEPTED |
| 1627af05 | Q | False | 3 | REJECTED |
| 65590a2c | reverseRecOn | False | N/A | SKIPPED_TERMINATION_BY |
| 6eabe6b2 | FiniteAdeleRing | False | N/A | BLOCKED: def_to_abbrev: no top-level `def FiniteAdeleRing` found in s |
| f3acad5a | runThe | True | 0 | REJECTED |
| a04c5481 | freeGroupEmptyEquivUnit | False | 0 | REJECTED |

**ACCEPTED: 1/6**

Tier 2 criterion: ≥3 known mathlib refactor commits reproduced (pipeline returns ACCEPTED or SKIPPED_TERMINATION_BY counts as a known-safe signal).
