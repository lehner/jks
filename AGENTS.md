# Working on the JKS measurement database system

Notes for agents (and people) using or extending `jks`.  They cover the data
model, the conventions every script follows, the spectral-bound tools and how to
test changes.  The mathematics of the positivity tools is documented in the note
`~/Papers/Note_Laplace_Bounds/note.tex`.

## Layout

```
jks/                  library (imported as `jks`)
  resamples.py        the database object: jks.resamples(file)
  measurements.py     jackknife objects: mean(), cov(), tcov(), addvar(), vars()
  positive_laplace.py exact positivity bands (solver behind jks_plsa)
  bounded_laplace.py  two-sided box bounds (solver behind jks_blsa)
  hlt.py              Hansen-Lupo-Tantalo coefficients (behind jks_hlt, jks_hlt_kernel)
scripts/              command-line tools, one file each, installed as-is by setup.py
setup.py              version and install_requires
```

Every file in `scripts/` is installed as a command (`glob("scripts/*")`), so do not
leave scratch or backup files there.

## Running

On this host `jks` is not pip-installed for the system `python3`.  Run scripts with
the source tree on the path:

```
export PYTHONPATH=~/jks_system_src/jks_system-1.1.0
~/jks_system_src/jks_system-1.1.0/scripts/jks_info file.jks
```

(Example drivers such as `~/SDP/positive_laplace/examples/lqcd/mk` put `scripts/`
on `PATH` instead.)  Dependencies: numpy, scipy, lz4, highspy, mpmath.

## Data model

- A database file holds a set of **tags**, each a jackknife object: the central
  value `orig` and one block per configuration (delete-one resamples).
- **Systematic variations** are extra blocks whose tag starts with `!`, e.g.
  `!band`.  Each is a single shifted evaluation: its covariance is the outer product
  `d d^T` of the shift `d = block_v - mean`.  A variation is therefore fully
  correlated between all elements and tags it shifts.
- A variation defined anywhere in the database is carried by every tag; for tags it
  does not affect, the variation block equals the mean (zero shift).
- `jk.cov()` is the statistical covariance from the non-`!` blocks, `jk.cov(v)` the
  variation `v`, `jk.tcov()` their sum.  Downstream fits use `tcov()`.
- Descriptions (`info`) are keyed by variation tag; an entry without a variation has
  nowhere to store a description.

### Covariance convention

`cov()` returns `sum_b (b - <b>)^2` over the jackknife blocks.  For a primary
observable this is N/(N-1) times the unbiased variance of the mean.  `jks_info`
prints the bias-free `(N-1)/N sum_b (b - <b>)^2` instead, so its stat errors are
smaller by sqrt((N-1)/N) than those from `cov()` (e.g. 0.5186 vs 0.5253 for N=20).
Correlations are unaffected.  The note (its jackknife covariance equation and footnote)
documents the `cov()` convention.  Do not "fix" either side without the owner's
decision: it changes every stored error.

## Script conventions

New tools should look like `scripts/jks_plsa`:

- GPL header, `import jks, sys, os, numpy as np`, usage text printed and
  `sys.exit(0)` when the argument count is wrong.
- First argument is always the database file.
- Weights: a list whose elements are either an **int `t`** (meaning `exp(-t omega)`
  on the grid) or a **string tag** (an array on `omega_grid` stored in the database).
  Integer input weights select `tag_in[t]`; a tag input weight at list position `i`
  selects `tag_in[i]`, so tag inputs need a data tag laid out in the same order.
- `JKS_CORRELATION_STRENGTH` (shrinkage toward the diagonal) and the covariance
  condition-number check (`kappa < 1e10`) are applied identically in all tools.
- Build derived quantities with `res.apply(lambda r: ...)`.  It evaluates the
  function on the central value and on every block, variations included, so stat
  blocks and systematics stay aligned (also across different tags).
- Store with `res.add(tag, jk)` then `res.save(db)`.  `res.add` refuses an existing
  tag (bare `AssertionError`); for tools that write several tags, check up front with
  `tag in res.set` and print which tags exist.
- Never store non-finite or non-converged numbers: print `ERROR: ...` and `sys.exit(1)`.
- Constant weight arrays (a grid, a kernel) are stored as
  `res.apply(lambda r: array)`, the same array in every block, as `jks_add` does.

### Owner preferences

- Store only the **statistical** error (jackknife blocks) for method choices.
  Method systematics (HLT lambda, omega-grid choice, ...) are estimated by the user by
  rerunning at several values; do not build automatic variations such as a
  lambda -> lambda/10 shift into a tool.
- Discretization errors of the omega grid have been found negligible; control them
  by varying the grid, not by adding solver complexity.
- Match the style of the surrounding code; keep comments at the density of
  `jks_plsa`.

## Spectral tools

