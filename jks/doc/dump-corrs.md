# dump-corrs

Prints the contents of a binary correlator file as text, optionally only one tag.

## Synopsis

    dump-corrs file [tag]

## Description

Reads the records of `file` (header as in `list-corrs`: int32 tag length, tag, uint32
CRC32, uint16 size `ln`, uint16 flags).  For each selected record it reads the stored
data, expands the compressed forms given by the flags (`empty`, `real`, `imag`, `symm`,
`asymm`) to `ln` complex numbers, checks the CRC32, and prints a header line followed by
one line per element.  Records of other tags are skipped.

Plain `jks.corrIO.writer` files (no flags) are read correctly as long as each record
has fewer than 65536 elements (little-endian machine).

## Arguments

| argument | meaning |
|---|---|
| `file` | correlator file |
| `tag` | optional: print only records whose tag is exactly `tag` |

## Output

    Tag[<tag>] Size[<ln>] Flags[<flags>] CRC32[<hex>]
    0 <re> <im>
    1 <re> <im>
    ...

(`%.15g`).  On a checksum mismatch it prints `Data corrupted!` and exits with status 1.

## Examples

```bash
dump-corrs corr/ens.200.bin A4P5
```

For a file written with `jks.corrIO.writer` containing `A4P5 = 0.1*exp(-0.4 t)`,
t = 0..5, this prints

    Tag[A4P5] Size[6] Flags[] CRC32[ED4614F8]
    0 0.1 0
    1 0.0670320046035639 0
    2 0.0449328964117222 0
    3 0.0301194211912202 0
    4 0.0201896517994655 0
    5 0.0135335283236613 0

## Notes

- Flagged records crash: `reconstruct_min` builds its output with
  `[0.0 for l in 2*range(NT)]` (lines 47 and 51), which is a `TypeError` in Python 3.
  Only unflagged records (as written by `corrIO.writer`) can be dumped.
- No usage text: without an argument it fails with `IndexError`.

## See also

`list-corrs`, `jks_create_correlator_from_corrfile`.
