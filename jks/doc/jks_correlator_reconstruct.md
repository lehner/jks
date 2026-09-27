# jks_correlator_reconstruct

Builds correlators `sum_{i<N} c2[i] exp(-t E[i])` from tags of energies and amplitudes, one output tag per number of states N.

## Synopsis

    jks_correlator_reconstruct inout otag etag c2tag Tmax

## Description

For `N = 1 .. len(etag)` the tag `otag.recN` is computed as
`C_N(t) = sum_{i=0}^{N-1} c2tag[i] * exp(-t * etag[i])` for `t = 0 .. Tmax-1`, with
`res.apply` (central value, every block and every variation), so the errors and
correlations of energies and amplitudes are propagated.  Pure exponentials are used
(no backward-propagating term).  The database is updated in place.

## Arguments

| argument | meaning |
|---|---|
| `inout` | database; read and rewritten in place |
| `otag` | prefix of the output tags |
| `etag` | tag with the energies `E[i]` |
| `c2tag` | tag with the amplitudes `c2[i]` (at least as long as `etag`) |
| `Tmax` | number of time slices of the output |

## Output

`otag.rec1`, ..., `otag.rec<len(etag)>`, each of length `Tmax`.

## Examples

```bash
jks_fit data.jks C "range(4,25)" "p[0]*math.exp(-p[1]*x)+p[2]*math.exp(-p[3]*x)" "[0.009,0.41,0.01,1.0]" fit2
jks_add data.jks E "[r['fit2'][3],r['fit2'][1]]" A "[r['fit2'][2],r['fit2'][0]]"
jks_correlator_reconstruct data.jks C E A 30
```

A two-exponential fit (the fitter put the excited state into `p[0], p[1]`, hence the
reordering) gives `C.rec1` (ground state only) and `C.rec2` (both states), 30 time
slices each; at t=12 both are close to `C` (6.9e-5 vs 6.8e-5), at t=5 only `C.rec2`
(2.005e-3 vs 1.996e-3; `C.rec1` 1.35e-3), below the fit range (t=2) neither.

## Notes

- Existing `otag.recN` tags make `res.add` fail (`AssertionError`).
- Extra arguments after `Tmax` are ignored (the usage check is `len(argv) < 6`).

## See also

jks_fit, jks_add, jks_gevp_2pt
