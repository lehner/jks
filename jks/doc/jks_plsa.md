# jks_plsa

Stores the exact spectral-positivity band of output weights, given data at input weights, as a new tag.

## Synopsis

    jks_plsa database.jks tag_in list_of_weights_in list_of_weights_out omega_grid tag_out [dchi2]

## Description

The spectral density is represented on the grid `omega_grid` by weights z_j >= 0
at the grid nodes. Each input weight e_i and each output weight k is either an
int `t`, meaning `exp(-t omega)` on the grid, or a string tag holding an array on
`omega_grid` (the tag's central value is used). The data are `tag_in` selected
by the input weights: an int `t` selects `tag_in[t]`, a string at list position
`i` selects `tag_in[i]`. With the full jackknife covariance Sigma of the selected
inputs (`cov()`, optionally shrunk by `JKS_CORRELATION_STRENGTH`),
chi^2(z) = (E z - C)^T Sigma^-1 (E z - C). The tool computes the exact NNLS
tension chi_min, the record threshold chi_r^2 = chi_min^2 + dchi2, and for every
output weight the range [lo, hi] of k.z over {z >= 0, chi^2(z) <= chi_r^2}: the
Delta-chi^2 profile-likelihood interval of int rho k (solver
`jks.positive_laplace`, column generation with closed-form faces and a dual
certificate; weights are column-rescaled internally, which does not change the
result). The stored central value is the band midpoint (lo+hi)/2. Each jackknife
block and each existing `!` variation block is the band midpoint recomputed at
that resample of the inputs, at its own record threshold
chi_min(C^(b))^2 + dchi2; blocks whose selected inputs equal the mean are not
re-solved (they get the central value). The part of the half-width the
statistics does not already cover, sys = sqrt(max(half^2 - stat^2, 0)), is
stored as the variation `!band`, so that `tcov()` gives max(stat, half).

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database to read and update in place |
| `tag_in` | data tag (e.g. a correlator) |
| `list_of_weights_in` | Python list of input weights: int `t` (`exp(-t omega)`, data `tag_in[t]`) or string tag (array on the grid, data `tag_in[i]` for list position `i`) |
| `list_of_weights_out` | Python list of output weights, same element types |
| `omega_grid` | tag holding the grid nodes (central value used) |
| `tag_out` | new tag, one element per output weight; must not exist |
| `dchi2` | profile-likelihood threshold, default 1 (68% for one parameter); 3.84 for 95%; must be > 0 |

## Output

- Tag `tag_out`: central = band midpoints, stat blocks = per-resample midpoints,
  variation `!band` = central + sys. The `band` info string records dchi2,
  chi_min, record chi, grid tag, range and size, and the input weights.
- Printed: grid range, covariance condition number, positivity tension
  (chi_min, chi^2_min, with a verdict: exact fit, ordinary noise if
  chi^2_min <= number of inputs, otherwise a warning), record chi, solve time and
  max primal-dual gap, the number of re-solved blocks with min/median/max record
  chi, and a table with columns `out` (the int t, or the list position for a tag
  weight), `central`, `stat` (from `cov()` of the blocks), `sys`, `total`,
  `stat/half`, `ML k.z*` (output evaluated on the maximum-likelihood positive
  spectrum), `(c-ML)/tot`, and flags `[band-dominated]` (half > 1.5 stat) or
  `[ill-posed]` (stat > 1.5 half; a WARNING line counts these).

## Environment

- `JKS_CORRELATION_STRENGTH` (0..1): Sigma -> lambda Sigma + (1-lambda) diag(Sigma)
  for the chi^2 metric. The jackknife blocks keep the full correlations.

## Examples

```bash
jks_plsa data.jks C "[1,2,3,4]" "[0,1,4,8]" omega0 C.plsa
jks_info data.jks C.plsa
JKS_CORRELATION_STRENGTH=0.9 jks_plsa data.jks C "[1,2,3,4]" "[1,4]" omega0 C.plsa.95 3.84
```

On the 4-state synthetic `fake.jks` (grid `omega0`, 40 nodes on [0.4, 4]):
chi_min = 0.415, 20 of 41 blocks re-solved; t=1 (an input) gives
0.86626 +- 0.01621 with sys 0 and stat/half 1.00, t=0 is band-dominated
(4.96 +- 0.69 stat, 3.08 sys). The third command stores a 95% band with
shrinkage 0.9 (t=1: stat 0.0162, sys 0.0274).

## Notes

- Sanity anchor: at an input time stat/half = 1.00 and sys = 0; the half-width
  is close to the input error (lqcd, t=14: 3.498e-07 vs 3.540e-07 from `cov()`).
- Only python `int` elements are treated as times; any other non-string element
  (e.g. `2.5`) fails with `AssertionError: weight not found`. A weight tag whose
  shape differs from the grid fails with `<tag> not found`.
- Every `jks_plsa`/`jks_blsa` output uses the same variation name `band`. Within
  one database the `!band` shifts of different outputs are therefore one fully
  correlated variation (`jks_cor` shows sys correlation +1), and the `band`
  description accumulates one line per run. If `tag_in` itself carries `!band`,
  that block is re-solved and then overwritten.
- Existing `tag_out` is refused only at `res.add`, after the full computation,
  with a bare `AssertionError`; nothing is written.
- Unbounded outputs (a grid node no input weight sees, or input weights
  cancelling on part of the grid) and failed solves print `ERROR: ...` and exit 1;
  non-finite values are never stored. Integer-time weights are always bounded.
- The grid is taken as exact (no error propagated); vary it by rerunning with
  another grid tag.
- Run time: one exact solve per output at the mean plus one per re-solved block.
  With noisy data the solves take milliseconds. With very precise data from a
  smooth spectrum and many inputs the face enumeration can grow like 2^m
  (see AGENTS.md); keep the input set small.
- Non-zero chi_min is normal (the data sit near the boundary of the positive cone).

## See also

`jks_blsa`, `jks_hlt`, `jks_hlt_kernel`, `jks_cor`, `jks_info`, `jks_add`
