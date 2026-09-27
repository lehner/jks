# jks_add_from

Copies tags from another database into a database, optionally renaming them.

## Synopsis

    jks_add_from database.jks from.jks tag1in tag1as [tag2in tag2as ...]

## Description

Opens `database.jks` (or starts an empty database if the file does not exist),
reads `from.jks`, and adds each tag `tagNin` of `from.jks` under the name
`tagNas`. Block lists are united by block name: configurations and variations
missing on one side are filled with the central value (zero shift), so data from
different ensembles stay uncorrelated. Then the whole target database is
compressed (blocks that equal the mean in every tag are dropped) and saved to
`database.jks`.

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | target database, updated in place or created |
| `from.jks` | source database (read only) |
| `tagNin` | tag name in `from.jks` |
| `tagNas` | name in `database.jks`; must not exist |

## Output

The copied tags under their new names; the configuration list is the union of both
databases after compression.

## Examples

```bash
jks_add_from C_sp.jks data.jks C.4.14 lqcd.C414 int.C lqcd.intC
jks_add_from new.jks data.jks C lqcd.C
```

The first adds the reconstructed correlator `C.4.14` and `int.C` of `data.jks` to
`C_sp.jks` as `lqcd.C414` and `lqcd.intC`; the result has the tags `C`, `Crec`,
`lqcd.C414`, `lqcd.intC`, the 29 configurations and the `!band` variation, while
the `mass` variation of `data.jks`, which does not affect these tags, is dropped by
the compression. The second creates `new.jks` with the single tag `lqcd.C` on 28
configurations: `Ca-00000690`, on which `C` was not measured, is compressed away.

## Notes

- An existing target name fails with a bare `AssertionError`; nothing is saved.
- With fewer than four arguments or an unpaired trailing `tagNin` the usage text is
  printed and the script exits with status 0 without touching the target.
- Compression applies to the whole target, so it also removes pre-existing unused
  configurations and variations.
- Variations are matched by name: a `!band` in both databases becomes one fully
  correlated variation, and differing descriptions are concatenated (truncated to
  1024 characters plus `...` before each append).

## See also

`jks_take`, `jks_merge`, `jks_tagged_merge`, `jks_compress`
