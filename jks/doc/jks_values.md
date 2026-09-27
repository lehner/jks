# jks_values

Prints the elements of a constant tag, one per line, for use in shell loops.

## Synopsis

    jks_values database.jks tag

## Description

Reads the tag's central value, flattens it, and checks that it is finite and that
every block (configurations and variations) equals it. Each element is printed as
an integer if it is integral (and below 2^53), otherwise as Python's shortest
round-trip `repr`. The database is not modified.

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database to read |
| `tag` | constant tag (e.g. a parameter list or a grid) |

## Output

One value per line on stdout. Errors (`ERROR: <tag> not in <db>`, `ERROR: <tag>
has non-finite values`, `ERROR: <tag> fluctuates over the blocks; loop values must
be constant`) are printed to stdout with exit code 1.

## Examples

```bash
jks_add fake.jks lambda '[1e-4, 1e-3, 0.5, 1.0, 2.0]'
jks_values fake.jks lambda
for lam in $(jks_values fake.jks lambda); do echo "lambda=$lam"; done
```

Prints `0.0001`, `0.001`, `0.5`, `1`, `2`, then one `lambda=...` line per value.

## Notes

- A parameter with non-zero error (`jks_add_parameter`) has a shifted variation
  block and is rejected as fluctuating; add it with error `0`.
- Used by `jks_flow` loops (`$(jks_values @node tag)`) and their bash replay.
- Wrong argument count prints the usage and exits 0.

## See also

`jks_add`, `jks_add_parameter`, `jks_flow`
