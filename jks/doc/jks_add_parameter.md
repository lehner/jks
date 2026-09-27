# jks_add_parameter

Adds fixed external parameters with an optional error to an existing database.

## Synopsis

    jks_add_parameter database.jks name1 value1 error1 [name2 value2 error2 ...]

## Description

For each triple a one-element tag `name` with central value `value` is built. It
has no statistical fluctuation (every configuration block equals the value). If
`error` is non-zero the tag gets its own systematic variation `!name` with block
`value + error`, i.e. a fully correlated shift of size `error`; with error `0` no
variation is added. The database is modified in place and saved (not compressed).

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | existing database, updated in place |
| `nameN` | tag name, also used as the variation name |
| `valueN` | central value (float) |
| `errorN` | error (float); `0` for an exact constant |

## Output

Tags `nameN` (1 element each) and, for non-zero errors, variations `nameN` with
the description `Parameter error from file <absolute path of database.jks>`.

## Examples

```bash
jks_add_parameter data.jks a0 0.5 0.01 lambda 0.1 0
```

Adds `a0 = 0.500(10)` (error carried entirely by variation `a0`) and the exact
constant `lambda = 0.1`.

## Notes

- The usage line says `pname pvalue1 perr1 [pvalue2 perr2 ...]`, but the code reads
  groups of three: `name value error`.
- An existing tag fails with a bare `AssertionError`; nothing is saved.
- The database must exist (`FileNotFoundError` otherwise); `jks_create_parameter`
  creates a new one.
- Because the variation has the parameter's name, a name equal to an existing
  variation (e.g. `band`) would make the parameter fully correlated with it.
- A parameter with non-zero error is not constant over the blocks, so `jks_values`
  rejects it.

## See also

`jks_create_parameter`, `jks_add`, `jks_add_sys`, `jks_values`
