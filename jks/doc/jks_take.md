# jks_take

Writes the tags of a database that match given patterns into a new database.

## Synopsis

    jks_take out.jks in.jks pattern1 [pattern2 ...]

## Description

Starts an empty database, adds every tag of `in.jks` matching each `fnmatch`
pattern in turn, compresses the result (drops configurations and variations on
which no selected tag depends) and writes it to `out.jks`, replacing any existing
file. `in.jks` is not modified.

## Arguments

| argument | meaning |
|---|---|
| `out.jks` | output file (overwritten) |
| `in.jks` | source database |
| `patternN` | `fnmatch` pattern of tags to copy |

## Output

`out.jks` with the selected tags; prints `Adding <pattern>` per pattern.

## Examples

```bash
jks_take sub.jks data.jks C 'omega*'
```

Writes `C`, `omega0`, `omega_low`, `omega_high` with 28 configs and no variations
(`band` and `mass` are dropped by the compression).

## Notes

- A tag matched by two patterns fails with a bare `AssertionError`; nothing is
  written.
- If no tag matches at all, the script crashes in `compress` (`TypeError: object
  of type 'NoneType' has no len()`) and writes nothing.
- Argument order is output first, then input.

## See also

`jks_rm`, `jks_add_from`, `jks_merge`, `jks_compress`
