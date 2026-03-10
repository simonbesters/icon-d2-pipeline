# ICON-D2 Pipeline — Fix Plan

Full code review + comparison against original NCL/Fortran RASP reference identified issues in two categories: (A) software engineering bugs/performance, and (B) meteorological correctness divergences from the NCL reference.

---

## Priority 1 — High Impact

### [x] B1. Fix `pfd_tot` formula to match NCL `pfd()`
**File:** `icon_d2_pipeline/calc/pfd.py` (`compute_pfd_tot`)
**Also:** `icon_d2_pipeline/config.py` (add constants)

NCL `pfd()` uses hardcoded polar coefficients and 1.15 m/s sink rate with **no** wing-loading adjustment. The Python incorrectly applies wing-loading correction and uses 0.9 m/s.

Fix: rewrite `compute_pfd_tot()` to use:
```
a = -0.000302016415111608
b = 0.0729181700942301
c = -5.21488508245734
SRIT = 1.15

wssel = wstar_cm / 100.0 - SRIT
sqrt_term = sqrt(max((c - wssel) / a, 0))
dist = (wssel * sqrt_term) / (2 * wssel - 2*c - b * sqrt_term) / divisor
```

Add `PFD_SIMPLE_A`, `PFD_SIMPLE_B`, `PFD_SIMPLE_C`, `PFD_SIMPLE_SRIT` to config.py.

Note: `pfd_tot2` and `pfd_tot3` are already correct (they match NCL `pfd2()`/`pfd3()`).

### [x] A1. Fix GeoTIFF resolution units mismatch
**File:** `icon_d2_pipeline/output/geotiff.py:78-87`

`gdal.Warp()` to EPSG:3857 passes `xRes`/`yRes` in degrees, but EPSG:3857 uses meters. This produces incorrect spatial resolution.

Fix: Remove `xRes` and `yRes` from the `gdal.Warp()` call — GDAL will auto-compute correct resolution from the source dataset.

### [x] A2. Reuse ProcessPoolExecutor across forecast hours
**File:** `icon_d2_pipeline/pipeline.py`

Currently creates a new process pool (with full pickling of weights to workers) for every forecast hour. Very expensive.

Fix:
- Create pool once at ~line 213, after remapper is built
- Pass `executor` into `_load_fields_for_hour()`
- `executor.shutdown()` after the timestep loop
- Skip if no remapper (`executor=None`)

---

## Priority 2 — Medium Impact

### [x] B4. Replace Espy LCL with profile-scanning `sfclcl`
**File:** `icon_d2_pipeline/calc/cloud.py:48-81` (`calc_sfclcl_height`)

Current Espy formula (`LCL_agl = 125 * (T - Td)`) is a rough approximation. NCL calls Fortran that scans the 3D profile.

Fix: lift a surface parcel dry-adiabatically, conserve mixing ratio, find height where T_parcel = Td_parcel. Fall back to Espy if no condensation found in profile.

### [x] B3. Improve `sfcsunpct` clear-sky model
**File:** `icon_d2_pipeline/calc/surface.py:16-80` (`calc_sfcsunpct`)

Current: `transmittance = 0.76 ** airmass` ignores atmospheric moisture.
NCL Fortran uses full 3D profile (z, pmb, tc, qvapor).

Fix: use Kasten (1980) formula accounting for precipitable water:
```
I_clear = I0 * cos(z) * exp(-0.09 * airmass * (1 + 0.012 * pw))
```
Compute PW by integrating qvapor column.

### [x] B6. Use actual BL temperature in `calc_wstar`
**File:** `icon_d2_pipeline/calc/thermal.py:12-36`
**Also:** `icon_d2_pipeline/pipeline.py` (pass T_blavg)

Currently uses constant `T_avg = 300K`. The Fortran receives the full 3D tc field.

Fix: add optional `t_avg` parameter to `calc_wstar()`. In pipeline.py, compute BL-averaged T from 3D field and pass it in.

### [x] A3. Use NaN instead of zeros for missing data
**File:** `icon_d2_pipeline/pipeline.py:283-420`

All `.get("param", np.zeros(...))` fallbacks write 0 as valid data. Should use `np.full((ny, nx), np.nan)` so missing data maps to -999999 in output files.

### [x] B5. Improve `blcloudpct` with RH-weighted cloud fraction
**File:** `icon_d2_pipeline/calc/cloud.py:129-174` (`calc_blcloudpct`)

Current: binary layer counting (has cloud water OR RH > 95%).
NCL Fortran: "subgrid" cloud scheme (statistical).

Fix: use standard NWP sub-grid approach:
```
cf_layer = max(0, (RH - RH_crit) / (1 - RH_crit))^2
```
where `RH_crit = 0.80`, then take BL-depth-weighted average.

---

## Priority 3 — Low Impact

### [x] A4. Flip z_full once before timestep loop
**File:** `icon_d2_pipeline/pipeline.py:592-593`

`flip_to_bottom_up(z_full)` creates a new copy every call but z_full never changes. Flip once before the loop.

### [x] A5. Use `np.savetxt` in data file writer
**File:** `icon_d2_pipeline/output/data_file.py:91-101`

Replace row-by-row `" ".join(str(v) for v in row)` with `np.savetxt(f, data, fmt="%d")`.

### [x] A6. Log warning when SSL verification disabled
**File:** `icon_d2_pipeline/download.py:240-242`

Add `logger.warning(...)` before `ssl_ctx.check_hostname = False`.

### [x] B2. Document VHF temperature choice
**File:** `icon_d2_pipeline/fields.py:227-230`

NCL uses lowest model level T; Python uses T_2M. Difference is ~0.5-2K, acceptable. Add a comment explaining the choice.

---

## Verification

1. Run `python test_pipeline_e2e.py` — no regressions
2. Spot-check `pfd_tot` values against expected range after B1 fix
3. Run `gdalinfo` on output .tiff files to verify correct EPSG:3857 resolution after A1
4. Time a full run before/after A2 to measure ProcessPool speedup
5. Compare wstar, sfcsunpct, zsfclcl ranges for physical plausibility after B3/B4/B6
