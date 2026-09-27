# jks_gui

Graphical browser for jks databases and designer of data flows, served as a local web page.

## Synopsis

    jks_gui [--host HOST] [--port PORT] [--jobs N] [--work DIR] [--history FILE]
            [--no-token] [--native] [--browser] [file.jks | flow.sh ...]

## Description

jks_gui is a NiceGUI web application (install with `pip install 'jks-system[gui]'`).
It prints a URL with an access token; open it in a browser.  On a remote machine,
forward the port first (`ssh -L 8080:localhost:8080 host`, as printed).

A **database** (`.jks`) opens in the browser: tag list with an fnmatch filter, plots
(inner bars statistical, outer bars stat and sys in quadrature, as `jks_plot2`),
value table, correlation matrix, per-configuration z-scores, fit overlay (the band of
a `jks_fit` result), and a step panel that previews a `jks_*` step on a copy before
it is committed to the file (the previous version is kept in `.jks_work/backup/`).

A **flow** (`.sh`, see `jks_flow`) opens as a graph of database states.  Selecting a
node shows its database; the step panel adds steps and loops after it or edits a
node (everything after an edited node is recomputed); the plot panel makes
`jks_plot2` figures; rebase lets a node start from another one.  Changed input files
make nodes stale; "Run stale" computes them.  The storage button in the header shows
the disk usage of the flow's work directory; its dialog lists every node's stored
result and cleans up results no node needs (as `jks_flow gc`).  The selected node's
toolbar shows the size of its result.

## Arguments

| argument | meaning |
|---|---|
| `file.jks`, `flow.sh` | databases or flows to offer; the first one is opened |
| `--host HOST` | interface to bind (default 127.0.0.1) |
| `--port PORT` | port (default 8080) |
| `--jobs N` | steps computed in parallel in flows (default 2) |
| `--work DIR` | work directory for step previews, relative to each database (default `.jks_work`) |
| `--history FILE` | file of recently used step-panel values (default `~/.config/jks_gui/history.json`) |
| `--no-token` | do not require the access token |
| `--native` | open in a desktop window (needs pywebview; no token) |
| `--browser` | open a browser even over ssh |

## Examples

```bash
jks_gui data.jks
jks_gui --port 8123 ana.sh
```

Opens a database, or a flow on port 8123.

## Notes

- The access token matters on shared machines: every user of the host can reach a
  localhost port.
- The input history survives restarts; it is shared by all jks_gui processes.
- `?` next to a script name shows its page of this documentation.

## See also

`jks_flow`, `jks_info`, `jks_plot2`
