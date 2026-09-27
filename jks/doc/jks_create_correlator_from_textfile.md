# jks_create_correlator_from_textfile

Creates a new jks database with one tag from text files, one file per configuration, of the form `t value`.

## Synopsis

    jks_create_correlator_from_textfile fn etag ctag pat

## Description

Every file matching the glob `pat` is one configuration.  `pat` contains one `*`; the
text at the `*` becomes the configuration number, and the configuration tag is
`<etag>-%08d` (e.g. `ensA-00000100`).  If that text starts with `[`, it is used
verbatim instead (`ensC-[a1]`).  The values of all files are combined into the
jackknife tag `ctag` (`measurements(...).jackknife().prepare(lambda mi: mi.mean())`),
and the database is written to `fn`.

### Text file format

- Empty lines and lines starting with `T` are skipped (e.g. a header `T ...`).
- Every other line is `i value [more columns]`, fields separated by one or more
  spaces (not tabs); the first remaining line must have at least two fields.
- `i` must equal the line number counted from 0 over the remaining lines
  (assertion), `value` is read as float, further columns are ignored.
- All files should have the same number of lines.

## Arguments

| argument | meaning |
|---|---|
| `fn` | output database; created, an existing file is overwritten |
| `etag` | ensemble prefix of the configuration tags |
| `ctag` | name of the tag to create |
| `pat` | glob with one `*` at the configuration number (quote it) |

## Output

Writes `fn` with the single tag `ctag`; prints nothing.

## Examples

```bash
mkdir -p ensA
for c in 100 110 120 130 140; do
  awk -v c=$c 'BEGIN{print "T pion, config " c; for(t=0;t<8;t++) printf "%d %.8g\n", t, exp(-0.5*t)*(1+0.001*(c%7)*t)}' > ensA/pion.$c.dat
done
jks_create_correlator_from_textfile pion.jks ensA pion "ensA/pion.*.dat"
jks_info pion.jks pion
```

`pion.jks` holds the tag `pion` (8 elements) on the 5 configurations
`ensA-00000100` ... `ensA-00000140`.

## Notes

- The configuration text is cut out by position (from the `*` to the length of the
  pattern's suffix), so `pat` must not contain other wildcards; non-integer text
  (other than `[...]`) raises `ValueError`, duplicate numbers fail an assertion.
- Lines starting with `#` are not skipped and raise `ValueError`.
- If no file matches, the script still writes `fn`, with `ctag` having no
  configurations and a `nan` mean.
- The database is created from scratch; use `jks_merge` to combine with an existing
  one.

## See also

`jks_create_correlator_from_multi_textfile`, `jks_create_correlator_from_corrfile`,
`jks_info`, `jks_merge`.
