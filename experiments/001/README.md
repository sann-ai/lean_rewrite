# Experiment 001: `Nat.dist` — `def → abbrev` 候補

## 候補定義

**ファイル**: `Mathlib/Data/Nat/Dist.lean`  
**モジュール**: `Mathlib.Data.Nat.Dist`  
**定義名**: `Nat.dist`

```lean
/-- Distance (absolute value of difference) between natural numbers. -/
def dist (n m : ℕ) :=
  n - m + (m - n)
```

### 提案する変換

```lean
abbrev dist (n m : ℕ) :=
  n - m + (m - n)
```

`noncomputable` も `partial` も付いていないため `abbrev` 化は有効。

---

## 下流での使用例

### パターン 1: `unfold Nat.dist; lia` (16 件 — `Dist.lean` 本体)

`Dist.lean` 内の定理証明はほぼすべて同じパターンを持つ:

```lean
theorem dist_eq_zero {n m : ℕ} (h : n = m) : dist n m = 0 := by
  unfold Nat.dist; lia

theorem dist_tri_left (n m : ℕ) : m ≤ dist n m + n := by
  unfold Nat.dist; lia

theorem dist_add_add_right (n k m : ℕ) : dist (n + k) (m + k) = dist n m := by
  unfold Nat.dist; lia

-- 同パターンが計 16 件
```

`Nat.dist` を `abbrev` にすれば、`lia` が定義を自動的に展開するため `unfold Nat.dist` が不要になる。

### パターン 2: `simp [Adjacent, Nat.dist]` (11 件 — `Archive/Imo/Imo2024Q5.lean`)

IMO 2024 Q5 の形式化では `Nat.dist` を展開した上で `lia` や `simp` を組み合わせるパターンが多数登場する:

```lean
-- Adjacent の定義に Nat.dist が登場する
def Adjacent (x y : Cell) : Prop :=
  Nat.dist x.1 y.1 + Nat.dist x.2 y.2 = 1

-- 証明内での展開パターン
rw [Adjacent, Nat.dist] at ha
simp only [Adjacent, Nat.dist] at ha1
split_ifs <;> simp [Adjacent, Nat.dist] at * <;> lia
```

`Nat.dist` が reducible になれば、`simp only [Adjacent]` だけで `dist` の本体まで展開でき、`Nat.dist` を明示的にリストに含める必要がなくなる可能性がある。

### パターン 3: 定理名での参照 (10 件 — `Ordmap/`)

`Mathlib/Data/Ordmap/Invariants.lean` と `Mathlib/Data/Ordmap/Ordset.lean` では、
`Nat.dist_tri_*` などの補題を介して使用される (直接 `unfold` なし)。
`abbrev` 化によって新たな問題が起きる可能性は低い。

---

## `abbrev` 化が効くと期待する根拠

1. **ボディが線形算術式**: `n - m + (m - n)` は `Nat` の截断減算の和で、`omega` / `lia` が得意とする形。`abbrev` によって定義が definitionally transparent になれば、`lia` がゴールに `dist` が現れた時点で自動展開できる。

2. **unfold 回数が多い**: 本体ファイルの 16 件すべてが `unfold Nat.dist; lia` という同一パターン。`abbrev` 化後は `lia` 単体で証明できるはずで、`unfold` が削除されることで証明が短くなる。

3. **属性・特殊 modifier なし**: `@[simp]` / `@[fun_prop]` / `noncomputable` / `partial` がなく、`abbrev` 化の副作用が小さい。`@[simp]` 付き補題群 (`dist_self`, `dist_comm` 等) は `abbrev` 化後も引き続き有効。

4. **型が `ℕ → ℕ → ℕ`**: Prop でも関数型でもない値レベルの計算なので、instance synthesis や `fun_prop` に副作用を及ぼしにくい。

---

## T006 への入力パラメータ

| パラメータ | 値 |
|---|---|
| mathlib パス | `/Users/san/mathlib4` |
| 対象ファイル | `Mathlib/Data/Nat/Dist.lean` |
| 対象 def 名 | `dist` (完全修飾: `Nat.dist`) |
| 下流モジュール (評価対象) | `Mathlib.Data.Nat.Dist`, `Archive.Imo.Imo2024Q5` |

---

## 既知の懸念点

- `Nat.dist` と `dist` (metric distance) は名前空間が違うが、`open Nat` の中では `dist` が衝突する可能性がある。`abbrev` 化後に `simp` の補題適用順序が変わらないか確認が必要。
- `Mathlib/Data/Ordmap/` 内では `dist` を `abbrev` と知らずに使う証明が存在するため、ビルド確認は `Ordmap.Ordset` も含めること。
- `Archive/Imo/Imo2024Q5.lean` はビルドに時間がかかる可能性がある (evaluator の timeout を長めに設定)。
