# jks_plot

Plots tags of a jks database with gnuplot into a (multi-page) PDF, driven by a list of short plot commands.

## Synopsis

    jks_plot [-k] out.pdf in.jks cmd1 [cmd2 ...]

## Description

`jks_plot` reads `in.jks`, translates each command into gnuplot text and data files,
and writes them into the directory `out.pdf.input/` (`plots.plt`, `data.NNN`,
`desc.txt` and a bash script `make`).  `make` runs `gnuplot` (terminal `pdfcairo`,
`Helvetica,12`, 12cm x 9cm, fontscale 0.75), then `pdfcrop` to crop to the ink, then
`exiftool` to store the command line (`{'pwd': ..., 'argv': ...}`) in the PDF
Description field.  Data commands (`c`, `e`, `p`, ...) add curves to the current
`plot` statement; `newpage` ends it, and the next data command starts a new page.
Setting commands (`xr`, `k`, `ls`, ...) emit gnuplot `set` lines and stay in effect
for all later pages.

Each data point carries two error bars: the inner (thin, `lw 0.5`, no point) one is
the statistical error `sqrt(cov()[i][i])`, the outer one the total error
`sqrt(tcov()[i][i])` (statistical and all `!` variations).  This is the `cov()`
convention, not the bias-free one printed by `jks_info` (see `AGENTS.md`).

Commands are recognised by their first characters, checked in this order: `c`, `e`,
`p`, `s`, `P`, `Q`, `d`, `b`, `f`, `ls`, `l`, `L`, `xwrap`, `k`, `xr`, `xl`, `xt`,
`yt`, `yl`, `vl`, `yr`, `newpage`.  Fields are separated by `:`.  Anything else prints
`Unknown command ...` and is ignored.

## Arguments

| argument | meaning |
|---|---|
| `-k` | keep `out.pdf.input/` (gnuplot script, data files, `make`, uncropped `plots.pdf`); may appear anywhere |
| `out.pdf` | output PDF (cropped, with Description metadata) |
| `in.jks` | database to read (not modified) |
| `cmd1 ...` | plot commands, see the table below |

### Plot commands

`<lt>` is pasted verbatim after gnuplot's `lt`, so it is a line type number
optionally followed by more line properties (`1`, `2 pt 7 lc rgb 'red'`).  `<title>`
fields go through title substitution (below); an empty or missing title means
`notitle`.  "Index" means the element number `i` of a tag (0, 1, 2, ...).

| command | syntax | meaning | example |
|---|---|---|---|
| `c` | `c<lt>:<tag>[:<title>]` | tag vs. index with stat (inner) and total (outer) error bars; x goes through `xmap` | `c1:int.C:Original` |
| `e` | `e<lt>:<tag>[:<title>]` | the errors instead of the values: stat error (no symbol) and total error as points vs. index | `e1:C:errors` |
| `p` | `p<lt>:<xtag>:<ytag>[:<title>]` | parametric plot: mean of `ytag[i]` vs. mean of `xtag[i]` with x and y error bars (inner stat, outer total); tags must have equal length | `p1:C.4.14:int.C.4.14:xy` |
| `s` | `s<lt>:<xtag>:<ytag>:<sel>[:<title>]` | like `p` for the indices in `sel`, a Python expression passed to `eval` (`range(16,30)`, `[1,3,5]`) | `s2:C.4.14:int.C.4.14:range(16,30):sel` |
| `P` | `P<lt>:<xtag>:<ytag>[:<title>]` | like `p`, outer bars `lw 2` | `P1:C.4.14:int.C.4.14:thick` |
| `Q` | `Q<lt>:<xtag>:<ytag>[:<title>]` | like `p`, outer bars `lw 4` | `Q2:C.4.14.b:int.C.4.14.b:thicker` |
| `d` | `d<lt>:<x>:<y>:<yerr>:<title>` | one literal data point with y error bar; all five fields required, title not substituted | `d3:2:0.25:0.05:point` |
| `b` | `b<lt>:<tag>` | like `c` but without title, outer bars `lw 2`, and x is not mapped by `xwrap` | `b1:C` |
| `f` | `f<lt>:<tag>:<expr>:<x0>:<x1>[:<title>]` | error band of a function of fit parameters: `expr` is a Python expression in `x` and `p` (`p` = mean of `tag`), evaluated at 51 points on `[x0,x1]`; band = linear error propagation with `tcov()` of `tag` (`jks.write_confidence_band`, eps 1e-8), drawn filled (transparency 0.4) plus the central line | `f4:C:p[0]+p[1]*x:0:4:band` |
| `ls` | `ls` or `ls:<axes>` | `unset logscale`, or `set logscale <axes>` (`x`, `y`, `xy`) | `ls:y` |
| `l` | `l<lt>:<gnuplot expr>[:<title>]` | a gnuplot function of `x` | `l1:0.3*exp(-x):model` |
| `L` | `L<lt>:<gnuplot expr>[:<title>]` | like `l` with `lw 2` | `L2:0.2:const` |
| `xwrap` | `xwrap:<T>:<T2>` | redefine `xmap(x)=(int(x+T2-T) % T2)-(T2-T)`: indices `>= T` are shifted down by `T2`, e.g. `xwrap:32:64` shows `t=32..63` at `-32..-1` (applies to `c`, `e`, `p`, `s`, `P`, `Q`, `d`) | `xwrap:32:64` |
| `k` | `k:<key options>` | `set key <key options>` | `k:top left`, `k:off` |
| `xr` | `xr:<lo>:<hi>` | `set xrange [lo:hi]`; `*` or empty = autoscale | `xr:16:40`, `xr:*:*` |
| `yr` | `yr:<lo>:<hi>` | `set yrange [lo:hi]` | `yr:0:0.5` |
| `xl` | `xl` or `xl:<label>` | unset / set the x label (title substitution applies) | `xl:t` |
| `yl` | `yl` or `yl:<label>` | unset / set the y label | `yl:t^4 C(t)` |
| `xt` | `xt` or `xt:<l0>:<l1>:...` | text tics `l0` at x=0, `l1` at x=1, ... rotated by -45 degrees; plain `xt` restores automatic tics | `xt:a:b:c` |
| `yt` | `yt:<l0>:<l1>:...` | text tics on y at 0, 1, ...; plain `yt` does not reset (see Notes) | `yt:low:high` |
| `vl` | `vl:<x>` | vertical line at `x` from bottom to top (a gnuplot arrow; never removed on later pages) | `vl:1.5` |
| `newpage` | `newpage` | finish the current plot; later data commands go to a new page | `newpage` |

