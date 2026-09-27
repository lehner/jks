# jks_create_correlator_from_corrfile_novar

Variant of `jks_create_correlator_from_corrfile` that numbers the configurations by their position in the file list instead of taking the number from the file name.

## Synopsis

    jks_create_correlator_from_corrfile_novar fn etag1 pat1 [etag2 pat2 ...]

## Description

Reads the files matching each glob `patK` with `corrIO.reader` (file format as in
`jks_create_correlator_from_corrfile`) and stores, for every correlator tag `T` present
in all files, the tags `T.r` and `T.i` in a new database `fn`.

The difference to `jks_create_correlator_from_corrfile` is the configuration tag.
The file name is not parsed: the pattern need not contain a `*` or a number.  The list
`glob.glob(patK)` is duplicated (`* 2`) and file `f` gets the tag
`<etagK>-%08d` of its index in the doubled list; the second copy overwrites the first,
so with `n` matching files the configuration numbers are `n` ... `2n-1` (per
pattern), in the (unsorted, filesystem dependent) order returned by
`glob`.  The measurement dictionary is keyed by these tags, so each file enters once
and the statistics equal those of `jks_create_correlator_from_corrfile` on the same
files; every file is, however, read twice.

## Arguments

| argument | meaning |
|---|---|
| `fn` | output database; created, an existing file is overwritten |
| `etagK` | ensemble prefix of the configuration tags |
| `patK` | glob of the files of this ensemble (quote it) |

## Output

`Loading <file>` / `Done` per read (twice per file).  Writes `fn`.  With no matching
file: `Attention: no file loaded for [...]`, exit status 1.

## Environment

The script does `import corrIO` (top-level module), not `jks.corrIO`.  With only the
source tree on `PYTHONPATH` it fails with `ModuleNotFoundError: No module named
'corrIO'`; add the directory of the `jks` package itself:

    export PYTHONPATH=$PYTHONPATH:~/jks_system_src/jks_system-1.1.0/jks

## Examples

```bash
# corr/ens.200.bin ... corr/ens.230.bin written with jks.corrIO.writer
# (see jks_create_correlator_from_corrfile)
PYTHONPATH=$PYTHONPATH:~/jks_system_src/jks_system-1.1.0/jks \
    jks_create_correlator_from_corrfile_novar novar.jks ensX "corr/ens.*.bin"
jks_info novar.jks
```

Four configurations `ensX-00000004` ... `ensX-00000007` (glob order here was
230, 220, 210, 200) and the tags `A4P5.r`, `A4P5.i`, `P5P5.r`, `P5P5.i`, with the same
means and errors (up to rounding in the last digit) as the database from `jks_create_correlator_from_corrfile`.

## Notes

- `import corrIO` (line 20) breaks the script when only `jks` is importable; see
  Environment.
- The doubled list (`glob.glob(pat[ll]) * 2`, line 76) and the trivially unique
  `tags` check look like leftovers; the numbering starts at `n`, not 0, and depends on
  `glob` order, so configuration tags from different runs or file systems need not
  agree.  Use it only when the file names carry no usable configuration number.
- The usage text is identical to the non-`novar` script.

## See also

`jks_create_correlator_from_corrfile`, `list-corrs`, `dump-corrs`, `jks_info`.
