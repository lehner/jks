# jks_slow_fit

Same fit as `jks_fit`, but every jackknife block (and variation) is refitted by a full minimization instead of the Hessian linearization.

## Synopsis

    jks_slow_fit inout tag1 ranges1 fnc1 [tag2 ranges2 fnc2 ...] guess fittag

## Description

Argument parsing, the function signature `lambda x,p,r: <fnc>`, the range format,
the handling of `r['tag']` references (constants and frozen extra parameters), the
joint fit of several tags and the uncorrelated chi2 with the diagonal of `tcov()` of
the concatenated data are identical to `jks_fit`.  The covariance is fixed (computed
once from the full data) and used for all blocks.

The central value and then every block `b` of the database (statistical and `!`
variations) are minimized with scipy Nelder-Mead (`maxiter=10000`, tolerance
`JKS_FIT_TOL`), each block starting from the command-line `guess` (not from the
central result).  Tags used as `r['tag']` parameters take the values of the block
in every refit, as in `jks_fit`, so their fluctuation is propagated.  A block whose
minimization fails twice aborts the script with an `AssertionError`.  The database
is updated in place.

## Arguments

| argument | meaning |
|---|---|
| `inout` | database; read and rewritten in place |
| `tagK` | data tag of the K-th fitted block |
| `rangesK` | `range(a,b)`, a list, or a list of lists for several ranges (as in `jks_fit`) |
| `fncK` | body of `lambda x,p,r:` for element `x` of `tagK` |
| `guess` | python list of initial values of the free parameters |
| `fittag` | name of the output tag |

## Output

- `fittag`: concatenation over ranges of `[p_0, ..., p_{npar-1}]`.  No p-value,
  chi2, dof or npar entries are stored (`JKS_PVAL` is not read).
- `fittag.<tag>.input.<j>`: data of each fitted tag with elements outside range `j`
  set to nan.

## Environment

| variable | effect |
|---|---|
| `JKS_FIT_TOL` | minimizer tolerance (default `1e-8`) |

## Examples

```bash
jks_slow_fit data.jks C "range(11,25)" "p[0]*math.exp(-p[1]*x)" "[0.012,0.43]" sfit1
jks_slow_fit data.jks C "[ list(range(a,25)) for a in (10,11) ]" "p[0]*math.exp(-p[1]*x)" "[0.012,0.43]" sfit2
jks_fit data.jks C "range(11,25)" "p[0]*math.exp(-p[1]*x)" "[0.012,0.43]" C.fit
jks_add data.jks m "[ r['C.fit'][1] ]"
jks_slow_fit data.jks C "range(11,25)" "p[0]*math.exp(-r['m'][0]*x)" "[0.012]" asfit
```

`sfit1` = `[0.009392(462), 0.4101(41)]`, blocks agree with the `jks_fit` result to
6e-6 (0.4 s instead of <1 ms for the blocks); `sfit2` holds the parameters of the
two ranges (4 entries).  `asfit` fits only the amplitude with the energy `m` taken
from `C.fit` block by block: 0.00939175 +- 0.000462, the same as `jks_fit` with the
same arguments.

## Notes

- The Hessians are still computed (fixed step 1e-7, `JKS_HESSIAN_EPS` is not read)
  but not used for the stored result.
- Useful as a check of the linearization in `jks_fit` when the fit is strongly
  nonlinear.
- Multi-range syntax and other pitfalls as in `jks_fit`.

## See also

jks_fit, jks_model_average
