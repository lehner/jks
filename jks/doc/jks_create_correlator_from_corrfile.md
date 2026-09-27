# jks_create_correlator_from_corrfile

Creates a new jks database from binary corrIO files, one file per configuration, with the real and imaginary part of every correlator as separate tags.

## Synopsis

    jks_create_correlator_from_corrfile fn etag1 pat1 [etag2 pat2 ...]

## Description

For each pair `etag pat`, the files matching the glob `pat` are read with
`jks.corrIO.reader`.  `pat` contains one `*`; the text the `*` stands for in a file
name must be an integer, the configuration number.  Each file becomes the
configuration `<etag>-<number>` (number zero-padded to 8 digits, `%8.8d`), so `etag` is
the ensemble prefix.  Several pairs combine several ensembles (or streams) in one
database; configuration tags are sorted as strings.

For every correlator tag `T` in the files, two database tags are stored: `T.r` (real
parts) and `T.i` (imaginary parts), each a jackknife of the per-configuration arrays
(`measurements(...).jackknife().prepare(lambda mi: mi.mean())`).  Correlator tags that
are missing in any file are skipped.

### corrIO file format

A file is a sequence of records (native byte order, as written by
`jks.corrIO.writer`):

| field | type |
|---|---|
| tag length `n` (including the terminating NUL) | int32 |
| tag | `n` bytes UTF-8, NUL-terminated |
| CRC32 of the data bytes | uint32 |
| number of elements `ln` | uint32 |
| data | `ln` complex numbers as 2 x `ln` float64 (re, im, re, im, ...) |

The reader checks the CRC32 (`Data corrupted!` otherwise).  If a tag occurs twice in a
file, the last record wins.

## Arguments

| argument | meaning |
|---|---|
| `fn` | output database; created, an existing file is overwritten |
| `etagK` | ensemble prefix of the configuration tags of the K-th pattern |
| `patK` | glob with exactly one `*` standing for the configuration number (quote it) |

## Output

Prints `Loading <file>` / `Done` per file.  Writes `fn` with tags `<T>.r` and `<T>.i`
and configurations `<etag>-%08d`.  If no file matches any pattern, prints
`Attention: no file loaded for [...]` and exits with status 1 without writing.

## Examples

```bash
python3 -c '
import jks, math
for c in [200, 210, 220, 230]:
    w = jks.corrIO.writer("corr/ens.%d.bin" % c)
    w.write("P5P5", [complex(math.exp(-0.4*t), 0.01*t) for t in range(6)])
    w.write("A4P5", [complex(0.1*math.exp(-0.4*t), 0.0) for t in range(6)])
    w.close()'
jks_create_correlator_from_corrfile corr.jks ensX "corr/ens.*.bin"
jks_info corr.jks
```

`corr.jks` has 4 configurations `ensX-00000200` ... `ensX-00000230` and the tags
`A4P5.r`, `A4P5.i`, `P5P5.r`, `P5P5.i` (6 elements each; the synthetic data are the
same on every configuration, so the errors are zero).

## Notes

- The part of the file name at the `*` is cut out by position: everything from the
  `*` position up to the length of the text after `*` in the pattern.  The pattern
  must therefore have no other wildcards, and the prefix before `*` must match the
  file name literally; a non-integer there raises `ValueError`, and two files with
  the same number fail an assertion.
- The database is always created from scratch; use `jks_merge` to add the tags to an
  existing database.
- The in-code helper `mm` is unused.

## See also

`jks_create_correlator_from_corrfile_novar`, `list-corrs`, `dump-corrs`,
`jks_create_correlator_from_textfile`, `jks_info`, `jks_merge`.
