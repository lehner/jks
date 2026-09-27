# jks_create_parameter

Creates a new database holding fixed parameters with optional errors.

## Synopsis

    jks_create_parameter output.jks name1 value1 error1 [name2 value2 error2 ...]

## Description

Same construction as `jks_add_parameter`, but starts from an empty database and
writes `output.jks`, replacing any existing file. Each parameter is a one-element
tag with no statistical blocks; a non-zero error becomes a variation `!name` with
block `value + error`. The database has no configurations, only variations.

## Arguments

| argument | meaning |
|---|---|
| `output.jks` | file to write (overwritten) |
| `nameN` | tag name, also used as the variation name |
| `valueN` | central value (float) |
| `errorN` | error (float); `0` for an exact constant |

## Output

Tags `nameN`; for non-zero errors variations `nameN` described as
`Parameter error from file <absolute path of output.jks>`.

## Examples

```bash
jks_create_parameter params.jks mpi 0.135 0.002 L 48 0
```

Writes `params.jks` with 0 configs, `mpi = 0.1350(20)_{mpi}` and the exact
constant `L = 48`.

## Notes

- The usage line says `pname pvalue1 perr1 [pvalue2 perr2 ...]`; the code reads
  groups of three `name value error`.
- An existing `output.jks` is overwritten, not extended.
- Without any parameter the script crashes in `save` with
  `AttributeError: ... '_clone_type_str'` and writes nothing.
- A repeated name fails with a bare `AssertionError`.
- Combine with data via `jks_merge` or `jks_add_from`; the parameters then carry
  zero shift on all configurations.

## See also

`jks_add_parameter`, `jks_merge`, `jks_add_from`
