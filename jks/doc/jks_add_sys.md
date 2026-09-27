# jks_add_sys

Attaches systematic variations to a tag, taking each shifted value from another tag.

## Synopsis

    jks_add_sys database.jks ctag alt1_tag var1 [alt2_tag var2 ...]

## Description

For each pair, the variation block `!varN` of `ctag` is set to the central value
(mean) of `altN_tag`, so the systematic shift is `mean(altN_tag) - mean(ctag)`,
fully correlated across the elements of `ctag`. Statistical blocks of `ctag` are
unchanged. `ctag` is then removed and re-added to the database, which is saved in
place (not compressed). Other tags carry the new variation with zero shift.

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database, updated in place |
| `ctag` | tag that receives the variations |
| `altN_tag` | tag holding the alternative (shifted) evaluation, same shape as `ctag` |
| `varN` | variation name (stored as `!varN`) |

## Output

Variations `varN` on `ctag`, described as `Systematic error from <argv list>`.

## Examples

```bash
jks_add data.jks C.alt '1.01*r["C"]'
jks_add_sys data.jks C C.alt norm
```

`C` gets variation `norm` equal to 1% of its value, e.g. element 1:
`0.22591170421666 +- 1.38e-05(stat) +- 0.00225911704216661(norm)`.

## Notes

- The usage text calls the second argument `shift1_tag`, but its *mean* is used as
  the shifted value itself, not as a shift to add.
- If `varN` already exists (e.g. `band`), the block of `ctag` for that variation is
  overwritten.
- `ctag` moves to the end of the tag order. Tags derived from `ctag` earlier (e.g.
  with `jks_add`) do not get the variation; recompute them.
- Wrong argument count prints the usage and exits 0.

## See also

`jks_add`, `jks_add_parameter`, `jks_rescale_variance`, `jks_cor`
