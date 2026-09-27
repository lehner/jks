# jks_plot_dist

Diagnostic plots (histogram, binning, sub-sample and autocorrelation checks) of the per-configuration distribution of one element of a tag.

## Synopsis

    jks_plot_dist out.pdf in.jks tag t nbins label

## Description

The tag is copied into a fresh database and compressed to the configurations it uses.
From its jackknife blocks the script reconstructs per-configuration values
(`scaled_measurements()`: `N*mean - (N-1)*block_i` over the configurations, `!`
variations are not used) of element `t` and writes, with gnuplot (postscript
terminal, 16cm x 12cm), a six-page PDF:

1. histogram of the values in `nbins` bins symmetric around the mean, drawn
   horizontally (values on the y axis, counts with `sqrt(count)` errors on the x
   axis, key title `label`), with the expected Gaussian bin counts for the same mean
   and standard deviation;
2. mean with jackknife error of the original data (x = 0) and of the data blocked by
   2 (x = 1), and a line at the bias-corrected mean;
3. to 5. the original mean (x = 0) and the means of the data split into 2, 4 and 8
   consecutive parts (x = 1, 2, ...), with the p-value of an uncorrelated constant
   fit to the part means (`p=...` label, top right) and the bias-corrected mean;
6. the autocorrelation function (normalized to 1 at distance 0, jackknife errors)
   versus the difference of configuration numbers, up to 10 times the smallest
   spacing, with a gnuplot fit `exp(-x/tau_exp)` whose value is shown in the key.

The PostScript is converted with `ps2pdf`, cropped with `pdfcrop`, and the command
line is stored in the Description field with `exiftool`.

## Arguments

| argument | meaning |
|---|---|
| `out.pdf` | output PDF |
| `in.jks` | database (read only) |
| `tag` | tag to analyse (an `fnmatch` pattern for `take`; it must match exactly this tag for `get`) |
| `t` | element index (int) |
| `nbins` | number of histogram bins (int) |
| `label` | key title of the histogram |

## Output

On stdout: `Compressed to N configs` (N counts the remaining blocks, `!` variations
included), the configurations with the 5 largest and 5 smallest values,
`B2/B1 = ...` (ratio of the blocked-by-2 to the unblocked jackknife error), the
configuration lists of each part, `Avg`, `Std` (standard deviation of the values),
`Bias`.  If the number of configurations is odd, the first value is dropped from the
binning, part and p-value analysis with a warning.  The configuration tags must
belong to one ensemble (`ens-number`), otherwise an assertion fails.

## Environment

External programs: `gnuplot`, `ps2pdf`, `pdfcrop`, `exiftool`.

## Examples

```bash
jks_plot_dist dist.pdf data.jks C 10 8 "C(10)"
jks_plot_dist dist2.pdf data.jks C.4.14 10 8 "C.4.14(10)"
```

The first prints `Compressed to 28 configs`, `B2/B1 = 1.0062`, the part lists (2
parts of 14, 4 of 7, 8 of 3 configurations), `Avg: 0.000160213`,
`Std: 3.56743e-06`, and writes a six-page `dist.pdf` (p-values 0.64, 0.5, 0.58 of
the part fits, `tau_exp` = 2.75).  The second works on a tag with a `!band`
variation (`Compressed to 29 configs`: 28 configurations plus `!band`).

## Notes

- `B2/B1` compares jackknife `cov()` errors (the N/(N-1) convention) for N
  configurations and N/2 blocks, so for uncorrelated data it is about
  `sqrt((N/2/(N/2-1))/(N/(N-1)))` above 1 (1.019 for N = 28).  Clearly larger values
  indicate autocorrelation.
- With 4 or 8 parts only `parts * floor(N/parts)` configurations are used; the
  last ones are left out (4 of 28 with 8 parts in the example).
- If a value is dropped for odd N, the part checks and their printed lists start at
  the second configuration.
- gnuplot's `fit` writes (appends to) `fit.log` in the current directory; the other
  temporary files are `tempfile.NamedTemporaryFile` objects and are not kept.
- `jks_gui`'s Distribution tab shows the same checks (histogram against a Gaussian,
  error of the mean against block size, consecutive parts with the p-value of a
  constant, autocorrelation) plus skewness, excess kurtosis and a Shapiro-Wilk
  p-value.

## See also

`jks_plot`, `jks_plot2`, `jks_info`, `jks_compress`.
