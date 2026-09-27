# jks_flow

Run, inspect and edit a data flow: a bash file of `jks_*` steps whose results are cached.

## Synopsis

    jks_flow status flow.sh
    jks_flow run flow.sh [-j N] [-f] [id ...]
    jks_flow export flow.sh id out.jks|out.pdf
    jks_flow log flow.sh id
    jks_flow source flow.sh id path
    jks_flow list flow.sh id word ...
    jks_flow plot flow.sh id input out.pdf|- command ...
    jks_flow add flow.sh [VAR=value ...] id parent|- script argument ...
    jks_flow block flow.sh id parent|- [-i id] [-f file] script.sh|-
    jks_flow rm flow.sh id
    jks_flow rebase flow.sh id parent
    jks_flow fmt flow.sh
    jks_flow du flow.sh
    jks_flow import flow.sh mk
    jks_flow gc flow.sh [-n]

## Description

A flow is a DAG of database states.  Each node is a source database, a list of
words, a step (one `jks_*` call), a loop (steps repeated for a list of values), a
plot (a `jks_plot2` figure) or a block (a bash script, for what no jks script does).  The flow file is a bash script, so `bash flow.sh`
replays every step without jks_flow; `jks_flow run` does the same incrementally.

A node's result is cached under a key that hashes the script, the jks library, the
node's definition, the keys of the nodes it reads and the content of external
files.  Editing a step makes it and everything after it stale; a changed input file
is detected too, but nothing runs until `jks_flow run`.  Results are stored as
deltas (the tags that differ from the parent) in `<flow>.work/store/`; every delta is
checked to reproduce the script's output exactly.

The flow file (written by `jks_flow` and `jks_gui`, and editable by hand) has a
`#@jks {json}` line before every node:

```bash
#@jks {"id": "raw"}
jks_source raw C_sp.jks
#@jks {"id": "grid", "label": "omega grid"}
jks_step grid raw jks_add @ omega0 'np.linspace(0.23, 1.2, 60)'
#@jks {"id": "plsa"}
jks_step plsa grid jks_plsa @ C '[14,16,18,20,23,25]' 'list(range(40))' omega0 C.4.14
#@jks {"id": "sub"}
jks_step sub - jks_take @ @plsa 'C*'
#@jks {"id": "names"}
jks_list names C Crec
#@jks {"id": "int"}
jks_begin int grid
for name in $(jks_list_values names); do
  jks_apply int jks_add @ "int.${name}" "[ r['${name}'][t] * t**4 for t in range(40) ]"
done
#@jks {"id": "fig"}
jks_figure fig int jks_plot2 plots/int.pdf xr:16:40 c1:int.C:C c2:int.Crec:Crec
```

A block is a here-document run with `bash -euo pipefail` in the flow's directory:

```bash
#@jks {"id": "refit", "files": ["guess.txt"]}
jks_block refit fit lam <<'JKS'
c=$(jks_info "$DB" C 1 | head -1 | awk '{print $1}')
jks_add "$DB" guess "[$c, $(cat guess.txt)]"
jks_add_from "$DB" "$IN_lam" lam lam2
JKS
```

`$DB` is a copy of the database of the node after the id (`-`: the script creates
`$DB`); what the script leaves in `$DB` is the block's database.  Further input nodes
follow (`$IN_<id>`, other characters than letters, digits and `_` become `_`).  The
flow cannot see inside a block: its key covers the script, its input nodes, the jks
library and the `jks_*` scripts it names, and the files listed in `"files"` (globs
allowed); declare every file it reads, or changes of it go unnoticed.  Files the
script writes besides `$DB` are not tracked.  The script cannot contain a line `JKS`.

`@` is the node's own database, `@id` the database of node `id` (only for input
databases).  The word after the node id in `jks_step` is the node whose database is
copied before the script runs (`-`: the script writes a new database).  Loops
(`jks_begin id parent`, `for ... do`, `jks_apply` lines, `done`) take their values
from words, `$(seq first [step] last)`, `$(jks_values @node tag)` (a constant tag,
best kept on a side node) or `$(jks_list_values list)`; rows set several variables
(`for row in 'C 14' 'Crec 16'; do` then `read -r tag t0 <<< "$row"`).  Loop
variables go into double-quoted arguments as `$name` or `${name}`.  Iterations that
only add tags run independently ("map"), others one after the other ("sequence");
`"mode": "sequence"` in the `#@jks` line forces the latter.

## Commands

