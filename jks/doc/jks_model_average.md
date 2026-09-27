# jks_model_average

Weighted average of one parameter over several fit results, with the spread of the models stored as a systematic variation.

## Synopsis

    jks_model_average inout model1 model2 [model3 ...] index weight etag tag

## Description

Each `model` is a fit tag made by `jks_fit` with `JKS_PVAL` set, i.e. with the
trailing entries `[..., p-value, chi2, dof, npar]` (single range).  For every model
a log-weight is computed from its central values:

| `weight` | log-weight |
|---|---|
| `aic` | `-(2 (npar+1) + chi2)/2` |
| `chi2` | `-chi2/2` |
| `flat` | `0` |

The normalized weights `w_m` are fixed (central values).  The new tag is
`sum_m w_m model_m[index]`, evaluated with `res.apply` on the central value and every
block, so statistical blocks and existing variations are averaged with the same
weights.  The weighted variance of the central values,
`var = sum_m w_m (value_m - mean)^2`, is added as variation `!etag`
(block = mean + sqrt(var), so `cov(etag)` = var).  The database is updated in place.

## Arguments

| argument | meaning |
|---|---|
| `inout` | database; read and rewritten in place |
| `modelK` | fit tags to average (at least two) |
| `index` | element of the fit vectors to average (e.g. 1 for `p[1]`) |
| `weight` | `aic`, `chi2` or `flat` |
| `etag` | name of the systematic variation (without `!`) |
| `tag` | output tag |

## Output

`tag`: one-element vector `[average]` with the averaged statistical blocks and the
variation `!etag`, described as `Systematic error from model average <argv>`.

## Environment

| variable | effect |
|---|---|
| `JKS_DIST` | if set, file name for a histogram of the model-averaged distribution: 25 bins over mean +- 5 total errors; each model contributes 100000 Gaussian samples (mean, `tcov()` error of that model, seed 13) weighted by `w_m`.  Columns: bin centre, probability, bin lower edge, cumulative probability |

## Examples

```bash
for a in 10 11 12 13; do JKS_PVAL=1 jks_fit data.jks C "range($a,25)" "p[0]*math.exp(-p[1]*x)" "[0.012,0.43]" fit.t$a; done
jks_model_average data.jks fit.t10 fit.t11 fit.t12 fit.t13 1 aic model E0.aic
JKS_DIST=dist.txt jks_model_average data.jks fit.t10 fit.t11 fit.t12 fit.t13 1 flat model E0.flat
```

Averages the energy `p[1]` of four fit ranges: `E0.aic` = 0.40455 with stat error
0.0066 and `model` shift 0.0016; `E0.flat` = 0.40879 with stat 0.0049 and shift 0.0046;
`dist.txt` has 25 lines.

## Notes

- Models must carry the `JKS_PVAL` layout.  Without it `aic`/`chi2` read the wrong
  entries (silently for fits with 3 or more parameters, `IndexError` for 2).
- The `+1` in `aic` is a common constant and cancels.  There is no penalty for the
  number of data points, so for models with the same `npar`, `aic` and `chi2` give
  identical weights, favouring the range with the smallest chi2 (shortest range).
- Only the central values of chi2/npar enter the weights; the weights are not
  resampled.
- Reusing an existing `etag` (as in the example) makes the two systematics one fully
  correlated variation; the info texts are concatenated.  If the models themselves
  depend on `!etag`, the averaged shift is overwritten.
- `m.cov()` is computed per model but not used (`jks_model_average:68`).

## See also

jks_fit, jks_slow_fit, jks_info
