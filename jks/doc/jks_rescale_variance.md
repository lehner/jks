# jks_rescale_variance

Multiplies the variance of tags by given factors, in place.

## Synopsis

    jks_rescale_variance database.jks tag1 scale1 [tag2 scale2 ...]

## Description

For each tag, every block (configurations and `!` variations) is replaced by
`orig + (block - orig) * sqrt(scale)`, so statistical and systematic covariances
are both multiplied by `scale` while the central value is kept. `scale` is either
one number for all elements or a `;`-separated list with one factor per element.
The tag is modified in place and the database saved (not compressed).

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database, updated in place |
| `tagN` | existing tag to rescale |
| `scaleN` | variance factor `s`, or `s0;s1;...` with one factor per element |

## Output

Rescaled tags; nothing is printed.

## Examples

```bash
jks_rescale_variance fake.jks C 4
jks_rescale_variance fake.jks C.plsa.1to4 '2;1;1;1;1;1;1;1;1;1;1;1;1;1;1'
```

The first doubles every stat error of `C` (element 0: 0.01615 -> 0.03230); the
second multiplies stat and `band` errors of element 0 of `C.plsa.1to4` by sqrt(2).

## Notes

- Errors scale with `sqrt(scale)`; the factor is a variance factor.
- Variation shifts are scaled too, not only the statistical blocks.
- A per-element list of the wrong length fails with a bare `AssertionError`.
- Covariances with other tags scale by `sqrt(scale)`; tags derived earlier from the
  rescaled tag are not updated.

## See also

`jks_set_variance`, `jks_add_sys`
