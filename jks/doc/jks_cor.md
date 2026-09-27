# jks_cor

Prints the statistical, systematic and total correlation between two elements of a database.

## Synopsis

    jks_cor database.jks tag1 t1 tag2 t2

## Description

Builds the joint 2-vector (tag1[t1], tag2[t2]) with `res.apply`, so that stat
blocks and variations are aligned, and prints both values with their stat
errors, the stat correlation from the jackknife blocks (`cov()`), the shift
d_v = block_v - mean of each `!` variation that moves at least one of the two
values, the combined systematic correlation
sum_v d1 d2 / sqrt(sum_v d1^2 sum_v d2^2), and the total correlation from
`tcov()` (stat + sum_v d_v d_v^T, as used downstream). A single variation is
fully correlated (correlation = sign(d1 d2)), so its shifts are printed instead
of a correlation. Read only.

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database (not modified) |
| `tag1`, `tag2` | tags; must exist |
| `t1`, `t2` | element indices (int; scalar tags use 0; Python negative indices work) |

## Output

- `tag[t] = value +- err (stat)` for both (err in the `cov()` convention, i.e.
  larger by sqrt(N/(N-1)) than the bias-free error of `jks_info`; C[1] of
  `fake.jks`: 1.631e-02 here, 0.01611 in `jks_info`).
- `stat correlation`.
- If any variation shifts either value: a table `variation`, `shift tag1[t1]`,
  `shift tag2[t2]`, `sign` (+1, -1, or `-` if one shift is 0), then
  `sys correlation` (or `undefined (... has no systematic shift)`) and
  `total correlation`. Without shifting variations only the stat correlation is
  printed.

## Examples

```bash
jks_plsa data.jks C "[1,2,3,4]" "[0,1,4,8]" omega0 C.plsa
jks_cor data.jks C.plsa 2 C.plsa 3
jks_cor data.jks C 1 C.plsa 1
```

On `fake.jks`: outputs t=4 and t=8 of the band have stat correlation 0.9107,
`band` shifts 8.042e-03 and 2.972e-03 (sys correlation 1), total 0.9335; the
input C[1] and the band output at t=1 have stat correlation 0.9939 and no
variation.

## Notes

- A zero stat variance gives `nan` for the stat correlation.
- All `jks_plsa`/`jks_blsa` outputs share the variation `band`, so their `band`
  shifts always appear fully correlated (sign +1 or -1) with each other.
- Out-of-range indices raise `IndexError`; a missing tag fails with an
  `AssertionError` naming it.

## See also

`jks_info`, `jks_plsa`, `jks_blsa`, `jks_add_sys`
