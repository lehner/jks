# jks_plot2

Drop-in replacement for `jks_plot` that draws the same plots with matplotlib, without gnuplot, pdfcrop or exiftool.

## Synopsis

    jks_plot2 [-k] out.pdf in.jks cmd1 [cmd2 ...]

## Description

`jks_plot2` takes the same arguments and plot commands as `jks_plot` and writes the
same data files (`out.pdf.input/data.NNN`).  Instead of running gnuplot it
reimplements the parts of gnuplot 6 that `jks_plot` uses (pdfcairo terminal,
`Helvetica,12` at fontscale 0.75, 12cm x 9cm page, autoscaling and tics, margins, key
layout, enhanced text, point symbols, the default line type colours), renders with
matplotlib's PDF backend, crops each page to its ink bounding box (like `pdfcrop`) and
stores the command line `{'pwd': ..., 'argv': ...}` as XMP `dc:description` (read by
`exiftool` as Description, like `jks_plot`).

Inner error bars are the statistical error `sqrt(cov()[i][i])`, outer ones the total
error `sqrt(tcov()[i][i])` (`cov()` convention, see `AGENTS.md`).

Commands are collected first and rendered per page: setting commands are applied in
order, and a page is drawn at each `newpage` (and at the end) if it holds at least one
data command.  Settings persist to later pages, as in gnuplot.

## Arguments

| argument | meaning |
|---|---|
| `-k` | keep `out.pdf.input/` (`data.NNN`, `desc.txt`, `plots.pdf`); may appear anywhere |
| `out.pdf` | output PDF |
| `in.jks` | database to read (not modified) |
| `cmd1 ...` | plot commands, see the table below |

### Plot commands

Same dispatch as `jks_plot` (first characters, in the order `c`, `e`, `p`/`s`/`P`/`Q`,
`d`, `b`, `f`, `ls`, `l`/`L`, `xwrap`, `k`, `xr`, `xl`, `xt`/`yt`, `yl`, `vl`, `yr`,
`newpage`; anything else prints `Unknown command ...`).  `<lt>` is a line type number
optionally followed by line properties (`lw`, `pt`, `ps`, `lc`/`linecolor` with
`rgb '<name>'`, `'#rrggbb'` or a number, `dt`); `<title>` fields go through title
substitution (below).

| command | syntax | meaning | example |
|---|---|---|---|
| `c` | `c<lt>:<tag>[:<title>]` | tag vs. index with stat (inner) and total (outer) error bars; x mapped by `xwrap` | `c1:int.C:Original` |
| `e` | `e<lt>:<tag>[:<title>]` | stat error (no symbol) and total error as points vs. index | `e1:C:errors` |
| `p` | `p<lt>:<xtag>:<ytag>[:<title>]` | mean of `ytag[i]` vs. mean of `xtag[i]` with x and y error bars; equal lengths required | `p1:C.4.14:int.C.4.14:xy` |
| `s` | `s<lt>:<xtag>:<ytag>:<sel>[:<title>]` | like `p` restricted to the indices in `sel` (Python expression, `eval`) | `s2:C.4.14:int.C.4.14:range(16,30):sel` |
| `P` | `P<lt>:<xtag>:<ytag>[:<title>]` | like `p`, outer bars `lw 2` | `P1:C.4.14:int.C.4.14:thick` |
| `Q` | `Q<lt>:<xtag>:<ytag>[:<title>]` | like `p`, outer bars `lw 4` | `Q2:C.4.14.b:int.C.4.14.b:thicker` |
| `d` | `d<lt>:<x>:<y>:<yerr>:<title>` | one literal point with y error bar; all fields required, title not substituted | `d3:2:0.25:0.05:point` |
| `b` | `b<lt>:<tag>` | like `c`, no title, outer bars `lw 2`, not mapped by `xwrap` | `b1:C` |
| `f` | `f<lt>:<tag>:<expr>:<x0>:<x1>[:<title>]` | band of the Python expression `expr(x, p)`, `p` = mean of `tag`, 51 points on `[x0,x1]`, linear error propagation with `tcov()` (`jks.write_confidence_band`); filled (alpha 0.4) plus central line | `f4:C:p[0]+p[1]*x:0:4:band` |
| `ls` | `ls` or `ls:<axes>[ <base>]` | switch log scale off for x and y, or on for the given axes (`x`, `y`, `xy`; default base 10) | `ls:y` |
| `l` | `l<lt>:<expr>[:<title>]` | a function of `x` in gnuplot syntax (see Notes) | `l1:0.3*exp(-x):model` |
| `L` | `L<lt>:<expr>[:<title>]` | like `l` with `lw 2` | `L2:0.2:const` |
| `xwrap` | `xwrap:<T>:<T2>` | x -> `(int(x+T2-T) mod T2)-(T2-T)`, e.g. `xwrap:32:64` shows `t=32..63` at `-32..-1` | `xwrap:32:64` |
| `k` | `k:<key options>` | gnuplot `set key` options (`on`, `off`, `top`, `bottom`, `left`, `right`, `center`, `inside`, `outside`, `above`, `below`, `Left`, `Right`, `box`, `reverse`, `invert`, `samplen`, `spacing`, `width`, `height`, `maxrows`, `maxcols`, `title`, `opaque`, `at`, ...) | `k:top left`, `k:bottom left box`, `k:off` |
| `xr` | `xr:<lo>:<hi>` | x range; `*` or empty = autoscale; limits are gnuplot expressions | `xr:16:40`, `xr:*:*` |
| `yr` | `yr:<lo>:<hi>` | y range | `yr:0:0.5` |
| `xl` | `xl` or `xl:<label>` | unset / set x label (title substitution applies) | `xl:t` |
| `yl` | `yl` or `yl:<label>` | unset / set y label | `yl:t^4 C(t)` |
| `xt` | `xt` or `xt:<l0>:<l1>:...` | text tics at x = 0, 1, ... rotated by -45 degrees; plain `xt` restores automatic tics | `xt:a:b:c:d` |
| `yt` | `yt:<l0>:<l1>:...` | text tics at y = 0, 1, ...; plain `yt` keeps automatic tics but rotates them (as `jks_plot`) | `yt:low:high` |
| `vl` | `vl:<x>` | vertical line at `x` over the full plot height; stays on later pages | `vl:1.5` |
| `newpage` | `newpage` | start a new page | `newpage` |

