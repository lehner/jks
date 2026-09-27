# jks_tagged_merge

Merges several databases into a new one, prefixing each input's tags with a given label.

## Synopsis

    jks_tagged_merge out.jks label1 in1.jks [label2 in2.jks ...]

## Description

Like `jks_merge`, but every tag `n` of `inN.jks` is stored as `labelN/n`, so
databases with the same tag names can be combined. Blocks are united by name
(missing blocks = central value). The result is written to `out.jks`
(overwritten) without compression.

## Arguments

| argument | meaning |
|---|---|
| `out.jks` | output file (overwritten) |
| `labelN` | prefix for the tags of `inN.jks` |
| `inN.jks` | input database (read only) |

## Output

Tags `labelN/<tag>`; prints `Adding <n> tagged as <label> from <file>` per input.

## Examples

```bash
jks_tagged_merge both.jks fake fake.jks lqcd data.jks
```

`both.jks` holds `fake/C`, ..., `lqcd/C`, ..., 69 configs and variations `band`
and `mass`.

## Notes

- Only tag names are prefixed, not variation names: `!band` of both inputs is one
  fully correlated variation.
- Using the same label for two inputs with common tag names fails with a bare
  `AssertionError`.

## See also

`jks_tagged_merge_auto`, `jks_merge`, `jks_add_from`
