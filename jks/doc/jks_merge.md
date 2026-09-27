# jks_merge

Merges all tags of several databases into a new database.

## Synopsis

    jks_merge out.jks in1.jks [in2.jks ...]

## Description

Starts an empty database and adds every tag of each input in order. Blocks are
united by name: a configuration or variation absent from an input is filled with
that tag's central value (zero shift), so inputs from different ensembles stay
uncorrelated and inputs sharing configuration names are correlated. The result is
written to `out.jks` (overwritten) without compression.

## Arguments

| argument | meaning |
|---|---|
| `out.jks` | output file (overwritten) |
| `inN.jks` | input databases (read only) |

## Output

`out.jks` with all tags; prints `Adding <n> from <file>` per input.

## Examples

```bash
jks_create_parameter params.jks mpi 0.135 0.002 L 48 0
jks_merge all.jks data.jks params.jks
```

`all.jks` has the 11 tags of `data.jks` plus `mpi` and `L`, 29 configs and the
variations `band`, `mass`, `mpi`.

## Notes

- A tag name present in two inputs fails with a bare `AssertionError` (e.g.
  `jks_merge m.jks data.jks fake.jks`: both have `C`); use `jks_tagged_merge`.
- Variations with the same name in different inputs (e.g. `!band`) become one fully
  correlated variation; differing descriptions are concatenated.
- Padding with zero-shift blocks changes the statistical error printed by
  `jks_info` (and slightly `cov()`), because the number of blocks N enters the
  normalisation, e.g. `C.exact[0]` of `fake.jks`: 2.2207e-07 with its 40 blocks,
  2.2254e-07 in a merge with 48 blocks.

## See also

`jks_tagged_merge`, `jks_tagged_merge_auto`, `jks_add_from`, `jks_take`
