# jks_create_correlator_from_corrfile_novar

Variant of `jks_create_correlator_from_corrfile` that numbers the configurations by their position in the file list instead of taking the number from the file name.

## Synopsis

    jks_create_correlator_from_corrfile_novar fn etag1 pat1 [etag2 pat2 ...]

## Description

Reads the files matching each glob `patK` with `corrIO.reader` (file format as in
`jks_create_correlator_from_corrfile`) and stores, for every correlator tag `T` present
in all files, the tags `T.r` and `T.i` in a new database `fn`.

The difference to `jks_create_correlator_from_corrfile` is the configuration tag.
The file name is not parsed: the pattern need not contain a `*` or a number.  The
files matching `patK` are sorted by name, and with `n` matching files the k-th file
(k = 0..n-1) gets the tag `<etagK>-%08d` of `n + k`, i.e. the configuration numbers
are `n` ... `2n-1` per pattern in sorted file order.  Every file is read once and
the statistics equal those of `jks_create_correlator_from_corrfile` on the same
files.

## Arguments

| argument | meaning |
|---|---|
| `fn` | output database; created, an existing file is overwritten |
| `etagK` | ensemble prefix of the configuration tags |
| `patK` | glob of the files of this ensemble (quote it) |

## Output

`Loading <file>` / `Done` per file.  Writes `fn`.  With no matching
file: `Attention: no file loaded for [...]`, exit status 1.

## Examples

```bash
# corr/ens.200.bin ... corr/ens.230.bin written with jks.corrIO.writer
# (see jks_create_correlator_from_corrfile)
jks_create_correlator_from_corrfile_novar novar.jks ensX "corr/ens.*.bin"
jks_info novar.jks
```

Four configurations `ensX-00000004` ... `ensX-00000007` (files 200, 210, 220, 230 in
this order) and the tags `A4P5.r`, `A4P5.i`, `P5P5.r`, `P5P5.i`, with the same means,
errors and blocks as the database from `jks_create_correlator_from_corrfile`, whose
configurations are `ensX-00000200` ... `ensX-00000230`.

## Notes

- The numbering starts at `n`, not 0, and depends only on the sorted file names of
  each pattern, so adding or removing a file renumbers all configurations of that
  pattern.  Use it only when the file names carry no usable configuration number.
- The usage text is identical to the non-`novar` script.

## See also

`jks_create_correlator_from_corrfile`, `list-corrs`, `dump-corrs`, `jks_info`.
