# jks_gevp_2pt

Solves the generalized eigenvalue problem of a matrix of two-point correlators time slice by time slice and writes energies, overlaps and eigenvectors to a new database.

## Synopsis

    jks_gevp_2pt out in ops fmtC fmtO dt [jkscale [lenient]]

## Description

For operators `ops = o_0,...,o_{N-1}` the matrix `C_ij(t)` is read from tag
`fmtC % (o_i,o_j)`; if absent, `fmtC % (o_j,o_i)` is used (symmetric), and if
neither exists as a real tag the complex pair `<tag>.r`/`<tag>.i` is used
(`fmtC % (o_j,o_i)` then conjugated).  The number of time slices T is the length of
`C_00`.

For each `t` (`t = 0..T-dt-1` if `dt > 0`, `t = -dt..T-1` if `dt <= 0`) with
`t0 = t+dt`, the eigenvalues `lambda_n` and eigenvectors `u_n` of
`C(t0)^-1 C(t)` are computed (`numpy.linalg.eig`, eigenvectors of unit norm) and

- `E_n = -log(lambda_n)/(t-t0)`, sorted ascending,
- `c2[op m][state n] = |(C(t) u_n)_m|^2 / |u_n^† C(t) u_n| * exp(E_n t)`
  (estimate of `|<0|O_m|n>|^2`),
- `u_n` components (real and imaginary parts).

If any `lambda_n` has `|Im| >= 1e-10` or `Re <= 0`, all entries at that `t` are nan;
if the smallest `E_n <= 0`, the energies are kept but overlaps and eigenvectors are
nan.  A nan norm of `C(t)` or `C(t0)` also gives nan.  The computation is done with
`res.apply` on the central value, every jackknife block and every variation.

With `jkscale` the blocks are moved towards the mean by that factor before the
GEVP and the result is scaled back (`res.apply(..., scale=jkscale)`), a linearization
for noisy blocks.  The output file is written from scratch (input tags are not
copied); if `out` exists and is the same file as `in` (`os.path.samefile`), the
script prints `ERROR: the output database is written from scratch and must not be
the input <in>` and exits with status 1.

## Arguments

| argument | meaning |
|---|---|
| `out` | output database (created/overwritten, contains only the GEVP tags); must not be `in` |
| `in` | input database with the correlator matrix |
| `ops` | comma-separated operator names |
| `fmtC` | format with two `%s` for the correlator tags, e.g. `C_%s_%s` |
| `fmtO` | format with one `%s` for the output tags, e.g. `gevp.%s` |
| `dt` | `t0 - t`; positive: reference time after `t` |
| `jkscale` | optional float, default 1 |
| `lenient` | optional; any 8th argument enables it: eigenvalues are replaced by their real part and non-positive ones are accepted (the log then gives nan) |

## Output

With `n` the state index (ascending energy) and `m`/`i` the operator index:

- `fmtO % "En-n"`: energy of state n
- `fmtO % "c2mn-m-n"`: `|<0|O_m|n>|^2` (first index operator, second state)
- `fmtO % "cni-n-i.r"`, `fmtO % "cni-n-i.i"`: real/imaginary part of component i of
  eigenvector `u_n`

Each is a vector over the `t` loop: element k belongs to `t = k` for `dt > 0` (T-dt
entries) and to `t = k - dt` for `dt <= 0` (T+dt entries).

## Environment

| variable | effect |
|---|---|
| `STATS_KEEP_FIXED` | comma-separated fnmatch patterns of input tags kept at their central value in all blocks (to isolate error contributions) |

## Examples

```bash
jks_gevp_2pt gevp.jks corr.jks a,b "C_%s_%s" "gevp.%s" 1
jks_gevp_2pt gevpm.jks corr.jks a,b "C_%s_%s" "gevp.%s" -2
STATS_KEEP_FIXED="C_b*" jks_gevp_2pt gevpk.jks corr.jks a,b "C_%s_%s" "gevp.%s" 1
jks_gevp_2pt corr.jks corr.jks a,b "C_%s_%s" "gevp.%s" 1
```

`corr.jks` is a synthetic 2-state database (E = 0.4, 0.8; `<n|O_i|0>` =
[[1,0.5],[0.6,-0.9]]; tags `C_a_a`, `C_a_b`, `C_b_b`, T=16; `C_b_a` is found by
symmetry).  `gevp.jks` gets 14 tags of length 15: `gevp.En-0` ~ 0.40,
`gevp.En-1` ~ 0.80, `gevp.c2mn-0-0` ~ 1.00, `gevp.c2mn-1-0` ~ 0.25,
`gevp.c2mn-0-1` ~ 0.36, `gevp.c2mn-1-1` ~ 0.81 and the `cni` tags; with `dt=-2` the
vectors have 14 entries starting at t=2; `STATS_KEEP_FIXED` keeps `C_b_b` fixed
(printed as `Translated: ['C_b_b']`) and reduces the errors.  The last call
refuses to overwrite the input (`ERROR: ...`, exit 1) and leaves `corr.jks`
unchanged.

## Notes

- An existing `out` is overwritten, not merged; use `jks_add_from` to combine the
  GEVP tags with other data.
- The overall phase/sign of `u_n` is whatever `numpy.linalg.eig` returns; states are
  identified only by ordering the energies.
- The `.i` parts are zero for real input.
- A singular `C(t0)` raises `LinAlgError` (only nan norms are caught).
- The usage text omits the optional `jkscale` and `lenient` arguments.

## See also

jks_gevp_2pt_tref, jks_gevp_2pt_basis_change, jks_fit
