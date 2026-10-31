# JKS_BIN

Delete-bin jackknife estimate of the statistical covariance, for studies of autocorrelations, computed from the stored delete-one blocks.

## Synopsis

    JKS_BIN=m [JKS_BIN_MODE=offsets|single|overlap] jks_<script> ...
    JKS_BIN=pattern:m[,pattern:m ...] [JKS_BIN_POOL=pattern+pattern[,...]] jks_<script> ...

## Description

Every statistical covariance taken through `jk.cov()` / `jk.tcov()` (fit weights and
parameter errors, plots, `jks_cor`, `jks_plsa`, `jks_blsa`, `jks_hlt`, `jks_model_average`,
`jks_info`, the GUI tables) is replaced by the covariance of delete-bin resamples, bins of
`m` consecutive configurations.  Nothing binned is stored: the database keeps its delete-one
blocks, so the bin size can be chosen at any later stage of an analysis, e.g. only for the
final `jks_info` or for a global fit.  Variations (`!` tags) are not affected.

**Streams.**  A configuration tag `<stream>-<label>` belongs to the stream before the last
`-` (`48VF3fh-1-00000100` is in stream `48VF3fh-1`).  Bins never cross streams; each stream
is binned in database order (the tag order, i.e. increasing label for zero-padded numbers).

**Populations.**  The streams of one jackknife.  By default every stream is its own
population, as in a merge of separately imported ensembles (`jks_tagged_merge`,
`global.jks`).  Streams imported together into one jackknife
(`jks_create_correlator_from_corrfile db ensA patA ensB patB`: one mean over all their
configurations) must be declared with `JKS_BIN_POOL`, e.g. `JKS_BIN_POOL=ensA+ensB`
(comma-separated pools, `+` joins `fnmatch` patterns; a pool takes every stream matching
one of its patterns).  The streams of a pool must have the same bin size.  Populations
add.

**Estimate.**  With the deviations d_i = b_i - orig in a population of N configurations,
deleting the m configurations of bin B shifts the estimate by

    D_B = (N - 1) / (N_kept - m) * sum_{i in B} d_i

exactly for primary data and to leading order for derived quantities (the order of the
jackknife itself); N_kept = configurations in bins.  The stat covariance of the population is

| `JKS_BIN_MODE` | |
|---|---|
| `offsets` (default) | the average of `single` over the m starting offsets s = 0..m-1 (the first s configurations of every stream dropped) |
| `single` | N_kept/N sum_B (D_B - <D>)(D_B - <D>)^T over the bins of all its streams, each from its first configuration, the trailing n mod m of each stream dropped |
| `overlap` | moving-block jackknife: all W windows of m consecutive configurations within the streams, N/(m W) sum_j D_j D_j^T (N/(N-m) times its bias-free estimate) |

The factor N_kept/N refers the error of the mean of the kept configurations to the mean of
all N, the central value (without it the error grows with the dropped fraction even
without autocorrelation).  This is the `cov()` convention (sum over the Nb bins); `jks_info`
prints the bias-free version, each population scaled by (Nb-1)/Nb ((N-m)/N for
`overlap`).  m = 1 is the ordinary jackknife (centered per population; equal to `cov()`
up to rounding).  A population on which a tag does not fluctuate (deviations below 1e-12 of
the value) contributes nothing and is not checked or reported.  All three modes were
checked for bias by Monte Carlo (iid and AR(1), pooled 24+17 configurations).

## Setting

| value | meaning |
|---|---|
| `JKS_BIN=2` | every stream in bins of 2 |
| `JKS_BIN=32F3fh-0:2,48VF3fh-1:3` | listed streams binned, every other stream unbinned |
| `JKS_BIN='48VF*:2,32F3fh-0:3'` | `fnmatch` patterns as in `jks_take`; the first matching entry wins |
| `JKS_BIN='32F3fh-0:3,*:2'` | explicit default for all streams not listed before |
| `JKS_BIN_POOL='ensA+ensB,C-s*'` | populations of several streams (see above) |

