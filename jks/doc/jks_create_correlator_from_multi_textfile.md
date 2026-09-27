# jks_create_correlator_from_multi_textfile

Creates a new jks database with one tag from text files of several ensembles or streams, each given by its own prefix and file pattern.

## Synopsis

    jks_create_correlator_from_multi_textfile fn ctag etag1 pat1 [etag2 pat2 ...]

## Description

For each pair `etagK patK`, the files matching the glob `patK` are read; the text at the
single `*` must be an integer and gives the configuration tag `<etagK>-%08d`.  All
files of all pairs are put into one measurement set, truncated to the shortest file
(`min_len` lines), and stored as the jackknife tag `ctag` in the new database `fn`.
The file format is the same as for `jks_create_correlator_from_textfile`: empty lines
and lines starting with `T` are skipped, the other lines are `i value [...]`
(space separated, `i` counting from 0), and only `value` is used.

## Arguments

| argument | meaning |
|---|---|
| `fn` | output database; created, an existing file is overwritten |
| `ctag` | name of the tag to create |
| `etagK` | configuration tag prefix for the K-th pattern |
| `patK` | glob with one `*` at the configuration number (quote it) |

## Output

Writes `fn` with the single tag `ctag`; prints nothing.

## Examples

```bash
mkdir -p ensB
for c in 8 16 24; do
  awk -v c=$c 'BEGIN{for(t=0;t<6;t++) printf "%d  %.8g 0\n", t, exp(-0.5*t)*(1-0.001*(c%5)*t)}' > ensB/pion.$c.dat
done
# ensA/pion.{100..140}.dat (8 lines each) as in jks_create_correlator_from_textfile
jks_create_correlator_from_multi_textfile multi.jks pion ensA "ensA/pion.*.dat" ensB "ensB/pion.*.dat"
jks_info multi.jks pion
```

`multi.jks` holds `pion` with 6 elements (the `ensB` files have 6 lines, so the
8-line `ensA` files are truncated) on 8 configurations `ensA-00000100` ...
`ensA-00000140`, `ensB-00000008`, `ensB-00000016`, `ensB-00000024`.

## Notes

- All configurations of all pairs form one sample: the mean is over all files and the
  jackknife removes one configuration at a time, whatever its prefix.  It does not
  build separate per-ensemble quantities.
- Unlike `jks_create_correlator_from_textfile`, `[...]` configuration names are not
  supported (the text must be an integer).
- As in the single-file variant, the configuration text is cut by position and `#`
  lines raise `ValueError`.
- A pattern without matches is silently ignored; if no pattern matches anything the
  script stops with `ValueError: min() iterable argument is empty`.

## See also

`jks_create_correlator_from_textfile`, `jks_create_correlator_from_corrfile`,
`jks_info`, `jks_merge`.
