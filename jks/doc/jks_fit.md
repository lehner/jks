# jks_fit

Uncorrelated least-squares fit of one or more tags to user-supplied functions; jackknife blocks are obtained by Hessian linearization around the central fit.

## Synopsis

    jks_fit inout tag1 ranges1 fnc1 [tag2 ranges2 fnc2 ...] guess fittag

## Description

The data of all listed tags are concatenated into one vector and fitted
simultaneously; parameters are shared between tags through the common vector `p`.
Each `fnc` is the body of `lambda x,p,r: <fnc>` (evaluated in the script namespace,
so `math` and `np` are available), where `x` is the element index inside that tag
(e.g. the time slice), `p` the parameter list and `r` a dictionary of other database
tags that the function may reference as `r['tag']`.

`ranges` is evaluated with `eval` and converted with `list()`.  A flat list or
`range(a,b)` is one range; a list of lists defines several ranges, and a separate
fit is done for each range `j`.  All tags must give the same number of ranges; fit
`j` uses range `j` of every tag.

`r` references: before fitting, the functions are evaluated with the guess; each
unknown `r['tag']` is looked up in the database.  If the tag has zero total
covariance it is a constant (printed as `Constant ...`).  Otherwise its mean is
appended to `p` as extra parameters (printed as `Add tag as p[(a, b)]`); these are
frozen at the tag's mean during minimization, and its fluctuation per block is
propagated into the fit parameters (see below).  An unknown tag prints
`Unknown key` and exits with status 1.

Fit: `chi2 = sum_i (f(x_i) - y_i)^2 / sigma_i^2` over the points of the range,
with `sigma_i^2` the diagonal of `tcov()` of the concatenated data (statistical plus
all `!` variations; correlations are dropped).  Minimizer: scipy Nelder-Mead
(`jks.qfit`), `maxiter=10000`, tolerance `JKS_FIT_TOL`.  If the first minimization
does not report success it is restarted once from its result; if that also fails
the script stops with an `AssertionError` and nothing is written.

Jackknife blocks: only the central value is minimized.  Finite-difference second
derivatives of chi2 with respect to parameters (`P`) and data (`X`) at the minimum
give, for every block `b` (statistical and variations alike),
`p_b = p_0 - P^-1 X (y_b - y_0) - P^-1 P_frozen (q_b - q_0)` where `q` are the
frozen `r[...]` parameters.  The step is `JKS_HESSIAN_EPS` (absolute, in the units of
the parameters and data).  The database is updated in place.

## Arguments

| argument | meaning |
|---|---|
| `inout` | database; read and rewritten in place |
| `tagK` | data tag of the K-th fitted block |
| `rangesK` | python expression for the element indices of `tagK`: `range(a,b)`, a list, or a list of lists for several ranges |
| `fncK` | body of `lambda x,p,r:` giving the model for element `x` of `tagK` |
| `guess` | python list with the initial values of the free parameters (its length is the number of free parameters `npar`) |
| `fittag` | name of the output tag |

## Output

- `fittag`: concatenation over ranges `j` of the per-range vectors
  - default: `[p_0, ..., p_{npar-1}]`
  - with `JKS_PVAL`: `[p_0, ..., p_{npar-1}, p-value, chi2, dof, npar]`; the last four
    are central-fit numbers copied into every block (zero error).
  `dof` = number of points in the range minus `npar`; the p-value is the right-tail
  chi2 probability `1 - gammainc(dof/2, chi2/2)`.  Frozen `r[...]` parameters are not
  stored.
- `fittag.<tag>.input.<j>`: for every fitted tag and range `j`, the tag's data with
  elements outside the range set to nan (used by plotting / fit overlays).

The central results (`guess -> [params, p, chi2, dof, npar]`) are printed for each
range in either case.

## Environment

| variable | effect |
|---|---|
| `JKS_PVAL` | if set (any value), append `[p-value, chi2, dof, npar]` per range |
| `JKS_FIT_TOL` | minimizer tolerance (default `1e-8`) |
| `JKS_HESSIAN_EPS` | finite-difference step for the Hessians (default `1e-6`) |

## Examples

```bash
jks_fit data.jks C "range(11,25)" "p[0]*math.exp(-p[1]*x)" "[0.012,0.43]" fit1
JKS_PVAL=1 jks_fit data.jks C "[ list(range(a,25)) for a in (10,11,12) ]" "p[0]*math.exp(-p[1]*x)" "[0.012,0.43]" fit3
jks_fit data.jks C "range(11,25)" "p[0]*math.exp(-p[1]*x)" Crec "range(11,25)" "p[2]*math.exp(-p[1]*x)" "[0.012,0.43,0.012]" fitj
jks_add data.jks E0 "[r['fit1'][1]]"
jks_fit data.jks C "range(11,25)" "p[0]*math.exp(-r['E0'][0]*x)" "[0.012]" fitA
```

On the lattice correlator `C` (29 configurations): `fit1` = `[0.009392(462),
0.4101(41)]` plus `fit1.C.input.0`; `fit3` has 18 entries (three ranges t=10..24,
11..24, 12..24, each `[A, E, p, chi2, dof, 2]`, p = 0.019, 0.72, 0.97) and tags
`fit3.C.input.0..2`; `fitj` is a joint fit of `C` and `Crec` with shared energy
`p[1]` (3 entries, plus `fitj.C.input.0` and `fitj.Crec.input.0`); `fitA` fits only
the amplitude with the energy taken from tag `E0`, and its error (0.000462) includes
the propagated fluctuation of `E0`.

## Notes

- Several ranges must be given as a list of lists, e.g.
  `[ list(range(a,25)) for a in (10,11,12) ]`.  `[range(10,25),range(11,25)]` fails
  with `TypeError: unsupported operand type(s) for +: 'int' and 'range'`.
- A bad initial guess can make Nelder-Mead "converge" without moving (flat chi2);
  the Hessian is then singular and the stored tag is silently all nan (e.g. guess
  `[1,50]` for the example above stores `[nan nan]`).  Check the printed
  `guess -> result` line.
- The fit is uncorrelated (diagonal of `tcov()`), so chi2 and the p-value are those
  of an uncorrelated fit.
- In a multi-tag fit the element index of tag K is offset internally by the lengths
  of the preceding tags (printed ranges show the offsets, e.g. 76..89 for the second
  tag of length 65); `x` passed to `fncK` is the index within `tagK`.
- `fittag` and the `.input.` tags must not exist (`res.add` raises `AssertionError`).
- The tag name `#.#fit#.#` is used internally (not saved).
- The four `JKS_PVAL` entries are what `jks_model_average` expects.

## See also

jks_slow_fit, jks_model_average, jks_add (fit/cfit helpers), jks_plot2, jks_correlator_reconstruct