`JKS_BIN` overrides the `bin=` argument of `cov(var=None, bin=None, mode=None)` and
`tcov(bin=None, mode=None)` (same forms, also a dict `{pattern: m}`); `JKS_BIN_MODE` the
`mode=` argument.  `JKS_BIN_POOL` has no argument.  Unset (or empty), everything is exactly as without binning and nothing is
printed.

## Output (stderr)

The first time a stream is used in a process (on a tag that fluctuates on it), one line:

    # JKS_BIN 48VF3fh-1: 22 configs, bin 2 (10-11 bins, offsets)
    # JKS_BIN 32F3fh-0: 28 configs, bin 1 (no match)
    # JKS_BIN ensA (pool ensA+ensB): 24 configs, bin 2 (11-12 bins, offsets)

Once per database: a warning if some stream matched no entry (and is therefore unbinned)
while some entry matched no stream of the database, the typical typo:

    # WARNING JKS_BIN: no stream matches '48VF3fh-l'; unbinned: 48VF3fh-1

An explicit `*:m` entry leaves no stream unmatched and silences the warning (use `*:1` for
a partial list on purpose).  `jks_info db` lists all streams with their bin size and pool.

Pools are checked on every tag, once per stream: the deviations of a stream that is its own
jackknife sum to zero (exactly for primary data, to the order of bias/error for derived
quantities), those of a stream in a pooled jackknife sum to about the difference of the
stream means in units of the error.

    # WARNING JKS_BIN_POOL: the deviations of stream ensA do not sum to zero; it looks like part of a jackknife over several streams (declare them in JKS_BIN_POOL)
    # WARNING JKS_BIN_POOL: the deviations of stream ensA sum to zero; it looks like a separate jackknife, not part of pool ensA+ensB
    # WARNING JKS_BIN_POOL: in pool 'ensA+ensC' no stream matches 'ensC'

The first fires if |sum d| / |d| > 1 on some element of an undeclared stream (on all 416
tags of `global.jks` and the 824 derived tags of the per-ensemble databases of the
ensembles project the largest value is far below), the second if it is below 1e-8 on every
element of a declared one (only primary data can show it).

## Errors

A bin size leaving fewer than 2 bins in a population, or no bin in one of its streams (for
`offsets`: at every offset), different bin sizes in one pool, a non-integer or non-positive
bin size or an empty entry raise `ValueError("JKS_BIN: ...")` (only for tags that fluctuate
on that population: `JKS_BIN=2` works on every tag of `global.jks` that does not depend on
the 4-configuration `96SF3f-2`; `96SF3f-2:1,*:2` covers all);
`jks_info` prints it as `ERROR: JKS_BIN: ...` with exit status 1.  The old `BIN` variable of
`jks_info`, `jks_plot` and `jks_plot2` is refused with an error.  `jks_set_variance` refuses
to run with `JKS_BIN` set (its target error would refer to the binned covariance).

## Examples

```bash
for b in 1 2 3 4; do JKS_BIN=$b jks_info jks/48VF3fh-1.jks w0; done
JKS_BIN='48VF3fh-1:2,*:1' jks_info global.jks 48VF3fh-1/w0
JKS_BIN=2 JKS_BIN_POOL=ensA+ensB jks_info pooled.jks C
JKS_BIN=3 JKS_BIN_MODE=overlap jks_fit db.jks C "range(4,12)" "p[0]*math.exp(-p[1]*x)" "[1,0.5]" fit
```

On `48VF3fh-1` (22 configurations) the stat error of w0 is 0.01201 (bin 1), 0.01492 (2),
0.01590 (3), 0.01594 (4).

## Notes

- Results that depend on the covariance (fit central values through the weights,
  `jks_plsa` bands and their `!band` variation) depend on `JKS_BIN` like on
  `JKS_CORRELATION_STRENGTH`; flows put it into the step's key.
- With few bins the binned covariance has rank Nb-1 per stream: correlated fits and the
  spectral tools hit the condition-number check sooner.
- Without `JKS_BIN_POOL` a pooled database is treated per stream: the variance between the
  stream means is lost and the scale factor uses the stream's n instead of N (the warning
  above points to it).
- Library: `jks.binning` (`setting`, `parse`, `parse_pool`, `populations`, `rows`, `cov`,
  `describe`).

## See also

`jks_info`, `jks_plot_dist`, `jks_fit`
