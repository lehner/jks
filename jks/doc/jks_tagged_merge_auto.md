# jks_tagged_merge_auto

Merges several databases into a new one, prefixing each input's tags with its file name.

## Synopsis

    jks_tagged_merge_auto out.jks in1.jks [in2.jks ...]

## Description

Like `jks_tagged_merge` with the label taken from the input path:
`label = path.replace(".jks", "")`, and every tag `n` stored as `label/n`. Blocks
are united by name (missing blocks = central value). The result is written to
`out.jks` (overwritten) without compression.

## Arguments

| argument | meaning |
|---|---|
| `out.jks` | output file (overwritten) |
| `inN.jks` | input database (read only); its path gives the prefix |

## Output

Tags `<path without .jks>/<tag>`; prints `Adding <n> tagged as <label> from <file>`.

## Examples

```bash
jks_tagged_merge_auto both.jks fake.jks data.jks
```

`both.jks` holds `fake/C`, ..., `data/C`, ..., with 69 configs.

## Notes

- The label is the path as typed, directory included, and every `.jks` in it is
  removed: `sub/ens.a.jks` gives `sub/ens.a/C`, `./fake.jks` gives `./fake/C`.
- The same file given twice fails with a bare `AssertionError`.
- Variation names are not prefixed; equal names in different inputs are merged
  into one fully correlated variation.

## See also

`jks_tagged_merge`, `jks_merge`
