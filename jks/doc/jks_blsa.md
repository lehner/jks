# jks_blsa

Stores the exact band of output weights under a box prior lower <= z <= upper on the spectral weights, as a new tag.

## Synopsis

    jks_blsa database.jks tag_in list_of_weights_in list_of_weights_out omega_grid tag_lower tag_upper tag_out [dchi2 [error_tag]]

## Description

As `jks_plsa`, with positivity z_j >= 0 replaced by l_j <= z_j <= u_j at every
node of `omega_grid` (solver `jks.bounded_laplace`). z_j is the weight of the
delta function at node j (rho = sum_j z_j delta(omega - omega_j)), so the bounds
are per node, not per unit omega. `tag_lower` and `tag_upper` are arrays on the
grid (central values used); lower must be finite, upper may be `inf` node by
node. Weights: int `t` means `exp(-t omega)` and selects `tag_in[t]`; a string
tag at list position `i` is an array on the grid and selects `tag_in[i]`.
chi_min is now the distance of the data to the image of the box, the band is
[lo, hi] of k.z over the box intersected with chi^2 <= chi_min^2 + dchi2, and
central value, stat blocks (band midpoint per resample and per existing
variation, at its own record chi; blocks with unchanged inputs are not
re-solved) and the `!band` variation sqrt(max(half^2 - stat^2, 0)) are formed
and stored exactly as in `jks_plsa`.

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database to read and update in place |
| `tag_in` | data tag |
| `list_of_weights_in` | Python list: int `t` or string weight tag (see Description) |
| `list_of_weights_out` | Python list of output weights, same element types |
| `omega_grid` | tag holding the grid nodes |
| `tag_lower` | tag with the lower bound per node (finite) |
| `tag_upper` | tag with the upper bound per node (`inf` = unbounded), >= lower |
| `tag_out` | new tag, one element per output weight; must not exist |
| `dchi2` | profile-likelihood threshold, default 1; must be > 0 |
| `error_tag` | name of the band variation, default `band`, as in `jks_plsa` |

## Output

Tag `tag_out` with central, stat blocks and `!band` as for `jks_plsa`; the `band`
info string additionally names the lower and upper tags ("Box prior: lower ...,
upper ..."). The printed report and table have the same columns as `jks_plsa`
(`out`, `central`, `stat`, `sys`, `total`, `stat/half`, `ML k.z*`, `(c-ML)/tot`,
flags), with `ML k.z*` the maximum-likelihood spectrum within the bounds.

## Environment

- `JKS_CORRELATION_STRENGTH` (0..1): shrinkage of the chi^2 metric toward the
  diagonal, as in `jks_plsa`.

## Examples

```bash
jks_add data.jks omega0 "np.linspace(0.23, 1.2, 60)" omega_low "0*r['omega0']" omega_inf "0*r['omega0'] + np.inf" omega_cap "0*r['omega0'] + 0.02"
jks_blsa data.jks C "[14,16,18,20,23,25]" "[0,10,14,30]" omega0 omega_low omega_inf C.pos
jks_blsa data.jks C "[14,16,18,20,23,25]" "[0,10,14,30]" omega0 omega_low omega_cap C.cap
```

On the lattice correlator (`C_sp.jks`, 28 measured configurations): `C.pos`
reproduces `jks_plsa` (t=0: 4.04 +- 2.14 stat, 3.42 sys); with the cap
z_j <= 0.02 `C.cap` gives t=0: 0.232 +- 0.027 stat, 0.223 sys, while t=14 and
t=30 are unchanged (t=14: 2.99571e-05 +- 3.498e-07, sys 0).

## Notes

- Bit-for-bit identity with `jks_plsa` holds for lower = 0 and upper = `np.inf`
  (checked: equal `mean()`, `cov()`, `tcov()`). A large finite cap such as
  `+ 1e9` (as in `examples/lqcd/mk`) gives the same means but covariances that
  differ at ~5e-11 relative.
- The bounds are converted to the internally rescaled units (z_j -> d_j z_j);
  the result does not depend on this.
- If the prior binds at the best fit, chi_min increases and the band is relative
  to the constrained minimum. A cap active at some resamples only makes the
  centre move more (watch `stat/half`). The result is conditional on the prior;
  quote it.
- A node with upper = inf that no input weight sees makes any output nonzero
  there unbounded: `ERROR: ... UNBOUNDED`, exit 1. Nodes with a finite upper
  bound are always bounded.
- Lower/upper tags of the wrong shape fail with an `AssertionError`; lower not
  finite or upper < lower raise `ValueError` in the solver.
- Shared `!band` variation name (`error_tag`), refusal of an existing `tag_out`, int-only
  times and run-time behaviour: as in `jks_plsa`.
- Box splits make the enumeration heavier than `jks_plsa` (3^|S| lower/upper
  splits of a candidate set); the capped example still runs in a fraction of a
  second.

## See also

`jks_plsa`, `jks_hlt`, `jks_add`, `jks_info`, `jks_cor`
