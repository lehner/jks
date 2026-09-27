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
jks_add_from fake.jks data.jks C lqcd.C Crec lqcd.Crec
```

Adds the lattice correlators as `lqcd.C` and `lqcd.Crec` to `fake.jks`, which then
has 69 configs (40 + 29); the unused `mass` variation of `data.jks` is dropped by
the compression.

## Notes

- An existing target name fails with a bare `AssertionError`; nothing is saved.
- The argument check at line 21 uses `and` instead of `or`: with only
  `database.jks from.jks tag1in` (no `tag1as`) the script copies nothing but still
  compresses and rewrites the target; an unpaired trailing argument is ignored.
- Compression applies to the whole target, so it also removes pre-existing unused
  configurations and variations.
- Variations are matched by name: a `!band` in both databases becomes one fully
  correlated variation, and differing descriptions are concatenated (truncated to
  1024 characters plus `...` before each append).

## See also

`jks_take`, `jks_merge`, `jks_tagged_merge`, `jks_compress`
