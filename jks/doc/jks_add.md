# jks_add

Adds new tags computed from Python expressions over the existing tags of a database.

## Synopsis

    jks_add database.jks tag1 expr1 [tag2 expr2 ...]

## Description

Each expression is compiled as `lambda r: <expr>` and evaluated with
`res.apply`: once on the central values and once on every block (configurations
and `!` variations), with `r` a dict mapping tag name to that block's numpy array.
The results form a new jackknife tag, so statistical blocks and systematic
variations of all tags used are propagated consistently. Pairs are processed in
order and each new tag is added before the next expression is evaluated, so a
later expression can use a tag defined earlier in the same call. The database is
modified in place and saved once at the end (not compressed).

## Arguments

| argument | meaning |
|---|---|
| `database.jks` | database to read and update in place |
| `tagN` | name of the new tag; must not exist |
| `exprN` | Python expression in `r` returning an array-like value |

## Output

One new tag per pair, with the same block layout (configs and variations) as the
database. Prints `Adding i/N: tag = expr` for each pair.

## Examples

```bash
jks_add fake.jks C.meff 'emp_log(r["C"])' C.2x '2*r["C"]' w2 'np.exp(-2*r["omega0"])'
```

Adds `C.meff` (log effective mass, 14 elements), `C.2x` (twice `C`) and `w2`, a
constant weight array `exp(-2 omega)` on the grid `omega0` (zero error).

## Notes

- An existing tag name fails with a bare `AssertionError` (`resamples.add`); since
  saving happens only at the end, nothing is written in that case, including the
  pairs before the failing one.
- Expression namespace (module globals of the script): `r`, `np`, `math`, `jks`,
  `sys`, `os`, `glob`, `res` (the open database), and the helpers
  `fold(c)` (`(c[i]+c[-i])/2`, `i=0..T/2`), `afold(c)` (antisymmetric fold),
  `unfold(c)`, `foldsum(a)` (`a[0]` plus `a[t]+a[T-t]`), `partial_sum(c)`,
  `rpartial_sum(c)` (sum of elements after `i`), `cshift(a,i)` (cyclic shift),
  `shift(a,i)` (shift filling with NaN), `time_reverse(C)`, `apb(C,t0)` (negate the
  last `t0` elements), `emp_log(c, ndisp=1)` (`log(c[i]/c[i+ndisp])/ndisp`, NaN if
  the ratio is <= 0), `emp_cosh(c)` (`acosh((c[i]+c[i+2])/(2 c[i+1]))`, NaN if <= 1),
  `interpolate(y, y_val, x, order)` (x where `y` first crosses `y_val`, order 1 or 2,
  1-element array, NaN if no crossing), `first_available(r, *keys)`, `DT(t,T)`.
  The usage text lists only some of these.
- `fit(r, lfits, guess)` (uncorrelated) and `cfit(r, lfits, guess)` (correlated)
  fit `lfits = [(tag, times, lambda t, p: ...), ...]` jointly and return the
  parameters followed by chi^2, dof and p (NaN for `fit`), e.g.
  `fit(r, [('C', range(10,20), lambda t,p: p[0]*np.exp(-p[1]*t))], [0.01, 0.4])`.
  They print every fit; a failed fit gives NaN.
- Non-finite results (e.g. `emp_log` of a negative ratio) are stored silently.
- A scalar result (e.g. `np.pi`) is stored as a 0-d array, which `jks_info db tag`
  cannot print; wrap scalars in a list (`[2.0]`).
- The expression is passed to `eval`; quote it for the shell.

## See also

`jks_add_parameter`, `jks_add_sys`, `jks_rm`, `jks_info`, `jks_values`