| command | meaning |
|---|---|
| `status` | every node: ok, stale (with the reason: definition, input, values or code changed, output file missing), new, failed, missing; loops with their iterations |
| `run [-j N] [-f] [id ...]` | compute the given nodes (default: all) and what they need; `-j`: steps in parallel; `-f`: recompute the given nodes even if cached |
| `export id file` | write a node's database (or a plot node's pdf) |
| `log id` | output of the step that computed the node (or of its failure) |
| `source id path` | add a source database (read only, never written) |
| `list id word ...` | add a list of words for loops |
| `plot id input out.pdf\|- cmd ...` | add a `jks_plot2` figure of node `input`; `-` keeps it in the cache |
| `add [VAR=value ...] id parent\|- script args` | add a step; the database the script writes must be `@` |
| `block id parent\|- [-i id] [-f file] script.sh\|-` | add a block with the script from a file or stdin; `-i`: further input nodes, `-f`: files it reads |
| `rm id` | remove a node that no other node reads |
| `rebase id parent` | let a step or loop (and everything after it) start from another node |
| `fmt` | rewrite the file in canonical form |
| `du` | disk usage: per node its stored result (delta, full copy, snapshot of a source or figure; loops with their iterations) and its previous result, the work directory by part, and what `gc` would free |
| `import mk` | write a new flow from an mk driver (see below); prints what was not imported and which node holds each database file at the end |
| `gc [-n]` | delete stored results no current or last computed node needs, and temporary files of killed runs (`-n`: only report) |

## Importing an mk driver

`jks_flow import flow.sh mk` reads a bash driver of `jks_*` calls and follows every
database file through it: a step on `data.jks` starts from the node that holds the
current state of `data.jks` and becomes its new state.

- `cp a.jks b.jks` and `mv` carry a state to another file; a database the driver
  reads before writing it becomes a source node.  A file modified before the driver
  creates it is also imported as a source, with its content at import time, and
  reported (it may be the output of an earlier run).
- Scripts writing a new database (`jks_take`, `jks_merge`, `jks_create_*`, ...) start
  from `-`; other databases they read become `@id` (or stay file names).
- `for` loops over words, `$(seq ...)`, nested loops and rows
  (`read -r a b <<< "$row"`) become loop nodes when their body only calls `jks_*`
  scripts on one database; a word list used by several loops becomes a list node.
- Variables with a literal value (`T=40`, also inside strings) are substituted;
  `export JKS_...` and `VAR=value jks_...` become the environment of the steps whose
  scripts use the variable; `unset` ends it.  `export PATH=...` is not needed.
- `jks_plot`/`jks_plot2` become plot nodes (inside loops they are skipped); scripts
  that only print (`jks_info`, ...) and `echo`, `set`, `mkdir` are skipped.
- Everything else (`if`, pipelines, other programs, `$(...)` outside loop values, a
  loop body writing several databases, ...) becomes a block if it names exactly one
  database file the driver works on: the name is replaced by `${DB}`, the variables
  it uses are set at the top (exported ones exported), and the block is reported
  for review; declare the files it reads.  A statement that names no database,
  several, or one inside single quotes, and `cd`, are reported and kept in the flow
  file as a comment where they were.  Nothing else is guessed.

```bash
jks_flow import ana.sh mk
jks_flow run ana.sh
```

On the lqcd example: 6 nodes (source `C_sp`, steps `omega0`, `C.4.14`, `C.4.14.b`,
loop `int`, plot `plot.data`); the database of `int` equals the `data.jks` that
`bash mk` writes.

## Environment

`JKS_FLOW_WORK` sets the work directory (default `<flow>.work` next to the flow
file).  `JKS_FLOW_VERBOSE=1` prints the output of every step during `run`.  Other
`JKS_*` variables, `BIN` and `STATS_KEEP_FIXED` of the caller are ignored by steps
(in `jks_flow run` and in `bash flow.sh`): a step sets its own, e.g.
`JKS_CORRELATION_STRENGTH=0.9 jks_step ...`.

## Examples

```bash
jks_flow source ana.sh raw C_sp.jks
jks_flow add ana.sh grid raw jks_add @ omega0 "np.linspace(0.23, 1.2, 60)"
jks_flow add ana.sh plsa grid jks_plsa @ C "[14,16,18,20,23,25]" "list(range(40))" omega0 C.4.14
jks_flow run ana.sh
jks_flow export ana.sh plsa result.jks
bash ana.sh
```

Builds a three-node flow, computes it, writes the database of `plsa`, and replays the
flow without the cache into `ana.work/files/`.

## Notes

- Every node must come after the nodes it reads; `rebase` reorders the file if needed.
- A step's script must be known to jks (see `jks/flow/registry.py`); plots use
  `jks_plot2` or `jks_plot`.
- Comments before a node are kept when the file is rewritten; comments inside loop
  bodies are not.
- Several jks_gui and jks_flow processes may use the same flow; the last writer of the
  file wins.  Do not run `gc` while another process computes the flow.
- A node's previous result (of the last run before an edit) is kept until the node is
  computed again, so the GUI can still show it; `gc` removes older ones, results of
  discarded previews and of removed nodes.  Snapshots of sources are copies made with
  `cp --reflink=auto` (`cp -c` on macOS): on copy-on-write file systems they share the
  source's blocks, so `du` overstates their disk use.

## See also

`jks_gui`, `jks_values`, `jks_plot2`
