# jks_gevp_2pt_basis_change

Rotates a correlator matrix into the basis of GEVP eigenvectors taken at a fixed time slice, `C_nm(t) = u_n^† C(t) u_m`, optionally also with one side left in the original operator basis.

## Synopsis

    jks_gevp_2pt_basis_change inout corrsin ops keepstates tstar fmtCI fmtCO fmtc frozenCoef [opsLeft opsRight]

## Description

`inout` holds the eigenvector tags written by `jks_gevp_2pt` / `jks_gevp_2pt_tref`
(`fmtc % "cni-n-i.r"` and `".i"`), `corrsin` the correlator matrix, read as in
`jks_gevp_2pt` from `fmtCI % (o_i,o_j)`, its transpose, or `.r`/`.i` pairs.  Both
databases are merged in memory (`jks2.take`), so they must not share tag names.

The vectors `u_n` are the elements `tstar` of the `cni-n-i` tags.  For
`n, m = 0 .. Nkeep-1` (`Nkeep` = number of entries of `keepstates`) the script
computes, for all T time slices of `C_00`,

- `C_nm(t) = sum_ij conj(u_n^i) C_ij(t) u_m^j`
- for each `op` in `opsLeft`: `C_{op,n}(t) = sum_j C_{op,o_j}(t) u_n^j`
- for each `op` in `opsRight`: `C_{n,op}(t) = sum_i conj(u_n^i) C_{o_i,op}(t)`

with `res.apply` over the central value, every block and every variation (so the
fluctuation of `u_n` is included).  If `frozenCoef` evaluates to true, the
`cni-n-*` tags of state `n` are kept at their central value in all blocks.  The new
tags are added to `inout` (in place).

## Arguments

| argument | meaning |
|---|---|
| `inout` | database with the GEVP eigenvector tags; output tags are added to it |
| `corrsin` | database with the correlator matrix (read only) |
| `ops` | comma-separated operator names, in the order used for the GEVP |
| `keepstates` | comma-separated list; only its length `Nkeep` is used, states `0..Nkeep-1` are rotated |
| `tstar` | index into the `cni` vectors (the GEVP `t` loop index, not necessarily the time slice) |
| `fmtCI` | format with two `%s` for the input correlator tags |
| `fmtCO` | format with two `%s` for the output tags |
| `fmtc` | format with one `%s` for the eigenvector tags (the `fmtO` of the GEVP run) |
| `frozenCoef` | python expression (`True`/`False`); freeze the coefficients of state n |
| `opsLeft` | optional comma-separated operators for `C_{op,n}` (empty entries ignored) |
| `opsRight` | optional comma-separated operators for `C_{n,op}` (both or neither must be given) |

## Output

- `fmtCO % ("n","m") + ".r"` and `+ ".i"`: real and imaginary part of `C_nm(t)`,
  length T
- `fmtCO % (op,"n") + ".r"/".i"` for `op` in `opsLeft`
- `fmtCO % ("n",op) + ".r"/".i"` for `op` in `opsRight`

## Examples

```bash
jks_gevp_2pt gevp.jks corr.jks a,b "C_%s_%s" "gevp.%s" 1
jks_gevp_2pt_basis_change gevp.jks corr.jks a,b 0,1 3 "C_%s_%s" "Crot_%s_%s" "gevp.%s" False
```

On the synthetic 2-state database of the `jks_gevp_2pt` example this adds
`Crot_0_0.r/.i`, `Crot_0_1.r/.i`, `Crot_1_0.r/.i`, `Crot_1_1.r/.i` (length 16) to
`gevp.jks`; `Crot_0_1.r` vanishes (1e-16) at t = 3, 4 and is small elsewhere, the
diagonal ones decay like the two states.

## Notes

- The script runs under python 3, but `opsLeft`/`opsRight` are python-3 `filter`
  objects (lines 38-39) that are exhausted after the first state: only `n = 0` gets
  the left/right tags.  `... True a b` wrote `Crot_a_0` and `Crot_0_b` but no
  `Crot_a_1` or `Crot_1_b`.  Do not rely on the optional arguments until this is
  fixed.
- With `frozenCoef` true only the coefficients of state `n` are kept fixed (line
  144); in `C_nm` with `m != n` the vector `u_m` still fluctuates.
- `keepstates` values are ignored; `1,2` rotates states 0 and 1.
- For a GEVP run with `dt <= 0` the `cni` element `tstar` belongs to time slice
  `tstar - dt`.
- The usage text is printed unless there are exactly 9 or 11 arguments.

## See also

jks_gevp_2pt, jks_gevp_2pt_tref
