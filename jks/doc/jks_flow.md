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
    jks_flow rm flow.sh id
    jks_flow rebase flow.sh id parent
    jks_flow fmt flow.sh
    jks_flow gc flow.sh [-n]

## Description

A flow is a DAG of database states.  Each node is a source database, a list of
words, a step (one `jks_*` call), a loop (steps repeated for a list of values) or a
plot (a `jks_plot2` figure).  The flow file is a bash script, so `bash flow.sh`
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
| `rm id` | remove a node that no other node reads |
| `rebase id parent` | let a step or loop (and everything after it) start from another node |
| `fmt` | rewrite the file in canonical form |
| `gc [-n]` | delete stored results no current or last computed node needs (`-n`: only report) |

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
  file wins.

## See also

`jks_gui`, `jks_values`, `jks_plot2`
