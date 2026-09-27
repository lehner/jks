# jks_plot_dist

Diagnostic plots (histogram, binning, sub-sample and autocorrelation checks) of the per-configuration distribution of one element of a tag.

## Synopsis

    jks_plot_dist out.pdf in.jks tag t nbins label

## Description

The tag is copied into a fresh database and compressed to the configurations it uses.
From its jackknife blocks the script reconstructs per-configuration values
(`scaled_measurements()`: `N*mean - (N-1)*block_i`) of element `t` and builds, with
gnuplot (postscript terminal, 16cm x 12cm), a sequence of plots:

1. histogram of the values in `nbins` bins symmetric around the mean, with the
   expected Gaussian bin counts (same mean and standard deviation), titled `label`;
2. mean with jackknife error of the original data and of the data blocked by 2, and
   the bias-corrected mean;
3. to 5. means of the data split into 2, 4 and 8 consecutive parts, with the p-value of a
   constant fit to the part means (`p=...` label);
6. the autocorrelation function versus configuration distance (up to 10 times the
   smallest spacing of configuration numbers) with a fit `exp(-x/tau_exp)`.

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

On stdout: `Compressed to N configs`, the configurations with the 5 largest and 5
smallest values, `B2/B1 = ...` (ratio of blocked-by-2 to unblocked error), the
configuration lists of each part, `Avg`, `Std`, `Bias`.  If the number of
configurations is odd, one is dropped from the binning analysis with a warning.
The configuration tags must belong to one ensemble (`ens-number`), otherwise an
assertion fails.

## Environment

External programs: `gnuplot`, `ps2pdf`, `pdfcrop`, `exiftool`.

## Examples

```bash
jks_plot_dist dist.pdf data.jks C 10 8 "C(10)"
```

Untested result: in this version the script prints the configuration statistics and
the part lists and then stops with
`AttributeError: module 'jks' has no attribute 'plateau'`; no `dist.pdf` is written.

## Notes

- Broken: the part fits call `jks.plateau(...)` (line 188), which the `jks` package
  does not define, so the script aborts before any plot is made.  The description of
  the plots above is from the source only.
- The max/min listing (lines 108, 112) indexes `jk.tags`, which includes `!`
  variation tags, with indices of the statistical values only; for a tag with
  non-zero variations the printed configuration names are shifted, and the
  autocorrelation step (`int(a.split("-")[1])` on the config tags, line 72) would fail on
  `!` tags.
- Temporary files are `tempfile.NamedTemporaryFile` objects; nothing is kept.

## See also

`jks_plot`, `jks_plot2`, `jks_info`, `jks_compress`.
