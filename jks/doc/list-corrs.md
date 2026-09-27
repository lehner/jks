# list-corrs

Lists the record headers (tag, size, flags, checksum) of a binary correlator file.

## Synopsis

    list-corrs file

## Description

Reads the records of `file` one after another and prints one line per record without
reading the data.  The header is parsed as: int32 tag length (with NUL), the tag,
uint32 CRC32, uint16 size `ln`, uint16 flags (`struct` format `IHH`).  The flags
describe a compressed storage of the data (`0x01` empty, `0x02` real only, `0x04`
imaginary only, `0x08` symmetric, `0x10` antisymmetric); the data length skipped is
`16*ln` bytes, halved for real/imag-only, `ln//2+1` elements for (anti)symmetric, 0 for
empty.

Files written by `jks.corrIO.writer` store a uint32 size and no flags; on a
little-endian machine this reads as size = `ln`, flags = 0 as long as `ln < 65536`.

## Arguments

| argument | meaning |
|---|---|
| `file` | correlator file (corrIO format or the flagged variant) |

## Output

    Tag[<tag>] Size[<ln>] Flags[<flag names>] CRC32[<hex>]

per record, on stdout.

## Examples

```bash
list-corrs corr/ens.200.bin
```

For a file written with `jks.corrIO.writer` (tags `P5P5`, `A4P5` with 6 elements,
`extra` with 1) this prints (CRC values depend on the data)

    Tag[P5P5] Size[6] Flags[] CRC32[12084A5A]
    Tag[A4P5] Size[6] Flags[] CRC32[ED4614F8]
    Tag[extra] Size[1] Flags[] CRC32[D7FC8CF]

## Notes

- No usage text: without an argument it fails with `IndexError`.
- CRC32 is printed but not checked.
- Files from `corrIO.writer` with 65536 or more elements per tag are misparsed
  (size is only 16 bit in this reader).

## See also

`dump-corrs`, `jks_create_correlator_from_corrfile`.
