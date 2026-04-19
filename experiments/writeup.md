# lean_rewrite: Toward Downstream Abstraction — Tier 4 Writeup

## Background

Buzzard, Commelin, and Massot's *Schemes in Lean* (arXiv:2101.02602) formalized schemes in Lean
through three successive definitions, each an improvement over the last. The key lesson was not
merely syntactic: each revision reduced the degree to which downstream proofs depended on the
*internal construction* of a scheme. The first version forced downstream code to reach directly
into the concrete gluing construction (local rings attached via explicit maps). The second
introduced a localization predicate as an intermediate layer, so downstream proofs only had to
reason about this predicate, not about how it was assembled. The third version replaced the
custom construction with mathlib's categorical machinery (functors, limits), making scheme proofs
independent of any scheme-specific implementation detail.

The core lesson is: **a good refactor moves downstream proofs from "how the definition is built"
to "what the definition satisfies."** The `lean_rewrite` project automates detection and proposal
of such refactors, starting from the simple case of `def → abbrev` conversion and redundant
`unfold` elimination.

---

## Example: `Nat.dist` (def → abbrev + remove\_redundant\_unfolds)

### Before

`Mathlib/Data/Nat/Dist.lean` defines:

```lean
/-- Distance (absolute value of difference) between natural numbers. -/
def dist (n m : ℕ) :=
  n - m + (m - n)
```

With `def`, Lean treats `dist` as *opaque by default*: the elaborator does not unfold it unless
explicitly told to. As a result, every theorem about `dist` that needs arithmetic reasoning must
first expose its body with `unfold Nat.dist`:

```lean
theorem eq_of_dist_eq_zero {n m : ℕ} (h : dist n m = 0) : n = m := by
  unfold Nat.dist at h; lia

theorem dist_eq_sub_of_le {n m : ℕ} (h : n ≤ m) : dist n m = m - n := by
  unfold Nat.dist; lia

theorem dist_add_add_right (n k m : ℕ) : dist (n + k) (m + k) = dist n m := by
  unfold Nat.dist; lia
```

In total, the file contains **16 explicit `unfold Nat.dist` calls** and a further 17 occurrences
of implementation-dependent syntax (projections, `show`/`change` patterns involving `dist`), for
a `Baseline impl dependency count` of **33** across 21 downstream theorems.

### After (pipeline proposal)

The pipeline proposes converting `def dist` to `abbrev dist`:

```diff
-def dist (n m : ℕ) :=
+abbrev dist (n m : ℕ) :=
   n - m + (m - n)
```

With `abbrev`, Lean marks `dist` as *reducible*: the elaborator treats it as transparently as a
`let`-binding and unfolds it automatically during typeclass search, `decide`, and tactics like
`lia`, `omega`, and `simp`. Every `unfold Nat.dist` call becomes a no-op and is removed by the
`remove_redundant_unfolds` pass:

```lean
-- After: no unfold needed
theorem dist_add_add_right (n k m : ℕ) : dist (n + k) (m + k) = dist n m := by lia
```

### Metrics

| Metric | Value |
|--------|-------|
| Downstream theorems (same file) | 21 |
| `All builds succeeded` | True |
| `Baseline unfold count` | 16 |
| `Unfold count delta` | −16 |
| `Baseline impl dependency count` | 33 |
| `Impl dependency delta` | −32 |
| `VERDICT` | **IMPROVED** — patch accepted |

The pipeline's candidate patch, combined with redundant-unfold removal, reduces `impl_dependency_count`
from 33 to 1 (delta = −32). Only `dist_comm` retains a `simp [dist, add_comm]` call (which
references `dist` by name as a simp lemma hint, not as an implementation-level `unfold`).

---

## Buzzard Lens Analysis

Before the refactor, downstream theorems in `Nat.dist` follow a uniform pattern:

```
unfold Nat.dist  →  expose n - m + (m - n)  →  hand to lia
```

Every proof is coupled to the specific arithmetic body `n - m + (m - n)`. If the implementer
decided to define `dist` differently (e.g., as `max n m - min n m`), all 16 `unfold` sites would
need to be revisited.

After `def → abbrev`, downstream proofs treat `dist n m` as a transparent natural number. `lia`
reasons about it directly without knowing its body. The proofs no longer express "dist is defined
as truncated subtraction"; they express "dist is a natural number satisfying the arithmetic
inequalities." This is precisely the Buzzard lesson applied at small scale:

- **Schemes, 2nd → 3rd version**: replaced ad-hoc local-ring gluing with a localization
  predicate, then with categorical limits — downstream proofs stopped reaching into "how schemes
  are assembled" and only used "what properties schemes satisfy."
- **Nat.dist, def → abbrev**: downstream proofs stop reaching into "dist unfolds to n-m+(m-n)"
  and instead use "dist is a ℕ that lia can reason about directly."

The analogy is not perfect — `abbrev` achieves transparency by lowering the opacity wall rather
than by introducing an abstraction layer — but the *direction* is the same: reduce downstream
dependence on implementation details.

---

## Limitations

1. **Scope of `def → abbrev`**: The transformation is safe only when the definition's body
   is a simple expression that should be transparent to the elaborator. For complex predicates
   (`Irrational := ¬ ∃ q : ℚ, ...`) or lattice operations (`sup`), making the definition
   reducible breaks typeclass synthesis or proof terms that depend on the definition being
   opaque. Both `Irrational` and `sup` produced candidate build failures in T030.

2. **`@[simp]` conflicts**: Applying `@[simp]` to a definition that already has related simp
   lemmas (e.g., `divMaxPow`) can create rewriting loops, causing the candidate build to fail.
   The pipeline must detect pre-existing simp sets before proposing `@[simp]` attribution (T026).

3. **Tier 2 gap**: The pipeline reaches cumulative 1/8 ACCEPTED on historical mathlib commits.
   Most pure `def → abbrev` commits in mathlib history lack downstream `unfold` calls, so the
   pipeline correctly REJECTs them (no measurable improvement). Compound commits (where `def →
   abbrev` and `unfold` removal occur in the same commit) would yield better Tier 2 recall (T032).

---

## Next Steps

- **Tier 2**: Implement compound-commit detection (T032) to reach ≥3 ACCEPTED and satisfy the
  Tier 2 criterion.
- **Tier 3 (extended)**: The `@[simp]` attribution transformer (T023) can reduce
  `unfold X; simp`-style dependencies for definitions where `abbrev` is unsafe. This covers a
  broader class of mathlib defs.
- **Tier 4 (human review)**: The evidence here (21 downstream theorems, impl_dependency_delta=−32,
  VERDICT=IMPROVED) satisfies the numeric criteria. A human reviewer should confirm that the
  `Nat.dist` refactor represents a genuine move toward interface-level proofs in the Buzzard sense.
- **Characterizing lemmas**: For opaque definitions, automatic extraction of a minimal lemma set
  (`_eq_iff`, `_le_iff`, etc.) that covers all downstream usage would provide a true
  abstraction-layer refactor, matching the core Buzzard insight more directly than reducibility.
