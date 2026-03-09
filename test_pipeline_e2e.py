"""End-to-end test: download real ICON-D2 data and run pipeline for 1 timestep."""
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from icon_d2_pipeline.config import (
    GRIB_2D_VARS, GRIB_3D_VARS, GRIB_INVARIANT_VARS, GRIB_ICO_COORD_VARS,
    ICON_D2_NUM_LEVELS, ICON_D2_NUM_HALF_LEVELS,
)
from icon_d2_pipeline.download import build_urls, download_all
from icon_d2_pipeline.fields import (
    read_grib_field, get_lat_lon_from_meta, compute_model_heights,
    flip_to_bottom_up, compute_derived_2d, compute_derived_3d,
    load_2d_field, load_3d_field_ico,
)
from icon_d2_pipeline.grid import find_bbox_indices, get_grid_info
from icon_d2_pipeline.remap import IconRemapper, read_ico_grid_coords
from icon_d2_pipeline.calc.thermal import calc_wstar, calc_hcrit
from icon_d2_pipeline.calc.boundary_layer import calc_blavg, calc_blwind, calc_bltopwind
from icon_d2_pipeline.calc.cloud import calc_sfclcl_height
from icon_d2_pipeline.calc.derived import calc_bsratio, calc_hbl, calc_hglider
from icon_d2_pipeline.calc.wind import calc_sfcwind0
from icon_d2_pipeline.output.data_file import write_data_file, get_data_filename
from icon_d2_pipeline.output.json_meta import write_title_json, get_json_filename


