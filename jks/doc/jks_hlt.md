# jks_hlt

Stores the linear Hansen-Lupo-Tantalo (HLT) estimate g.C of output weights, with its jackknife blocks, as a new tag.

## Synopsis

    jks_hlt database.jks tag_in list_of_weights_in list_of_weights_out omega_grid tag_out lambda [alpha [p]]

## Description

Same calling convention as `jks_plsa`, no positivity. Weights: int `t` means
`exp(-t omega)` on `omega_grid` and selects `tag_in[t]`; a string tag at list
position `i` is an array on the grid and selects `tag_in[i]`. For each output
weight k the coefficients g minimize
W[g] = (1-lambda) A[g]/A[0] + lambda B[g]/C0^2, with
A[g] = int exp(alpha omega) omega^(2p) (k - kbar)^2 (trapezoidal rule on the
grid, physical units, no column rescaling), kbar = sum_i g_i e_i,
B[g] = g^T Sigma g (Sigma = `cov()` of the selected inputs, optionally shrunk),
and C0 the mean of the first input. g depends on the data only through Sigma
and C0. The stored value is g.C at the mean; every jackknife block and every
existing `!` variation block is g.C^(b) (the estimate is linear in C, so the
stat error is exactly the propagated one). No systematic is added.

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database to read and update in place |
| `tag_in` | data tag |
| `list_of_weights_in` | Python list: int `t` or string weight tag |
| `list_of_weights_out` | Python list of output weights (target kernels k) |
| `omega_grid` | tag with the grid nodes; must be strictly increasing, >= 2 nodes |
| `tag_out` | new tag, one element per output weight; must not exist |
| `lambda` | trade-off in (0, 1): small = faithful kernel, large stat error |
| `alpha` | exponential weight exp(alpha omega) in A, default 0 |
| `p` | power weight omega^(2p) in A, default 0; equivalent to scaling all input and output weights by omega^p; p > 0 needs omega >= 0, p < 0 needs omega > 0 |

## Output

- Tag `tag_out` with central g.C and blocks g.C^(b) (variations propagated
  linearly, zero shift for variations that do not touch the inputs).
- Printed: grid, lambda, alpha, p, covariance condition number, which output
  weights used mpmath (and the digit range) or "double precision sufficient",
  and a table with columns `out` (int t, or list position for a tag weight),
  `central`, `stat` (from `cov()` of the blocks), `A/A0` (relative L2 mismatch of
  kbar), `B/C0^2` (= (stat/C0)^2 up to shrinkage), `digits` (`dbl` or the mpmath
  working precision).

## Environment

- `JKS_CORRELATION_STRENGTH` (0..1): shrinkage of Sigma toward the diagonal in
  B[g] (changes g, not the jackknife blocks).

## Examples

```bash
jks_hlt data.jks C "[14,16,18,20,23,25]" "[10,14,18,30]" omega0 C.hlt.0.5 0.5
jks_hlt data.jks C "[14,16,18,20,23,25]" "[10,14,18,30]" omega0 C.hlt.1e-4 1e-4
```

On the lattice correlator with grid `omega0` (60 nodes on [0.23, 1.2]): at
lambda = 0.5 t=10 and t=14 use double precision and t=18, 30 mpmath (47 and 50
digits), t=14 gives 2.98891e-05 +- 3.490e-07 with A/A0 = 2.4e-07; at
lambda = 1e-4 all four use mpmath (50..54 digits) and t=14 gives
2.99328e-05 +- 3.503e-07 with A/A0 = 6.3e-11.

## Notes

- Precision paths (`jks/hlt.py`): a double-safe bound kappa on the condition of
  the scaled normal equations is formed per output. kappa <= 1e6: stacked,
  column-equilibrated least squares in double precision. Otherwise mpmath
  normal equations at ceil(log10 kappa)+20 digits, repeated with 20 more digits
  until g.C agrees to 1e-10 of the stat error (up to 4 raises). The printed
  `digits` is the precision of the accepted solve, i.e. verified against a solve
  with 20 fewer digits. Non-convergence prints `ERROR: ...` and exits 1. Integer
  weights are re-evaluated in mpmath; g.C (and kbar) are formed in mpmath because
  the coefficients alternate and cancel. The bound is pessimistic (typically
  45-75 digits); that only costs time.
- Sanity anchor: at an input time with small lambda, kbar reproduces the input
  weight (A/A0 ~ 1e-11 to 1e-16) and the result equals the input value and its
  `cov()` error (fake data, lambda 1e-6, t=1: 0.865699 +- 1.631e-02, A/A0 9.5e-17).
- The estimate is of int rho kbar, not of int rho k; nothing bounds the mismatch
  here. Use `jks_hlt_kernel` and `jks_plsa` for that.
- Only the statistical error is stored. Estimate the lambda, alpha/p and grid
  dependence yourself by rerunning.
- The first input must have nonzero mean (C0 normalizes B).
- An output weight that is zero on the grid gives g = 0 (value 0).
- An existing `tag_out` is refused only at `res.add`, after the solve, with a
  bare `AssertionError`.
- Run time grows with the mpmath digits, the number of inputs and the grid size;
  the examples above take well under a second each.

## See also

`jks_hlt_kernel`, `jks_plsa`, `jks_blsa`, `jks_info`
