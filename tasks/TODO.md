# icon-d2-pipeline — Open Items

## Bugs / Issues
- [ ] **PFD values too low**: Python PFD max ~217 km vs GFS WRF ~355 km. Calculation in `calc/pfd.py` needs investigation — likely different wstar/thermal height inputs or algorithm differences
- [ ] **PFD body.png appears white**: First PFD color bin (100-200 km) uses white from pfd.rgb colormap, so low values are invisible on white background. Either adjust colormap or fix underlying PFD calculation
- [ ] **Exit code 139 (OOM kill)**: Docker container gets SIGKILL after pipeline completes successfully. Happens when WRF containers are also running (~30GB total RAM). Not a functional issue but messy
- [ ] **surface.py RuntimeWarning**: divide by zero in sunshine calculation at low sun angles — cosmetic, already guarded by `np.where`

## Missing Features
- [ ] **Cron integration**: Pipeline not yet in cron schedule. Need to add to `run.0Z.cron.sh` etc. alongside WRF runs
- [ ] **Day 1 forecast**: Currently only day 0 runs. ICON-D2 supports up to day 2 (48h forecast)
- [ ] **Coastlines on body.png**: NCL body.png has coastlines baked in; Python version doesn't. Leaflet map shows them underneath but overlay opacity can hide them
- [ ] **DST time array**: `tzArrayD2Py["DST"]` in `index.html` is same as STD — needs +1h offset for summer time
- [ ] **CAPE discrepancy**: Python uses ICON-D2's native `CAPE_ML` (max ~324 J/kg) vs WRF computed CAPE (max ~1203 J/kg). Different definitions — may need own CAPE calculation to match

## Potential Improvements
- [ ] **Parallel PNG rendering**: PNG generation adds ~80s to pipeline. Could use multiprocessing for body rendering
- [ ] **Colormap accuracy**: Current BlAqGrYeOrReVi200 is an approximation with interpolated anchor points. Could extract exact RGB values from NCL source
- [ ] **GRIB cache cleanup**: 14GB cache in `/tmp/icon_d2_grib` grows without bound. Need age-based eviction
- [ ] **Remove NCL dependency**: Once Python pipeline is fully validated, remove ICON-D2 NCL button and symlinks from viewer

## Done
- [x] **wstar 10x too high**: Fixed — was missing energy→kinematic flux conversion (÷ρ·cp ≈ 1200)
- [x] **PNG rendering**: Added body/head/foot/side PNG generation matching NCL output format
- [x] **RASPViewer integration**: Viewer button, symlinks, corners, PFD naming all working
- [x] **Pipeline end-to-end**: Download → compute → output runs in ~4.5 min (with GRIB cache)
