# jks_compress

Drops configurations and variations on which no tag depends.

## Synopsis

    jks_compress in.jks out.jks

## Description

A block (configuration or `!` variation) is kept if, for at least one tag, it
differs from the central value (NaN treated as 0 for the comparison); all other
blocks are removed from every tag, and the descriptions of removed variations are
deleted. The result is written to `out.jks`, which may be the same file as
`in.jks`. Means and variation shifts are unchanged.

## Arguments

| argument | meaning |
|---|---|
| `in.jks` | database to read |
| `out.jks` | output file (overwritten; may equal `in.jks`) |

## Output

Prints `Delete variation <name>` and `Delete config <name>` for each removed block.

## Examples

```bash
jks_rm fake.jks C.plsa.1to4
jks_compress fake.jks fake.jks
```

Prints `Delete variation band`: after removing the only tag with a `band` shift the
variation is gone; the 40 configs stay.

## Notes

- Both arguments are required; with one the script fails with `IndexError` after
  reading (nothing written). There is no usage text.
- Removing configurations changes N, which changes the stat errors from `jks_info`
  and `cov()` slightly (see `jks_merge`).
- `jks_take` and `jks_add_from` compress automatically; `jks_rm`, `jks_merge` and
  the tagged merges do not.

## See also

`jks_rm`, `jks_take`, `jks_add_from`, `jks_info`
