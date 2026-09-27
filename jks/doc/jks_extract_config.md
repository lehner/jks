# jks_extract_config

Prints the single-configuration measurement of a tag, reconstructed from its delete-one jackknife block.

## Synopsis

    jks_extract_config database.jks tag config

## Description

Copies `tag` into a temporary database, drops every block that equals the
central value (configurations on which the tag was not measured and variations
that do not affect it, `compress`), and reconstructs the per-configuration
pseudo-values x_i = N mean - (N-1) block_i over the configurations the tag was
measured on, with N the number of those configurations (`scaled_measurements`;
`!` variation blocks are not used). Prints the elements of x for `config`.
Read only.

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database (not modified) |
| `tag` | tag to extract (matched with `fnmatch`, then looked up by exact name) |
| `config` | configuration tag as listed by `jks_info database.jks` |

## Output

One line per element: `t real imag` (`%.15g`). If `config` is not a
configuration the tag was measured on (also for a `!variation` name):
`<tag> not measured on <config>`, exit 1.

## Examples

```bash
jks_extract_config data.jks C Ca-00000400
jks_extract_config data.jks C.4.14 Ca-00000400
jks_extract_config data.jks C Ca-00000690
```

The first prints `0 0.333439111227861 0`, `1 0.225864492406525 0`, ... (the same
on `C_sp.jks`; N = 28). The second works on a tag with a `!band` variation and
prints `0 18.4184046620705 0`, `1 5.55188692787506 0`, ... The third prints
`C not measured on Ca-00000690` (exit 1): that configuration carries no
measurement of `C` and is dropped by the compression.

## Notes

- A configuration whose block equals the mean exactly is reported as not
  measured.
- The `imag` column is 0 for real data.

## See also

`jks_info`, `jks_dump_blocks`, `jks_take`, `jks_compress`