### Title substitution

In titles of `c`, `e`, `p`, `s`, `P`, `Q`, `f` and in `xl`/`yl`, every
`***<tag> [<n> [<fmt>]]***` is replaced by element `n` (default 0; negative counts from
the end) of `<tag>`: with `fmt`, as `fmt % mean`; otherwise as value(error) with the
total error (`jks.gformat`, `x 10^{..}` for exponents), or `%.2g` if the error is 0.
Fields are separated by single spaces, so `fmt` cannot contain spaces.  Example:
`c1:C:C(t) = ***C 16***` gives the title `C(t) = 1.342(24) x 10^{-5}`.  Titles use
gnuplot's enhanced text (`^`, `_`, `{/Symbol ...}`).

## Output

`out.pdf`, one page per plot group, cropped (324 x 243 pt for the examples below).
Gnuplot error output is printed as `Error: ...`; the exit status is 0 in any case.
Without `-k`, `out.pdf.input/` is removed at the end.

## Environment

| variable | meaning |
|---|---|
| `BIN` | integer `m`: for `c`, `e` and `b`, the statistical error is recomputed after binning the jackknife blocks in groups of `m` (averaged over the `m` cyclic shifts); the systematic part `tcov()-cov()` is kept.  Prints `BIN by m` |

External programs: `gnuplot` (with the `pdfcairo` terminal), `pdfcrop`, `exiftool`,
and `bash` for the generated `make` script.

## Examples

```bash
jks_plot data.pdf data.jks "xr:16:40" "xl:t" "yl:t^4 C(t)" "k:top left" \
    "c1:int.C:Original" "c2:int.Crec:Reconstructed" "c3:int.C.4.14:Positivity bound" \
    newpage "c3:int.C.4.14:A" "c4:int.C.4.14.b:B"
```

A two-page `data.pdf`: page 1 overlays three tags for t = 16..40 with a key at the top
left, page 2 two tags (x range, labels and key carry over).

```bash
jks_plot -k t.pdf data.jks "yr:0:0.5" "xr:0:5" "vl:1.5" "k:bottom left box" \
    "l1:0.3*exp(-x):model" "L2:0.2:const" "d3:2:0.25:0.05:point" "f4:C:p[0]+p[1]*x:0:4:band" \
    newpage "yr:*:*" "xr:*:*" "xwrap:32:64" "ls:y" "c1:C:C(t)"
```

Page 1: two gnuplot functions, a single point and a function band; page 2: `C` on a
log scale with t >= 32 shown at negative x.  `t.pdf.input/` is kept.

## Notes

- Setting commands must come before the first data command of a page (or right after
  `newpage`).  A setting between two data commands, or after the last one, is appended
  to the unfinished `plot` line (`... notitleset xrange [0:10]`); gnuplot reports
  `unexpected or unrecognized token: set` and stops, so that page and all later
  pages are missing or wrong.  `jks_plot2` has no such restriction.
- `c`, `e`, `p`, `s`, `P`, `Q` silently skip commands whose tag is missing; `b` and
  `f` stop with `KeyError` and leave `out.pdf.input/` behind.
- In `p`/`s`/`P`/`Q` the x coordinate is the mean of `xtag`, so `xr` refers to its
  values, not to indices.
- `yt` without labels: the code tests `len(a) == 0`, which is never true, so it emits
  `set ytics rotate by -45 ()` (automatic tics, rotated) instead of resetting.
- `out.pdf.input/` is reused if it exists (`force` is always true; the `-f` option in
  the message is disabled).
- Titles are enclosed in single quotes in the gnuplot script; a `'` in a title breaks
  the script.
- The usage text does not mention `-k`.

## See also

`jks_plot2` (same commands, matplotlib only), `jks_plot_dist`, `jks_info`, `jks_fit`.
