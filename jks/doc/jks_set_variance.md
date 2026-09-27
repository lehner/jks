# jks_set_variance

Rescales single elements of tags so that their total error is a given fraction of the value.

## Synopsis

    jks_set_variance database.jks tag1 idx1 rel_err1 [tag2 idx2 rel_err2 ...]

## Description

For each triple, the total variance `tcov()[idx][idx]` (statistical plus all
variations) of element `idx` of `tag` is computed and all blocks of that element,
variations included, are scaled about the central value by
`sqrt((mean[idx] * rel_err)^2 / tcov)`. Afterwards `sqrt(tcov()[idx][idx]) /
|mean[idx]| = rel_err`. Other elements are untouched. The tag is modified in place
and the database saved (not compressed).

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database, updated in place |
| `tagN` | existing tag |
| `idxN` | element index (int) |
| `rel_errN` | target relative total error |

## Output

Modified tags; nothing is printed.

## Examples

```bash
jks_set_variance fake.jks C 1 0.05
```

Sets the error of `C[1]` to 5% in the `cov()` convention; `jks_info` shows
0.04274 = 0.05 * 0.86570 * sqrt(39/40) because it uses the bias-free convention.

## Notes

- The target is defined with `tcov()` (the `cov()` convention), so `jks_info`
  reports a relative error smaller by `sqrt((N-1)/N)`.
- Stat and variation parts are scaled by the same factor; their ratio is kept.
- An element with zero variance (e.g. of a constant grid tag) becomes NaN in every
  block (division by zero, only a `RuntimeWarning`), and is stored.
- All blocks of the element are scaled by one factor, so its covariances with other
  elements and tags scale while the correlations are unchanged.

## See also

`jks_rescale_variance`, `jks_info`