| tool | what it stores |
|---|---|
| `jks_plsa db tag_in w_in w_out omega_grid tag_out [dchi2]` | positivity band (z >= 0); central = band midpoint, stat blocks = band centre per resample at its own record chi, `!band` = sqrt(max(half^2 - stat^2, 0)) |
| `jks_blsa ... omega_grid tag_lower tag_upper tag_out [dchi2]` | same with a box prior l <= z <= u; l=0, u=inf reproduce `jks_plsa` bit for bit |
| `jks_hlt db tag_in w_in w_out omega_grid tag_out lambda [alpha [p]]` | HLT linear estimate g.C and its jackknife blocks g.C^(b); no systematic |
| `jks_hlt_kernel db tag_in w_in w_out omega_grid list_of_tags_out lambda [alpha [p]]` | the HLT kernels kbar = sum_i g_i e_i on the grid, one tag per output weight |
| `jks_cor db tag1 t1 tag2 t2` | prints stat, per-variation shifts, combined sys and total correlation |

Notes:

- **HLT functional** (`jks/hlt.py`): W = (1-lambda) A/A0 + lambda B/C0^2, A the
  trapezoidal L2 norm on the grid with weight exp(alpha omega) omega^(2p), B = g^T Sigma
  g, C0 the mean of the first input weight.  `p` is exactly equivalent to scaling all
  input and output weights by omega^p.  No column rescaling (A is in physical units),
  unlike `jks_plsa`.
- **HLT precision**: a double-safe condition bound picks double precision (kappa <=
  1e6) or mpmath with ceil(log10 kappa)+20 digits; every mpmath solve is checked
  against one with 20 more digits and fails rather than store unconverged numbers.
  g.C and kbar are formed in mpmath (large alternating coefficients cancel).  The bound
  is safe but pessimistic (typically 45-75 digits); that costs only time.
- **HLT vs positivity**: `jks_hlt_kernel` output fed to `jks_plsa` as output weights
  shows what positivity adds to HLT for the same quantity int rho kbar.  For the HLT
  mismatch, pass `k - kbar` (built with `jks_add`) to `jks_plsa`.
- **`jks.positive_laplace` limitation**: the exact face enumeration is exponential in
  the NNLS support.  With noisy data the support is 3-6 nodes and solves are fast; with
  very precise data from a smooth spectrum and many inputs the support approaches m and
  the enumeration visits ~2^m faces (killed by memory at m=24).  A log-barrier solve of
  the dual `min_w a.w + chi|w|  s.t.  A^T w >= s k` is a robust independent check
  (agrees with the exact solver to 1e-11 where both run).

## GUI (`jks_gui`)

Optional NiceGUI web app (`pip install 'jks-system[gui]'`); `import jks` never loads it.

```
jks/gui/stats.py       vectorized stat/sys/cov of one tag, no GUI imports (validated
                       against jks_info and jk.cov()/tcov() to 1e-14)
jks/gui/database.py    read-only database view, cached per path, reload on mtime change
jks/gui/browser.py     database_view component (tag table, plots, table, correlation,
                       configuration z-scores, info); meant to become the node inspector
jks/gui/filepicker.py  picker for the host's filesystem
jks/gui/app.py         page, command line, access-token middleware
scripts/jks_gui        launcher
```

- On this host the GUI dependencies live in `~/.venvs/jks-gui` (system python has no pip):
  `PYTHONPATH=~/jks_system_src/jks_system-1.1.0 ~/.venvs/jks-gui/bin/python scripts/jks_gui db.jks`.
- Binds 127.0.0.1 and requires the token printed at startup (other users on a shared host
  can reach localhost ports).  Remote use: `ssh -L 8080:localhost:8080 host`.
- Plots follow `jks_plot2`: inner bar statistical, outer bar stat and sys in quadrature,
  default `cov()` convention; the table offers the bias-free `jks_info` convention too.
- Headless UI tests: playwright + chromium are installed in the venv; drive the page,
  take screenshots, and collect `pageerror` events.  Stop the test server by its PID
  (`$!`), not `pkill -f`/`pgrep -f` (both match the invoking shell).
- Plan: GUI is the designer of a flow (DAG of database states, one `.jks` per node,
  content-addressed cache), serialized as a bash script of `#@jks {json}` + one command
  per step, replayable without the GUI.  Writes go through the `jks_*` scripts.

## Testing changes

- Work on **copies** of databases (`cp ~/SDP/positive_laplace/examples/fake.jks
  $SCRATCH/`); every tool writes into the file it is given.
- Reference examples: `~/SDP/positive_laplace/examples/fake.jks` (4-state synthetic,
  inputs t=1..4, grid tag `omega0`) and `.../examples/lqcd/data.jks` (lattice data,
  N=28, grid `omega0` on [0.23, 1.2]).
- For refactors, record outputs before the change and require **bit-identical** means
  and jackknife covariances afterwards (`np.array_equal` on `x.mean()` and `x.cov()`),
  plus identical printed tables.
- Check both code paths where there are two (e.g. HLT double at lambda=0.5, mpmath at
  lambda=1e-4, many inputs with `list(range(4,30))` on the lqcd data).
- Sanity anchors: at an input time the plsa half-width equals the input error
  (stat/half = 1.00); an HLT kernel at an input time has A/A0 ~ 1e-12.

## Shell pitfalls seen here

- `pkill -f <pattern>` matches the invoking shell's own command line if it contains
  the pattern and kills it; use `pgrep` first or match a more specific string.
- Some `tail` builds reject `tail -1`; use `tail -n 1`.
- Long Monte-Carlo runs: launch in the background with `nohup` and print progress,
  otherwise there is no way to estimate the remaining time.
