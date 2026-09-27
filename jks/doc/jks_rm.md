# jks_rm

Removes tags matching shell-style patterns from a database, in place.

## Synopsis

    jks_rm database.jks pattern1 [pattern2 ...]

## Description

Every tag whose name matches any of the patterns (`fnmatch`: `*`, `?`, `[...]`) is
dropped; the remaining tags are copied into a new database object that is saved
over `database.jks`. The block list (configurations and variations) is kept as is:
the database is not compressed.

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database, rewritten in place |
| `patternN` | `fnmatch` pattern of tags to remove; quote it for the shell |

## Output

The database without the matched tags; nothing is printed. Patterns without a
match are ignored.

## Examples

```bash
jks_rm data.jks 'int.*' C.4.14.b
```

Leaves `C`, `Crec`, `omega0`, `omega_low`, `omega_high`, `C.4.14`.

## Notes

- Variations and configurations used only by removed tags stay in the file; run
  `jks_compress` to drop them.
- Removing every tag leaves a database without tags that keeps its configurations
  and variations; tags can be added to it again.
- Without a pattern the usage is printed and the exit code is 1 (other scripts
  exit 0).
- Tag names containing `*`, `?` or `[` need `glob.escape`-style quoting
  (`[*]`).

## See also

`jks_take`, `jks_compress`, `jks_merge`
