# jks_hlt_kernel

Stores the HLT reconstructed kernels kbar that `jks_hlt` would use, one grid-array tag per output weight.

## Synopsis

    jks_hlt_kernel database.jks tag_in list_of_weights_in list_of_weights_out omega_grid list_of_tags_out lambda [alpha [p]]

## Description

Computes the same HLT coefficients g as `jks_hlt` (W[g] = (1-lambda) A[g]/A[0] +
lambda B[g]/C0^2, trapezoidal L2 norm with weight exp(alpha omega) omega^(2p),
B = g^T Sigma g with the `cov()` of the selected inputs, C0 the mean of the first
input; weights: int `t` = `exp(-t omega)` selecting `tag_in[t]`, string = array
tag on the grid selecting `tag_in[i]` at list position `i`), and stores
kbar_j(omega) = sum_i g_i e_i(omega) on `omega_grid` instead of evaluating g.C.
g depends on the data only through Sigma and C0, so kbar is stored as a constant
array (the same in every block and variation, as `jks_add` stores constants).
kbar lies exactly in the span of the input weights.

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database to read and update in place |
| `tag_in` | data tag (enters through Sigma and C0 only) |
| `list_of_weights_in` | Python list: int `t` or string weight tag |
| `list_of_weights_out` | Python list of target kernels k |
| `omega_grid` | tag with the grid nodes; strictly increasing, >= 2 nodes |
| `list_of_tags_out` | Python list of new tag names, one per output weight, no duplicates, none may exist |
| `lambda` | in (0, 1) |
| `alpha` | exponential weight in A, default 0 |
| `p` | power weight in A, default 0 |

## Output

- One tag per entry of `list_of_tags_out`: kbar on the grid (float, formed at the
  working precision), zero error.
- Printed: grid, lambda, alpha, p, condition number, mpmath usage, and a table
  with columns `out`, `tag`, `A/A0`, `B/C0^2`, `digits` (`dbl` or mpmath digits).

## Environment

- `JKS_CORRELATION_STRENGTH` (0..1): shrinkage of Sigma toward the diagonal.

## Examples

```bash
jks_hlt_kernel data.jks C "[14,16,18,20,23,25]" "[10,30]" omega0 "['kbar10','kbar30']" 0.01
jks_plsa data.jks C "[14,16,18,20,23,25]" "['kbar10','kbar30']" omega0 C.plsa.kbar
jks_add data.jks d10 "np.exp(-10*r['omega0']) - r['kbar10']"
jks_plsa data.jks C "[14,16,18,20,23,25]" "['d10']" omega0 C.mismatch10
```

On the lattice correlator: stores `kbar10` (A/A0 2.3e-04, 48 digits) and
`kbar30` (A/A0 1.6e-07, 52 digits). `jks_hlt ... "[10,30]" ... 0.01` gives
1.47973e-04 +- 4.776e-06 for t=10; the positivity band of the same quantity
int rho kbar10 is 1.49428e-04 +- 4.352e-06 stat, 1.432e-06 sys. The band of the
mismatch int rho (k - kbar) at t=10 is 2.14e-05 +- 1.15e-05 stat, 1.88e-05 sys
(band-dominated).

## Notes

- Tag checks (list of strings, one per output weight, no duplicates, none
  existing) are made before the solve; an existing tag fails with
  `AssertionError: tags already in the database: [...]`, nothing is written.
- `B/C0^2` is the squared stat error of int rho kbar relative to C0, the mean of
  the first input (not relative to int rho kbar, as the printed legend says).
- Precision paths, convergence failure (`ERROR`, exit 1) and the requirement
  C0 != 0: as in `jks_hlt`.
- Used as output weights of `jks_plsa` with the same inputs, the kernels show
  what positivity adds to HLT; the `out` column there shows list positions for
  tag weights.
- The stored kernels are fixed arrays: they do not follow later changes of the
  data or the grid.

## See also

`jks_hlt`, `jks_plsa`, `jks_blsa`, `jks_add`
