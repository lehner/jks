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
The flow machinery (`jks/flow/`, behind `jks_flow` and the GUI's steps) needs only the
core dependencies; `jks/gui/` is installed too but only `jks_gui` needs NiceGUI.

```
jks/gui/stats.py       vectorized stat/sys/cov of one tag, no GUI imports (validated
                       against jks_info and jk.cov()/tcov() to 1e-14)
jks/gui/database.py    read-only database view, cached per path, reload on mtime change
jks/gui/browser.py     database_view component (tag table, plots, table, correlation,
                       configuration z-scores, info); meant to become the node inspector
jks/gui/filepicker.py  picker for the host's filesystem
jks/flow/registry.py   signatures of the jks_* scripts (argv = head + repeat*k + tail +
                       optional[:j], typed roles, env vars); parse/build round-trips argv
jks/flow/runner.py     runs one step on a copy in the work directory, content-hash cache,
                       diff of two databases, commit with hard-link backup and history.sh
jks/gui/step.py        step panel: form from the registry, pasted commands, preview, commit
jks/gui/history.py     recently used field values (20 per "script:argument", "env:VAR",
                       "command"), ~/.config/jks_gui/history.json, merged on every save
jks/flow/core.py       flows: DAG of steps in a bash file (parse/write), engine with keys,
                       status, delta store, parallel runs, export, gc (no GUI imports)
jks/gui/flowview.py    flow page: graph (ECharts, layered layout), node inspector
                       (database_view of the node), flow_target for the step panel
jks/gui/app.py         page, command line, access-token middleware
scripts/jks_gui        launcher
scripts/jks_flow       command line for flows (status, run, export, log, add, rm, fmt, gc)
```

### Flows (`jks_flow`)

- Format: one `#@jks {json}` line + one command per node, nodes after their inputs.
  `jks_source id path` or `[VAR=x] jks_step id parent|- script argv`, with `@` = the
  node's own database and `@id` = another node's (only for `db_in` arguments).  Other
  comment lines are kept with the next node; `fmt` joins continuation lines.  The
  generated header defines the helpers, so `bash flow.sh` replays the flow into
  `<flow>.work/files/` (bash 3.2 syntax for macOS; untested there so far) and unsets
  `JKS_*`, `BIN`, `STATS_KEEP_FIXED` like the engine.
- Lists and loops: `jks_list id word ...` (no database) and loop nodes
  `jks_begin id parent` / `for v in SPEC; do` / `jks_apply id script argv` / `done`, SPEC =
  words, `$(seq ...)` (integers), `$(jks_values @node tag)` or `$(jks_list_values id)`; rows
  `for row in 'a 1' 'b 2'; do read -r x y <<< "$row"`; nesting = product.  Loop variables
  only as `$v`/`${v}` in double-quoted jks_apply arguments.  Keep parameter nodes that
  loops read (`jks_add @ lambda "[...]"`) on a side branch: a loop's key has the values,
  not the value node, so adding a value computes one iteration.
- `scripts/jks_values db tag`: elements of a constant tag, one per line (integral values
  without ".0", else shortest round-trip repr); used by both the engine and the replay.
- Loop modes: map (iterations on the parent, in parallel) if every body script has
  `appends=True` in the registry, no iteration reads a tag another writes, and at run time
  each iteration only appended tags (disjointly); then parent + appended tags in iteration
  order equals the sequential bash loop.  Otherwise sequence (iteration i+1 on i).  Every
  iteration is cached; `"mode": "sequence"` in the #@jks JSON forces it (not in the key:
  both modes give the same database).  Tested bit-identical to `bash flow.sh` for list,
  jks_values, row and nested loops, map and sequence, after incremental edits.
- Keys (Merkle): script file hash, hash of the jks library sources (jks/*.py, so a solver
  change marks results "code changed"), definition (script, parent, argv, env), keys of the
  inputs, content hash of sources and external databases, size/mtime of glob files.
  Status: ok / stale (an older result exists; "definition changed" or "input changed") /
  new / failed / missing.  Nothing runs until `jks_flow run`.
- Store (`<flow>.work/store/`): children of sources and scripts writing a new database
  are stored in full; others as a delta (changed tags + block-tag list, info, order)
  against the parent, kept only if `apply_delta` reproduces the output exactly and the
  delta has < 50% of the tags; a full copy after 7 deltas in a row.  Tested bit-identical
  to `bash flow.sh` for every node (lqcd example incl. plsa/blsa/fit/take and a
  JKS_CORRELATION_STRENGTH branch).  180 MB database, 6 steps: 173 MB store.
- Files are written with `flow._write` (resamples format, no `os.getlogin`).

- A script that is not in `registry.SCRIPTS` cannot be run from the GUI; add an entry
  when adding a script.  Deprecated (python 2, `jks_op`) scripts are left out.
- Steps run as `sys.executable script argv` with cwd = the database's directory, the
  written database replaced by a copy in `.jks_work/tmp/`, and an environment without any
  `JKS_*` variable except the step's own.  Results are bit-identical to the same command
  run by hand (tested for jks_add, jks_plsa with and without JKS_CORRELATION_STRENGTH,
  jks_rescale_variance, jks_rm, jks_take).
- Flow page (`jks_gui flow.sh`, or "new flow from this database" on a database page): the
  step panel adds a node after the selected one (preview first: the candidate flow is
  run in the work directory, then "Add ... to the flow" saves the file) or edits a step
  node (after saving, all descendants are recomputed).  Changed inputs are only flagged;
  "Run stale" computes them.  The engine runs in a worker thread with its own event loop
  (`flow_page.engine_run`); log lines and node states come back through a queue drained
  by a timer, so UI code never runs in the worker.  Notifications go through
  `flow_page.notify` (the element that triggered an action may have been deleted).
  Deleting tags in a flow proposes a `jks_rm` node.  Loops: the step panel's "loop"
  checkbox adds loop levels (list node, jks_values of a tag, words, seq, rows; nested),
  a body of one or more commands (chips; the form edits one), and the mode; `$var` is
  allowed in every field and the command box quotes such arguments with double quotes.
  Loop and list nodes are edited like steps (descendants recompute, unchanged
  iterations come from the cache).  Rebase (`flow.rebase`, `jks_flow rebase`, GUI button
  with preview) gives a step or loop another parent; its descendants stay, the file is
  reordered (stable topological order) if the new parent came later; cycles are refused.
  A step can be turned into a loop with the same id.  A loop over one variable gets a Scan tab in the
  inspector: each output template (e.g. C.hlt.$lam) against the loop value.
- Deleting tags from the tag panel runs `jks_rm` with `glob.escape`d names and commits
  only if the diff removes exactly the selected tags.
- Fit overlay (`stats.fit_band`): jks_fit stores per range j the parameters, plus
  [p-value, chi2, dof, npar] with JKS_PVAL (detected from the data), and the fitted data
  as `<fit>.<tag>.input.<j>`.  Default band: f evaluated per jackknife block and variation;
  "linear" reproduces jks_plot2 / `jks.write_confidence_band` (to 2e-8).  The function
  comes from the cached jks_fit step (`runner.find_fit`).  Multi-range fits need
  `[ list(range(a,b)) for ... ]`; a plain range object is not recognized by jks_fit.
- Cache key: script file hash, argv with the output database as a placeholder, env,
  content hash of every database read, size/mtime of glob-matched files.

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