### Title substitution

As in `jks_plot`: `***<tag> [<n> [<fmt>]]***` in titles of `c`, `e`, `p`, `s`, `P`,
`Q`, `f` and in `xl`/`yl` becomes element `n` (default 0, negative from the end) of
`<tag>`, formatted as value(total error) by `jks.gformat`, or `fmt % mean`.  Example
`c1:C:C(t) = ***C 16***` -> `C(t) = 1.342(24) x 10^{-5}`.  Enhanced text (`^`, `_`,
`{...}`, `{/Symbol ...}`, `@`, `&`, `~`) is rendered.

## Output

`out.pdf` with one cropped page per plot group (324 x 243 pt for the examples below).
If no page could be drawn, `out.pdf` is not written and `Error: no plot was generated`
is printed.  Warnings and errors are printed at the end as `Error: ...`; the exit status
is 0.  Without `-k`, `out.pdf.input/` is removed.

## Environment

| variable | meaning |
|---|---|
| `BIN` | integer `m`: statistical errors of `c`, `e`, `b` recomputed from jackknife blocks binned in groups of `m` (averaged over cyclic shifts); systematic part kept.  Prints `BIN by m` |

Dependencies: numpy, the `jks` package and matplotlib (with fontTools); nothing
external.  Fonts: the first available of Nimbus Sans, Helvetica, Arial, Liberation
Sans, TeX Gyre Heros, else DejaVu Sans.  Exact agreement with gnuplot's output is
aimed at gnuplot 6.0.2 with Nimbus Sans.

## Examples

```bash
jks_plot2 data.pdf data.jks "xr:16:40" "xl:t" "yl:t^4 C(t)" "k:top left" \
    "c1:int.C:Original" "c2:int.Crec:Reconstructed" "c3:int.C.4.14:Positivity bound" \
    newpage "c3:int.C.4.14:A" "c4:int.C.4.14.b:B"
```

A two-page `data.pdf`, visually the same as `jks_plot` with the same arguments.

```bash
jks_plot2 -k t.pdf data.jks "yr:0:0.5" "xr:0:5" "vl:1.5" "k:bottom left box" \
    "l1:0.3*exp(-x):model" "L2:0.2:const" "d3:2:0.25:0.05:point" "f4:C:p[0]+p[1]*x:0:4:band" \
    newpage "yr:*:*" "xr:*:*" "xwrap:32:64" "ls:y" "c1:C:C(t)"
```

Page 1: functions, a literal point and a band; page 2: `C` on a log scale with
t >= 32 at negative x.  `t.pdf.input/` keeps `data.000`-`data.002`, `desc.txt`,
`plots.pdf`.

```bash
jks_plot2 red.pdf data.jks "xr:0:10" "c1 pt 7 lc rgb 'red':Crec:red"
```

`Crec` with filled red circles.

## Notes

- Differences from `jks_plot`: a setting placed between or after data commands of a
  page is applied to that whole page (in `jks_plot` it breaks the gnuplot script);
  `-k` keeps no `plots.plt`/`make`.
- Expressions in `l`, `L`, `xr`, `yr`, `vl` and key positions are evaluated by a
  gnuplot-like evaluator: numbers, `x`, `pi`, `+ - * / % **`, comparisons, `&& || !`,
  and `abs sgn sqrt exp log log10 sin cos tan asin acos atan atan2 sinh cosh tanh asinh
  acosh atanh floor ceil int real imag gamma lgamma erf erfc norm`; integer `/` and
  `%` follow gnuplot.  User variables and other gnuplot functions give `undefined
  variable`.
- Unsupported pieces warn instead of failing: key `font`, `textcolor`, `offset`,
  `keywidth`; `dt` other than 1 (drawn solid); log scale on axes other than x/y.
- A gnuplot-style error (e.g. `all points y value undefined!`, an x range excluding
  all data) stops rendering; pages drawn before it are kept, as with gnuplot.
- `c`, `e`, `p`, `s`, `P`, `Q` skip missing tags silently; `b` and `f` stop with
  `KeyError` and leave `out.pdf.input/` behind.
- `yt` without labels does not reset the y tics (mirrors `jks_plot`).
- The usage text does not mention `-k`.

## See also

`jks_plot`, `jks_plot_dist`, `jks_info`, `jks_fit`.
