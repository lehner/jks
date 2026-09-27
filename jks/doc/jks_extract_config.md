# jks_extract_config

Prints the single-configuration measurement of a tag, reconstructed from its delete-one jackknife block.

## Synopsis

    jks_extract_config database.jks tag config

## Description

Copies `tag` into a temporary database, drops every block that equals the
central value (configurations on which the tag was not measured and variations
that do not affect it, `compress`), and reconstructs the measurement on
configuration i as x_i = N mean - (N-1) block_i, with N the number of remaining
non-`!` blocks (`scaled_measurements`). Prints the elements of x for `config`.
Read only.

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database (not modified) |
| `tag` | tag to extract (matched with `fnmatch`, then looked up by exact name) |
| `config` | configuration tag as listed by `jks_info database.jks` |

## Output

One line per element: `t real imag` (`%.15g`). If `config` is not among the
remaining blocks: `<tag> not measured on <config>`, exit 1.

## Examples

```bash
jks_extract_config data.jks C Ca-00000400
```

On the lattice correlator `C_sp.jks` prints `0 0.333439111227861 0`,
`1 0.225864492406525 0`, ... (N = 28: configuration Ca-00000690 carries no
measurement of `C` and is dropped).

## Notes

- Bug: for a tag that carries a variation (e.g. a `jks_plsa` output with `!band`)
  the result is wrong. The configuration index is taken from the full tag list,
  in which `!` variations sort first, but the reconstructed data contain only
  the non-`!` blocks, so the output is that of a later configuration (off by the
  number of variations). Passing `'!band'` as `config` even prints the first
  configuration. Only tags without variations give correct results.
- A configuration whose block equals the mean exactly is reported as not
  measured.
- The `imag` column is 0 for real data.

## See also

`jks_info`, `jks_dump_blocks`, `jks_take`, `jks_compress`
