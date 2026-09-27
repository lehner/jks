# jks_info

Prints a database overview, or the values of a tag with statistical and systematic errors.

## Synopsis

    jks_info database.jks [tag [element]]

## Description

Reads the pickled (lz4 or plain) file directly, without the `jks` library.
Without a tag it prints the file's origin record, the configuration tags, each
variation with its description, and the list of tags. With a tag it computes, per
element, the statistical error from the non-`!` blocks in the bias-free
convention sqrt((N-1)/N sum_b (b - <b>)^2) (N = number of non-`!` blocks in the
database), and for each variation v the shift |block_v - mean|; `sys` is the
quadrature sum over all variations. Read only.

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database (not modified) |
| `tag` | tag to print |
| `element` | element index; prints this element with every error separately |

## Output

- No tag: `Origin:` (argv, pwd, hostname, user, date, argv[0].mtime of the run
  that last saved the file), `N configs:` with their names, `Variation 'v':` with
  its info string, `Tags:`.
- `tag`: header `# t, c[t], stat, sys, (stat^2+sys^2)^0.5`, then one line per
  element: index, value, stat, sys, total (`%.15g`). With
  `JKS_INFO_HUMAN_READABLE` set: index and `value(stat)_{stat}(sys)_{sys}` with two
  error digits.
- `tag element`: `value +- stat(stat) +- shift(v) ...` (zero errors omitted), then
  a LaTeX string with each error separately, variations sorted, and
  `\times 10^{n}` where needed, e.g. `0.223(13)_{stat}(08)_{band}`.
- Error convention: stat errors are smaller by sqrt((N-1)/N) than those from
  `jk.cov()` (and than those printed by `jks_plsa`, `jks_hlt`, `jks_cor`), e.g.
  C[14] of the lattice data: 3.478e-07 here vs 3.540e-07 from `cov()`.
  Correlations and variation shifts are the same in both conventions.

## Environment

- `JKS_INFO_HUMAN_READABLE`: if set (any value), the `tag` mode prints the
  compact `value(err)` format.
- `BIN=m`: in the tag modes, rebin the jackknife blocks into bins of m
  consecutive configurations (in the database's tag order) before the stat
  error; the trailing n mod m configurations are dropped; the error is averaged
  over the m cyclic shifts of the configuration order. The bins are listed on
  stderr (`# bin m configurations: ...`).

## Examples

```bash
jks_plsa data.jks C "[1,2,3,4]" "[0,1,4,8]" omega0 C.plsa
jks_info data.jks
jks_info data.jks C.plsa
jks_info data.jks C.plsa 2
JKS_INFO_HUMAN_READABLE=1 jks_info data.jks C.plsa
```

On `fake.jks`: the overview shows 40 configs, variation `band` and the tags;
`C.plsa` element 2 prints
`0.222934283938427 +- 0.0134688941430295(stat) +- 0.00804161887987442(band)` and
`0.223(13)_{stat}(08)_{band}`; the human-readable table starts with
`0 5.0(0.7)_{stat}(3.1)_{sys}`.

```bash
BIN=2 jks_info data.jks C 14
```

On the lattice data (29 configurations, 14 bins of 2, the last configuration
dropped): 3.771e-07 instead of 3.478e-07 unbinned.

## Notes

- Do not "fix" the (N-1)/N factor toward `cov()` (see AGENTS.md).
- N counts all non-`!` blocks, including configurations on which the tag was not
  measured (block = mean, e.g. the other ensemble of a merged database).
- An element with value exactly 0 is formatted with the digits of its error,
  like a small value, e.g. `0.0(1.3)_{stat} \times 10^{-2}`.
- The `BIN` cyclic-average branch carries the source comment "something goes
  wrong here"; treat binned errors with care.
- Missing tags raise `KeyError`, out-of-range elements `IndexError`.
- The usage text calls `tag` and `tag element` "single argument" and "two
  arguments" (counted after the file name).

## See also

`jks_cor`, `jks_values`, `jks_plot2`, `jks_dump_blocks`
