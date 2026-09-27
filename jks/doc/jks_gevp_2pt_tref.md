# jks_gevp_2pt_tref

Like `jks_gevp_2pt`, but the correlator matrix is first rotated with the GEVP eigenvectors of a fixed reference time `tref` before the per-time-slice GEVP is solved.

## Synopsis

    jks_gevp_2pt_tref out in ops fmtC fmtO dt tref [jkscale [lenient]]

## Description

The correlator matrix is read exactly as in `jks_gevp_2pt` (`fmtC % (o_i,o_j)`, its
transpose, or `.r`/`.i` pairs).  In each block the eigenvectors `V` of
`C(tref+dt)^-1 C(tref)` define the rotated matrix `Crot(t) = V^† C(t) V`.  For every
`t` of the loop (`t = 0..T-dt-1` for `dt > 0`, `t = -dt..T-1` otherwise) with
`t0 = t+dt`, the GEVP of `Crot(t0)^-1 Crot(t)` is solved; the eigenvectors are
mapped back with `u_n = V w_n`, and energies, overlaps `c2` (computed with the
unrotated `C(t)`) and eigenvector components are formed as in `jks_gevp_2pt`, with
the same nan rules.  Blocks, variations, `jkscale`, `lenient` and
`STATS_KEEP_FIXED` behave as in `jks_gevp_2pt`.  The output file is written from
scratch; if `out` exists and is the same file as `in`, the script prints `ERROR: the
output database is written from scratch and must not be the input <in>` and exits
with status 1.

## Arguments

| argument | meaning |
|---|---|
| `out` | output database (created/overwritten); must not be `in` |
| `in` | input database |
| `ops` | comma-separated operator names |
| `fmtC` | format with two `%s` for the correlator tags |
| `fmtO` | format with one `%s` for the output tags |
| `dt` | `t0 - t` |
| `tref` | reference time; uses `C(tref)` and `C(tref+dt)` |
| `jkscale` | optional float, default 1 |
| `lenient` | optional; any 9th argument enables lenient eigenvalue signs |

## Output

Same tags and layout as `jks_gevp_2pt`: `fmtO % "En-n"`, `fmtO % "c2mn-m-n"`
(operator m, state n), `fmtO % "cni-n-i.r"` / `".i"` (component i of `u_n`), vectors
over the `t` loop.

## Environment

| variable | effect |
|---|---|
| `STATS_KEEP_FIXED` | comma-separated fnmatch patterns of input tags kept at their central value in all blocks |

## Examples

```bash
jks_gevp_2pt_tref gevpt.jks corr.jks a,b "C_%s_%s" "gevp.%s" 1 2
```

On the synthetic 2-state database of the `jks_gevp_2pt` example the energies and
overlaps agree with `jks_gevp_2pt` (same 14 tags of length 15); the eigenvector
components differ slightly away from `t = tref = 2`.

## Notes

- `tref+dt` must be a valid time slice; the reference GEVP is not protected by the
  nan / positivity checks applied per `t`.
- `V` comes from a non-Hermitian eigenproblem and is not orthonormalized, so
  `u_n = V w_n` has unit norm only at `t = tref` (in the example the norm deviates
  from 1 by up to ~5e-4 at other `t`), whereas `jks_gevp_2pt` stores unit vectors.
- The usage text omits the optional `jkscale` and `lenient` arguments.

## See also

jks_gevp_2pt, jks_gevp_2pt_basis_change