def main():
    t0 = time.time()
    run_date = datetime(2026, 3, 9)
    init_hour = 0
    forecast_hour = 6  # Single forecast hour (06 UTC = ~07 local CET)
    grib_dir = Path("/tmp/icon_d2_test_e2e")
    out_dir = Path("/tmp/icon_d2_test_e2e/OUT")
    out_dir.mkdir(parents=True, exist_ok=True)

    date_init = f"{run_date.strftime('%Y%m%d')}{init_hour:02d}"

    # ---- Step 1: Download ----
    logger.info("=== Step 1: Download GRIB files ===")

    # Download only what we need for one timestep:
    # - 2D single-level vars (1 file each)
    # - Time-invariant (HSURF + HHL 66 levels + FR_LAND)
    # - Icosahedral coords (CLAT, CLON)
    # - 3D model-level for a few key vars (T, P, U, V, W, QV, QC)
    all_vars = GRIB_2D_VARS + GRIB_INVARIANT_VARS + GRIB_ICO_COORD_VARS + GRIB_3D_VARS
    # Include previous hour for flux de-accumulation
    urls = build_urls(run_date, init_hour, [forecast_hour - 1, forecast_hour], all_vars)

    logger.info(f"Total files to download: {len(urls)}")
    # This is a LOT of files (65 levels × 7 vars = 455 model-level files + ~20 2D + 66 HHL + 2 ico)
    # Let's be selective: only download bottom 20 levels for 3D (where BL matters)
    # and skip QC (not critical for initial test)
    filtered_urls = []
    import re
    for url, local in urls:
        # Check if this is a model-level file (has _mlNNN pattern)
        m = re.search(r'_ml(\d+)\.grib2', local)
        if m:
            # Model-level: only keep bottom 20 levels (levels 46-65 in ICON top-down)
            level = int(m.group(1))
            if level >= 46:
                filtered_urls.append((url, local))
        else:
            # Keep all non-model-level files
            filtered_urls.append((url, local))

    logger.info(f"Filtered to {len(filtered_urls)} files (bottom 20 model levels only)")

    downloaded = asyncio.run(download_all(filtered_urls, grib_dir, max_concurrent=30))
    logger.info(f"Downloaded {len(downloaded)}/{len(filtered_urls)} files")

    t1 = time.time()
    logger.info(f"Download took {t1-t0:.1f}s")

    # ---- Step 2: Load grid ----
    logger.info("=== Step 2: Load grid and invariant fields ===")

    # Find a regular-lat-lon file for grid info
    sample_file = grib_dir / f"icon-d2_{date_init}_{forecast_hour:03d}_t_2m_sl.grib2"
    if not sample_file.exists():
        logger.error(f"Sample file not found: {sample_file}")
        return

    _, meta = read_grib_field(sample_file)
    lat_full, lon_full = get_lat_lon_from_meta(meta)
    lat_slice, lon_slice = find_bbox_indices(lat_full, lon_full)
    lat = lat_full[lat_slice]
    lon = lon_full[lon_slice]
    grid_info = get_grid_info(lat, lon)
    ny, nx = grid_info["ny"], grid_info["nx"]
    logger.info(f"Domain: {ny}x{nx}, lat [{lat[0]:.2f},{lat[-1]:.2f}], lon [{lon[0]:.2f},{lon[-1]:.2f}]")

    # Load terrain
    ter_file = grib_dir / f"icon-d2_{date_init}_000_hsurf_inv.grib2"
    ter_data, _ = read_grib_field(ter_file)
    ter = np.maximum(ter_data[lat_slice, lon_slice], 1.0)
    logger.info(f"Terrain: {ter.min():.0f}m to {ter.max():.0f}m")

    # Load HHL (half-level heights)
    hhl_levels = []
    for level in range(1, 67):
        hhl_file = grib_dir / f"icon-d2_{date_init}_000_hhl_inv{level:03d}.grib2"
        if hhl_file.exists():
            data, _ = read_grib_field(hhl_file)
            hhl_levels.append(data[lat_slice, lon_slice])
    if len(hhl_levels) == 66:
        z_half = np.stack(hhl_levels, axis=0)
        z_full = compute_model_heights(z_half)
        z = flip_to_bottom_up(z_full)
        logger.info(f"Model heights: {z.shape}, surface={z[0].mean():.0f}m, top={z[-1].mean():.0f}m")
    else:
        logger.warning(f"Only {len(hhl_levels)}/66 HHL levels loaded")
        z = None

    # ---- Step 3: Set up remapper ----
    logger.info("=== Step 3: Initialize icosahedral remapper ===")
    clat_file = grib_dir / f"icon-d2_{date_init}_000_clat_ico.grib2"
    clon_file = grib_dir / f"icon-d2_{date_init}_000_clon_ico.grib2"

    if clat_file.exists() and clon_file.exists():
        ico_lats, ico_lons = read_ico_grid_coords(clat_file, clon_file)
        remapper = IconRemapper(lat, lon)
        remapper.build_weights(ico_lats, ico_lons)
    else:
        logger.error("CLAT/CLON not found")
        return

    # ---- Step 4: Load 2D fields ----
    logger.info("=== Step 4: Load 2D fields ===")
    raw_2d = {}
    for var in GRIB_2D_VARS:
        var_lower = var.lower()
        try:
            raw_2d[var] = load_2d_field(grib_dir, date_init, forecast_hour,
                                        var_lower, lat_slice, lon_slice)
            logger.info(f"  {var}: {raw_2d[var].min():.2f} to {raw_2d[var].max():.2f}")
        except Exception as e:
            logger.warning(f"  {var}: {e}")

    # De-accumulate time-mean fluxes
    if forecast_hour > 0:
        for flux_var in ["ASHFL_S", "ALHFL_S"]:
            if flux_var in raw_2d:
                try:
                    prev = load_2d_field(grib_dir, date_init, forecast_hour - 1,
                                         flux_var.lower(), lat_slice, lon_slice)
                    accum_now = forecast_hour * raw_2d[flux_var]
                    accum_prev = (forecast_hour - 1) * prev
                    instantaneous = accum_now - accum_prev
                    logger.info(f"  {flux_var} de-accumulated: {instantaneous.min():.1f} to {instantaneous.max():.1f} W/m²")
                    raw_2d[flux_var] = instantaneous
                except Exception as e:
                    logger.warning(f"  {flux_var} de-accumulation failed: {e}")

    fields_2d = compute_derived_2d(raw_2d)

    # ---- Step 5: Load 3D fields (icosahedral → remap) ----
    logger.info("=== Step 5: Load and remap 3D fields ===")
    raw_3d = {}
    n_levels_to_use = 20  # Only bottom 20 levels
    for var in GRIB_3D_VARS:
        var_lower = var.lower()
        try:
            t_load = time.time()
            num_lev = ICON_D2_NUM_HALF_LEVELS if var == "W" else ICON_D2_NUM_LEVELS
            # Only load levels 46-65 (bottom 20)
            levels_data = []
            for level in range(num_lev - n_levels_to_use + 1, num_lev + 1):
                from icon_d2_pipeline.fields import read_grib_ico_field
                filename = f"icon-d2_{date_init}_{forecast_hour:03d}_{var_lower}_ml{level:03d}.grib2"
                filepath = grib_dir / filename
                if filepath.exists():
                    levels_data.append(read_grib_ico_field(filepath))
                else:
                    break
            if levels_data:
                ico_data = np.stack(levels_data, axis=0)
                remapped = remapper.remap_3d(ico_data)
                # Flip: these are bottom 20 levels (46-65), already near-surface last
                raw_3d[var] = remapped[::-1]  # Now index 0 = lowest level
                dt = time.time() - t_load
                logger.info(f"  {var}: {len(levels_data)} levels, remapped in {dt:.2f}s, "
                           f"range={raw_3d[var].min():.2f} to {raw_3d[var].max():.2f}")
        except Exception as e:
            logger.warning(f"  {var}: {e}")

    # Use subset of z that matches our 20 levels
    if z is not None:
        z_subset = z[:n_levels_to_use]  # Bottom 20 levels
    else:
        z_subset = None

    fields_3d = compute_derived_3d(raw_3d, raw_2d)

    # ---- Step 6: Compute soaring parameters ----
    logger.info("=== Step 6: Compute soaring parameters ===")

    # PBL height
    pblh = raw_2d.get("MH", None)
    if pblh is not None:
        logger.info(f"  PBLH (MH): {pblh.min():.0f}m to {pblh.max():.0f}m")
    else:
        pblh = np.full((ny, nx), 1000.0)
        logger.warning("  PBLH: using fallback 1000m")

    # wstar
    vhf = fields_2d.get("vhf", np.zeros((ny, nx)))
    wstar = calc_wstar(vhf, pblh)
    logger.info(f"  wstar: {wstar.min():.2f} to {wstar.max():.2f} m/s")

    # hcrit
    hcrit = calc_hcrit(wstar, ter, pblh)
    logger.info(f"  hcrit: {hcrit.min():.0f} to {hcrit.max():.0f} m MSL")

    # hbl
    hbl = pblh + ter
    logger.info(f"  hbl: {hbl.min():.0f} to {hbl.max():.0f} m MSL")

    # Surface wind
    u10 = raw_2d.get("U_10M", np.zeros((ny, nx)))
    v10 = raw_2d.get("V_10M", np.zeros((ny, nx)))
    _, _, sfcwind = calc_sfcwind0(u10, v10)
    logger.info(f"  sfcwind0: {sfcwind.min():.1f} to {sfcwind.max():.1f} m/s")

    # BL wind (if 3D available)
    ua = fields_3d.get("U", None)
    va = fields_3d.get("V", None)
    if ua is not None and va is not None and z_subset is not None:
        _, _, blwind = calc_blwind(ua, va, z_subset, ter, pblh)
        logger.info(f"  blwind: {blwind.min():.1f} to {blwind.max():.1f} m/s")

        _, _, bltopwind = calc_bltopwind(ua, va, z_subset, ter, pblh)
        logger.info(f"  bltopwind: {bltopwind.min():.1f} to {bltopwind.max():.1f} m/s")

        bsratio = calc_bsratio(blwind, wstar)
        logger.info(f"  bsratio: {bsratio.min():.1f} to {bsratio.max():.1f}")

    # CAPE (direct from ICON-D2)
    cape = raw_2d.get("CAPE_ML", None)
    if cape is not None:
        logger.info(f"  CAPE: {cape.min():.0f} to {cape.max():.0f} J/kg")

    # Cloud fractions (direct)
    for name in ["CLCL", "CLCM", "CLCH"]:
        val = raw_2d.get(name, None)
        if val is not None:
            logger.info(f"  {name}: {val.min():.3f} to {val.max():.3f}")

    # sfctemp
    sfctemp = fields_2d.get("sfctemp", None)
    if sfctemp is not None:
        logger.info(f"  sfctemp: {sfctemp.min():.1f} to {sfctemp.max():.1f} C")

    # sfcdewpt
    sfcdewpt = fields_2d.get("sfcdewpt", None)
    if sfcdewpt is not None:
        logger.info(f"  sfcdewpt: {sfcdewpt.min():.1f} to {sfcdewpt.max():.1f} C")

    # SLP
    pmsl = raw_2d.get("PMSL", None)
    if pmsl is not None:
        slp = pmsl / 100.0
        logger.info(f"  SLP: {slp.min():.1f} to {slp.max():.1f} hPa")

    # ---- Step 7: Write sample output ----
    logger.info("=== Step 7: Write output files ===")

    valid_dt = datetime(2026, 3, 9, 7, 0)
    ts_local = "0700"

    results = {
        "wstar": wstar,
        "hbl": hbl,
        "sfctemp": sfctemp,
        "sfcwind0": sfcwind,
        "wrf=slp": slp if pmsl is not None else np.zeros((ny, nx)),
        "wrf=HGT": ter,
    }
    if cape is not None:
        results["cape"] = cape

    for param_name, data in results.items():
        if data is None:
            continue
        data_filename = get_data_filename(param_name, ts_local)
        data_path = out_dir / data_filename
        write_data_file(data_path, param_name, data, grid_info,
                        valid_dt, "6", init_hour, "CET")
        logger.info(f"  Wrote {data_filename}")

        json_filename = get_json_filename(param_name, ts_local)
        json_path = out_dir / json_filename
        write_title_json(json_path, param_name, data, valid_dt, "6", init_hour, "CET")
        logger.info(f"  Wrote {json_filename}")

    # ---- Verify .data file is readable ----
    logger.info("=== Step 8: Verify output ===")
    sample_data = out_dir / get_data_filename("wstar", ts_local)
    with open(sample_data) as f:
        lines = f.readlines()
    logger.info(f"  .data file header:")
    for i, line in enumerate(lines[:4]):
        logger.info(f"    Line {i+1}: {line.rstrip()[:100]}")
    # Read grid data
    grid_data = np.loadtxt(sample_data, skiprows=4)
    logger.info(f"  Grid data shape: {grid_data.shape}, range: {grid_data.min():.0f} to {grid_data.max():.0f}")

    t_end = time.time()
    logger.info(f"\n=== DONE in {t_end-t0:.1f}s ===")


if __name__ == "__main__":
    main()
