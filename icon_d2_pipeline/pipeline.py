"""Pipeline orchestrator: download -> compute -> output.

This is the main entry point that coordinates all steps of the ICON-D2
soaring weather pipeline.
"""

import asyncio
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .calc.boundary_layer import (
    calc_blavg,
    calc_bltop_pottemp_variability,
    calc_blwind,
    calc_blwinddiff,
    calc_bltopwind,
    calc_wblmaxmin,
)
from .calc.cape import calc_cape
from .calc.cloud import (
    calc_blcl_height,
    calc_blcloudbase,
    calc_blcloudpct,
    calc_sfclcl_height,
)
from .calc.derived import (
    calc_bsratio,
    calc_cfrac,
    calc_hbl,
    calc_hglider,
    calc_rain1,
    calc_zblcldif,
    calc_zblclmask,
    calc_zsfclcldif,
    calc_zsfclclmask,
)
from .calc.pfd import compute_pfd_tot, compute_pfd_tot2, compute_pfd_tot3
from .calc.pressure import calc_pressure_level_winds
from .calc.surface import calc_sfcdewpt, calc_sfcsunpct, calc_sfctemp
from .calc.thermal import calc_hlift, calc_hcrit, calc_wstar
from .calc.wind import calc_sfcwind0
from .config import (
    GRIB_2D_VARS,
    GRIB_3D_VARS,
    GRIB_ICO_COORD_VARS,
    GRIB_INVARIANT_VARS,
    ICON_D2_NUM_LEVELS,
    PRESSURE_LEVELS,
    REGION,
    TIMESTEPS_LOCAL,
)
from .download import build_urls, download_all, get_forecast_hours
from .fields import (
    compute_derived_2d,
    compute_derived_3d,
    compute_model_heights,
    flip_to_bottom_up,
    get_lat_lon_from_meta,
    interpolate_half_hour,
    load_2d_field,
    load_3d_field,
    load_3d_field_ico,
    load_invariant_field,
    read_grib_field,
    read_grib_ico_field,
)
from .remap import IconRemapper, read_ico_grid_coords
from .grid import find_bbox_indices, get_grid_info, subset_domain
from .output.data_file import get_data_filename, write_data_file
from .output.geotiff import write_geotiff
from .output.json_meta import get_json_filename, write_title_json
from .output.png_render import write_pngs

logger = logging.getLogger(__name__)

# Module-level globals for ProcessPoolExecutor workers
_worker_weights = None
_worker_indices = None
_worker_target_shape = None


def _init_worker(weights, indices, target_shape):
    """Initialize worker process with shared remapper data."""
    global _worker_weights, _worker_indices, _worker_target_shape
    _worker_weights = weights
    _worker_indices = indices
    _worker_target_shape = target_shape


def _read_and_remap(filepath_str):
    """Read icosahedral GRIB and remap to regular grid (runs in worker process)."""
    import eccodes
    with open(filepath_str, "rb") as f:
        msgid = eccodes.codes_grib_new_from_file(f)
        try:
            ico_1d = eccodes.codes_get_values(msgid)
        finally:
            eccodes.codes_release(msgid)
    neighbor_vals = ico_1d[_worker_indices]
    result = np.sum(neighbor_vals * _worker_weights, axis=1)
    return result.reshape(_worker_target_shape).astype(np.float32)


def run_pipeline(run_date: datetime, init_hour: int, start_day: int,
                 results_dir: Path, grib_dir: Path | None = None,
                 tz_offset: int = 1) -> bool:
    """Run the complete ICON-D2 soaring parameter pipeline.

    Args:
        run_date: The model run date.
        init_hour: Model initialization hour (UTC).
        start_day: Forecast day offset (0=today, 1=tomorrow).
        results_dir: Base results directory (e.g., /tmp/results).
        grib_dir: Directory for GRIB downloads. Default: /tmp/icon_d2_grib.
        tz_offset: UTC offset for local time (1=CET, 2=CEST).

    Returns:
        True if pipeline completed successfully.
    """
    t_start = time.time()

    # Construct run prefix
    now = datetime.now()
    run_prefix = f"{now.strftime('%Y%m%d_%H%M')}_{REGION}_{start_day}"
    run_dir = results_dir / run_prefix
    out_dir = run_dir / "OUT"
    log_dir = run_dir / "LOG"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    if grib_dir is None:
        grib_dir = Path("/tmp/icon_d2_grib")
    grib_dir.mkdir(parents=True, exist_ok=True)

    tz_id = "CET" if tz_offset == 1 else "CEST"

    logger.info(f"Pipeline start: {REGION} init={init_hour}Z day={start_day}")
    logger.info(f"Output: {run_dir}")

    # ---- Step 1: Download GRIB files ----
    logger.info("Step 1: Downloading ICON-D2 GRIB files...")
    forecast_hours = get_forecast_hours(init_hour, start_day, tz_offset)
    logger.info(f"Forecast hours needed: {forecast_hours}")

    all_vars = GRIB_3D_VARS + GRIB_2D_VARS + GRIB_INVARIANT_VARS + GRIB_ICO_COORD_VARS
    urls = build_urls(run_date, init_hour, forecast_hours, all_vars)
    logger.info(f"Total files to download: {len(urls)}")

    downloaded = asyncio.run(download_all(urls, grib_dir))
    if len(downloaded) < len(urls) * 0.8:
        logger.error(f"Too many download failures: {len(downloaded)}/{len(urls)}")
        return False

    # ---- Step 2: Load grid and invariant fields ----
    logger.info("Step 2: Loading grid and invariant fields...")
    date_init = f"{run_date.strftime('%Y%m%d')}{init_hour:02d}"

    # Get grid info from a regular-lat-lon file (not icosahedral)
    sample_file = next(grib_dir.glob("icon-d2_*_sl.grib2"), None)
    if sample_file is None:
        sample_file = next(grib_dir.glob("icon-d2_*_inv.grib2"), None)
    if sample_file is None:
        logger.error("No regular-lat-lon GRIB files found")
        return False

    _, meta = read_grib_field(sample_file)
    lat_full, lon_full = get_lat_lon_from_meta(meta)
    lat_slice, lon_slice = find_bbox_indices(lat_full, lon_full)
    lat = lat_full[lat_slice]
    lon = lon_full[lon_slice]
    grid_info = get_grid_info(lat, lon)
    ny, nx = grid_info["ny"], grid_info["nx"]
    logger.info(f"Domain: {ny}x{nx} grid points, "
                f"lat [{grid_info['lat_min']:.2f}, {grid_info['lat_max']:.2f}], "
                f"lon [{grid_info['lon_min']:.2f}, {grid_info['lon_max']:.2f}]")

    # Load terrain height (HSURF)
    ter = load_invariant_field(grib_dir, date_init, "hsurf", lat_slice, lon_slice)
    ter = np.maximum(ter, 1.0)  # Floor at 1m like WRF code

    # Load land fraction for masking thermals over water
    try:
        fr_land = load_invariant_field(grib_dir, date_init, "fr_land", lat_slice, lon_slice)
    except Exception as e:
        logger.warning(f"FR_LAND not available — no land/water masking: {e}", exc_info=True)
        fr_land = None

    # Load half-level heights (HHL) — individual files per half-level
    hhl_levels = []
    for level in range(1, 67):  # 66 half-levels
        hhl_file = grib_dir / f"icon-d2_{date_init}_000_hhl_inv{level:03d}.grib2"
        if hhl_file.exists():
            data, _ = read_grib_field(hhl_file)
            hhl_levels.append(data[lat_slice, lon_slice])
        else:
            break
    if len(hhl_levels) == 66:
        z_half = np.stack(hhl_levels, axis=0)  # (66, ny, nx)
        z_full = compute_model_heights(z_half)  # (65, ny, nx)
    else:
        logger.warning(f"HHL incomplete ({len(hhl_levels)}/66), will compute heights from pressure")
        z_full = None

    # Initialize icosahedral grid remapper for 3D model-level data
    clat_file = grib_dir / f"icon-d2_{date_init}_000_clat_ico.grib2"
    clon_file = grib_dir / f"icon-d2_{date_init}_000_clon_ico.grib2"
    remapper = None
    if clat_file.exists() and clon_file.exists():
        ico_lats, ico_lons = read_ico_grid_coords(clat_file, clon_file)
        remapper = IconRemapper(lat, lon)
        remapper.build_weights(ico_lats, ico_lons)
    else:
        logger.warning("CLAT/CLON not found — cannot remap icosahedral data")

    # Pre-flip z_full to bottom-up once (avoids redundant flipping per hour)
    z_bottom_up = flip_to_bottom_up(z_full) if z_full is not None else None

    # Create ProcessPoolExecutor once for all timesteps (avoids per-hour overhead)
    executor = None
    if remapper is not None:
        executor = ProcessPoolExecutor(
            max_workers=os.cpu_count(),
            initializer=_init_worker,
            initargs=(remapper._weights, remapper._indices, remapper._target_shape),
        )

    # ---- Step 3: Process each timestep ----
    logger.info("Step 3: Processing timesteps...")

    # Cache for hourly loaded fields (to avoid reloading for half-hour interp)
    # Evict old hours to avoid OOM — keep at most 2 hours in cache
    hourly_cache = {}
    prev_tot_prec = None

    for ts_idx, ts_local in enumerate(TIMESTEPS_LOCAL):
        logger.info(f"  Timestep {ts_idx+1}/{len(TIMESTEPS_LOCAL)}: {ts_local} local")

        # Convert local time to UTC forecast hour
        local_hour = int(ts_local[:2])
        local_min = int(ts_local[2:])
        utc_hour = local_hour - tz_offset + 24 * start_day
        fh = utc_hour - init_hour

        # Determine if we need interpolation (half-hour)
        if local_min == 30:
            # Interpolate between fh (at :00) and fh+1 (at next :00)
            fh_lo = fh
            fh_hi = fh + 1
            weight = 0.5

            fields_lo = _load_fields_for_hour(
                grib_dir, date_init, fh_lo, lat_slice, lon_slice,
                z_bottom_up, ter, hourly_cache, remapper, executor)
            fields_hi = _load_fields_for_hour(
                grib_dir, date_init, fh_hi, lat_slice, lon_slice,
                z_bottom_up, ter, hourly_cache, remapper, executor)

            if fields_lo is None or fields_hi is None:
                logger.warning(f"  Skipping {ts_local}: missing data")
                continue

            fields_2d = interpolate_half_hour(fields_lo["2d"], fields_hi["2d"], weight)
            fields_3d = interpolate_half_hour(fields_lo["3d"], fields_hi["3d"], weight)
            pblh = (1 - weight) * fields_lo["pblh"] + weight * fields_hi["pblh"]
            z = fields_lo["z"]  # Heights don't change
        else:
            loaded = _load_fields_for_hour(
                grib_dir, date_init, fh, lat_slice, lon_slice,
                z_bottom_up, ter, hourly_cache, remapper, executor)
            if loaded is None:
                logger.warning(f"  Skipping {ts_local}: missing data")
                continue
            fields_2d = loaded["2d"]
            fields_3d = loaded["3d"]
            pblh = loaded["pblh"]
            z = loaded["z"]

        # Evict old cache entries to limit memory (keep max 2 hours)
        needed_hours = {fh}
        if local_min == 30:
            needed_hours = {fh, fh + 1}
        for cached_fh in list(hourly_cache.keys()):
            if cached_fh not in needed_hours:
                del hourly_cache[cached_fh]

        # Construct valid time
        valid_dt = datetime(run_date.year, run_date.month, run_date.day,
                            local_hour, local_min)
        if start_day > 0:
            valid_dt += timedelta(days=start_day)
        forecast_str = f"{fh}"

        # ---- Compute all parameters ----
        results = {}

        # Surface params
        nan_default = np.full((ny, nx), np.nan, dtype=np.float32)
        results["sfctemp"] = calc_sfctemp(fields_2d.get("sfctemp", nan_default.copy()))
        results["sfcdewpt"] = calc_sfcdewpt(fields_2d.get("sfcdewpt", nan_default.copy()))

        # Virtual heat flux and wstar — suppress over water
        vhf = fields_2d.get("vhf", None)
        if vhf is None:
            logger.warning("VHF not available for this timestep")
            vhf = np.full((ny, nx), np.nan, dtype=np.float32)
        if fr_land is not None:
            vhf = vhf * fr_land  # Scale by land fraction (0 over water, 1 over land)

        # Compute BL-averaged temperature for wstar scaling
        t_3d = fields_3d.get("T", None)
        if t_3d is not None:
            t_blavg = calc_blavg(t_3d, z, ter, pblh)
        else:
            t_blavg = 300.0
        wstar = calc_wstar(vhf, pblh, t_blavg)
        results["wstar"] = wstar
        results["wstar175"] = wstar  # Same data, different contour levels

        # Thermal heights
        hcrit = calc_hcrit(wstar, ter, pblh)
        results["experimental1"] = calc_hlift(175.0, wstar, ter, pblh)

        # BL height
        results["hbl"] = calc_hbl(pblh, ter)

        # BL variability
        theta = fields_3d.get("theta", None)
        if theta is not None:
            results["bltopvariab"] = calc_bltop_pottemp_variability(theta, z, ter, pblh)

        # Wind parameters
        u10m = fields_2d.get("U_10M", nan_default.copy())
        v10m = fields_2d.get("V_10M", nan_default.copy())
        u_sfc, v_sfc, spd_sfc = calc_sfcwind0(u10m, v10m)
        results["sfcwind0"] = spd_sfc

        ua = fields_3d.get("U", None)
        va = fields_3d.get("V", None)
        if ua is not None and va is not None:
            u_blavg, v_blavg, spd_blavg = calc_blwind(ua, va, z, ter, pblh)
            results["blwind"] = spd_blavg

            u_top, v_top, spd_top = calc_bltopwind(ua, va, z, ter, pblh)
            results["bltopwind"] = spd_top

            results["blwindshear"] = calc_blwinddiff(ua, va, z, ter, pblh)

            # Buoyancy/shear ratio
            results["bsratio"] = calc_bsratio(spd_blavg, wstar)

        # Vertical velocity (W is on half-levels, interpolate to full-levels)
        wa = fields_3d.get("W", None)
        if wa is not None:
            if wa.shape[0] > z.shape[0]:
                wa = 0.5 * (wa[:-1] + wa[1:])  # half-levels -> full-levels
            results["wblmaxmin"] = calc_wblmaxmin(0, wa, z, ter, pblh)
            results["zwblmaxmin"] = calc_wblmaxmin(1, wa, z, ter, pblh)

        # Cloud parameters
        tc_3d = fields_3d.get("tc", None)
        td_3d = fields_3d.get("td", None)
        pmb_3d = fields_3d.get("pmb", None)
        qvapor = fields_3d.get("QV", None)
        qcloud = fields_3d.get("QC", None)

        if tc_3d is not None and td_3d is not None and pmb_3d is not None:
            zsfclcl = calc_sfclcl_height(pmb_3d, tc_3d, td_3d, z, ter, pblh)
            results["zsfclcl"] = zsfclcl

            zsfclcldif = calc_zsfclcldif(ter, pblh, zsfclcl)
            results["zsfclcldif"] = zsfclcldif
            results["zsfclclmask"] = calc_zsfclclmask(zsfclcl, zsfclcldif)

            if qvapor is not None:
                qv_blavg = calc_blavg(qvapor, z, ter, pblh)
                zblcl = calc_blcl_height(pmb_3d, tc_3d, qv_blavg, z, ter, pblh)
                results["zblcl"] = zblcl

                zblcldif = calc_zblcldif(ter, pblh, zblcl)
                results["zblcldif"] = zblcldif
                results["zblclmask"] = calc_zblclmask(zblcl, zblcldif)

            # Thermalling height (depends on hcrit, zsfclcl, zblcl)
            zblcl_for_hglider = results.get("zblcl", zsfclcl)
            results["hglider"] = calc_hglider(hcrit, zsfclcl, zblcl_for_hglider)

        if qvapor is not None and qcloud is not None and tc_3d is not None and pmb_3d is not None:
            results["blcloudpct"] = calc_blcloudpct(
                qvapor, qcloud, tc_3d, pmb_3d, z, ter, pblh)

        # Sunshine percentage
        swdown = fields_2d.get("swdown", None)
        if swdown is not None:
            jday = valid_dt.timetuple().tm_yday
            gmt_hr = local_hour - tz_offset + local_min / 60.0
            results["sfcsunpct"] = calc_sfcsunpct(
                swdown, jday, gmt_hr, lat, lon, ter, z, pmb_3d, tc_3d, qvapor)

        # CAPE — use ICON-D2's directly computed CAPE_ML if available
        cape_ml = fields_2d.get("CAPE_ML", None)
        if cape_ml is not None:
            results["cape"] = cape_ml
        elif pmb_3d is not None and tc_3d is not None and td_3d is not None:
            results["cape"] = calc_cape(pmb_3d, tc_3d, td_3d)

        # Rain
        tot_prec = fields_2d.get("TOT_PREC", None)
        if tot_prec is not None:
            if prev_tot_prec is not None:
                results["rain1"] = calc_rain1(tot_prec, prev_tot_prec)
            else:
                results["rain1"] = np.zeros((ny, nx), dtype=np.float32)
            prev_tot_prec = tot_prec.copy()

        # Cloud fractions — use ICON-D2's directly computed CLCL/CLCM/CLCH
        clcl = fields_2d.get("CLCL", None)
        clcm = fields_2d.get("CLCM", None)
        clch = fields_2d.get("CLCH", None)
        if clcl is not None:
            results["cfracl"] = clcl.astype(np.float32)  # already 0-100%
        else:
            results["cfracl"] = np.full((ny, nx), np.nan, dtype=np.float32)
        if clcm is not None:
            results["cfracm"] = clcm.astype(np.float32)  # already 0-100%
        else:
            results["cfracm"] = np.full((ny, nx), np.nan, dtype=np.float32)
        if clch is not None:
            results["cfrach"] = clch.astype(np.float32)  # already 0-100%
        else:
            results["cfrach"] = np.full((ny, nx), np.nan, dtype=np.float32)

        # Pressure levels
        if ua is not None and va is not None and wa is not None and pmb_3d is not None:
            for plev in PRESSURE_LEVELS:
                u_p, v_p, w_p = calc_pressure_level_winds(ua, va, wa, pmb_3d, float(plev))
                param_name = f"press{plev}"
                results[param_name] = w_p
                # Also store u, v for wind direction/speed data files
                results[f"{param_name}_u"] = u_p
                results[f"{param_name}_v"] = v_p

        # MSL pressure (wrf=slp)
        pmsl = fields_2d.get("PMSL", None)
        if pmsl is not None:
            results["wrf=slp"] = (pmsl / 100.0).astype(np.float32)  # Pa to hPa

        # Terrain height (wrf=HGT)
        results["wrf=HGT"] = ter.astype(np.float32)

        # ---- Write output files ----
        for param_name, data in results.items():
            # Skip auxiliary fields
            if param_name.endswith("_u") or param_name.endswith("_v"):
                continue

            # Determine data format
            ldatafmt = 2 if param_name == "rain1" else 0

            # Write .data file
            data_filename = get_data_filename(param_name, ts_local)
            data_path = out_dir / data_filename
            write_data_file(data_path, param_name, data, grid_info,
                            valid_dt, forecast_str, init_hour, tz_id, ldatafmt)

            # Write GeoTIFF
            scaled = data * _get_param_mult(param_name)
            tiff_path = data_path.with_suffix(".data.tiff")
            write_geotiff(tiff_path, scaled, lat, lon)

            # Write .title.json
            json_filename = get_json_filename(param_name, ts_local)
            json_path = out_dir / json_filename
            write_title_json(json_path, param_name, data, valid_dt,
                             forecast_str, init_hour, tz_id)

            # Write PNGs (body, head, foot, side) for web viewer
            write_pngs(data, param_name, ts_local, out_dir, valid_dt,
                        forecast_str, init_hour, tz_id,
                        mult=_get_param_mult(param_name))

        # Write wind direction/speed data files for pressure levels
        for plev in PRESSURE_LEVELS:
            param_name = f"press{plev}"
            u_key = f"{param_name}_u"
            v_key = f"{param_name}_v"
            if u_key in results and v_key in results:
                # Wind direction
                u_p = results[u_key]
                v_p = results[v_key]
                wdir = 180.0 + np.degrees(np.arctan2(u_p, v_p))
                wdir_filename = f"{param_name}wdir.curr.{ts_local}lst.d2.data"
                write_data_file(out_dir / wdir_filename, f"{param_name}wdir",
                                wdir, grid_info, valid_dt, forecast_str, init_hour, tz_id)

                # Wind speed
                wspd = np.sqrt(u_p**2 + v_p**2)
                wspd_filename = f"{param_name}wspd.curr.{ts_local}lst.d2.data"
                write_data_file(out_dir / wspd_filename, f"{param_name}wspd",
                                wspd, grid_info, valid_dt, forecast_str, init_hour, tz_id)

    # Shutdown ProcessPoolExecutor
    if executor is not None:
        executor.shutdown(wait=True)

    # ---- Step 4: Compute PFD (reads .data files) ----
    logger.info("Step 4: Computing Potential Flight Distance...")

    pfd_results = {
        "pfd_tot": compute_pfd_tot(out_dir),
        "pfd_tot2": compute_pfd_tot2(out_dir),
        "pfd_tot3": compute_pfd_tot3(out_dir),
    }

    last_ts = TIMESTEPS_LOCAL[-1]
    last_valid_dt = datetime(run_date.year, run_date.month, run_date.day,
                             int(last_ts[:2]), int(last_ts[2:]))
    if start_day > 0:
        last_valid_dt += timedelta(days=start_day)

    for param_name, pfd_data in pfd_results.items():
        if pfd_data is not None:
            # Write with timestep (standard format)
            data_filename = get_data_filename(param_name, last_ts)
            write_data_file(out_dir / data_filename, param_name, pfd_data,
                            grid_info, last_valid_dt, str(forecast_hours[-1]),
                            init_hour, tz_id)

            tiff_path = (out_dir / data_filename).with_suffix(".data.tiff")
            write_geotiff(tiff_path, pfd_data, lat, lon)

            json_filename = get_json_filename(param_name, last_ts)
            write_title_json(out_dir / json_filename, param_name, pfd_data,
                             last_valid_dt, str(forecast_hours[-1]),
                             init_hour, tz_id)

            write_pngs(pfd_data, param_name, last_ts, out_dir,
                        last_valid_dt, str(forecast_hours[-1]),
                        init_hour, tz_id, mult=1.0)

            # Also write without timestep (viewer expects pfd_tot.body.png)
            write_data_file(out_dir / f"{param_name}.data", param_name,
                            pfd_data, grid_info, last_valid_dt,
                            str(forecast_hours[-1]), init_hour, tz_id)
            write_title_json(out_dir / f"{param_name}.title.json",
                             param_name, pfd_data, last_valid_dt,
                             str(forecast_hours[-1]), init_hour, tz_id)
            from .output.png_render import render_body, render_head, render_foot, \
                render_side, _compute_levels
            levels, colors, unit_str, is_fixed = _compute_levels(
                param_name, pfd_data, 1.0)
            render_body(pfd_data, levels, colors).save(
                out_dir / f"{param_name}.body.png", optimize=True)
            render_head(param_name, last_valid_dt, str(forecast_hours[-1]),
                        init_hour, tz_id).save(
                out_dir / f"{param_name}.head.png", optimize=True)
            render_foot(levels, colors, unit_str, is_fixed).save(
                out_dir / f"{param_name}.foot.png", optimize=True)
            render_side(levels, colors, unit_str, is_fixed).save(
                out_dir / f"{param_name}.side.png", optimize=True)

    # ---- Step 5: Signal completion ----
    # Touch GM.printout to trigger callback
    (log_dir / "GM.printout").touch()
    (log_dir / "done").touch()

    elapsed = time.time() - t_start
    logger.info(f"Pipeline complete in {elapsed:.1f}s")
    return True


def _get_param_mult(param_name: str) -> float:
    """Get the output multiplier for a parameter."""
    from .config import PARAM_UNITS
    return PARAM_UNITS.get(param_name, {"mult": 1.0})["mult"]


def _load_fields_for_hour(grib_dir: Path, date_init: str, fh: int,
                          lat_slice: slice, lon_slice: slice,
                          z_bottom_up: np.ndarray | None,
                          ter: np.ndarray,
                          cache: dict,
                          remapper: "IconRemapper | None" = None,
                          executor: "ProcessPoolExecutor | None" = None) -> dict | None:
    """Load all fields for a given forecast hour, using cache.

    Returns dict with keys: '2d', '3d', 'pblh', 'z'
    """
    if fh in cache:
        return cache[fh]

    try:
        # Load 2D fields (regular-lat-lon grid)
        raw_2d = {}
        for var in GRIB_2D_VARS:
            var_lower = var.lower()
            try:
                raw_2d[var] = load_2d_field(grib_dir, date_init, fh,
                                            var_lower, lat_slice, lon_slice)
            except Exception as e:
                if var in ("ASHFL_S", "ALHFL_S", "T_2M", "TD_2M", "ASWDIR_S", "ASWDIFD_S"):
                    logger.warning(f"Could not load essential 2D var {var} fh={fh}: {e}")
                else:
                    logger.debug(f"Could not load {var} fh={fh}: {e}")

        # De-accumulate time-mean fluxes to approximate instantaneous values
        # ICON-D2 ASHFL_S/ALHFL_S are time-means over [0, fh].
        # Instantaneous ≈ fh * mean(0,fh) - (fh-1) * mean(0,fh-1)
        if fh > 0:
            for flux_var in ["ASHFL_S", "ALHFL_S"]:
                if flux_var in raw_2d:
                    try:
                        prev = load_2d_field(grib_dir, date_init, fh - 1,
                                             flux_var.lower(), lat_slice, lon_slice)
                        # Convert from mean to accumulated, then difference
                        accum_now = fh * raw_2d[flux_var]
                        accum_prev = (fh - 1) * prev
                        raw_2d[flux_var] = accum_now - accum_prev
                    except Exception as e:
                        logger.warning(f"Flux de-accumulation failed for {flux_var} fh={fh}: {e}")

        # Derive 2D fields
        fields_2d = compute_derived_2d(raw_2d)

        # Load 3D fields (icosahedral grid → remap to regular lat-lon)
        # Use ProcessPoolExecutor for true parallelism (eccodes holds GIL)
        raw_3d = {}
        if remapper is not None and executor is not None:
            from .config import ICON_D2_NUM_HALF_LEVELS

            # Build all filepaths for all vars at once for maximum parallelism
            var_level_map = {}
            all_filepaths = []
            for var in GRIB_3D_VARS:
                var_lower = var.lower()
                num_lev = ICON_D2_NUM_HALF_LEVELS if var == "W" else ICON_D2_NUM_LEVELS
                filepaths = [
                    str(grib_dir / f"icon-d2_{date_init}_{fh:03d}_{var_lower}_ml{level:03d}.grib2")
                    for level in range(1, num_lev + 1)
                ]
                var_level_map[var] = (len(all_filepaths), len(filepaths))
                all_filepaths.extend(filepaths)

            try:
                all_results = list(executor.map(_read_and_remap, all_filepaths))

                for var, (start_idx, count) in var_level_map.items():
                    remapped_levels = all_results[start_idx:start_idx + count]
                    raw_3d[var] = flip_to_bottom_up(np.stack(remapped_levels, axis=0))
            except Exception as e:
                logger.warning(f"Could not load 3D fields for fh={fh}: {e}")

        # Heights (z_bottom_up is pre-flipped before the timestep loop)
        if z_bottom_up is not None:
            z = z_bottom_up
        else:
            # Fallback: compute heights from hypsometric equation
            z = _estimate_heights(raw_3d, ter)

        # Derive 3D fields
        fields_3d = compute_derived_3d(raw_3d, raw_2d)

        # PBL height from ICON-D2 mixing height (MH)
        pblh = raw_2d.get("MH", None)
        if pblh is None:
            pblh = _estimate_pblh(fields_3d, z, ter)

        result = {
            "2d": fields_2d,
            "3d": fields_3d,
            "pblh": pblh,
            "z": z,
        }
        cache[fh] = result
        return result

    except Exception as e:
        logger.error(f"Error loading fields for fh={fh}: {e}")
        return None


def _estimate_pblh(fields_3d: dict, z: np.ndarray,
                   ter: np.ndarray) -> np.ndarray:
    """Estimate PBL height from the theta profile.

    Uses the method of finding where theta exceeds its surface value
    by more than 1.5 K (commonly used for convective BL detection).
    """
    theta = fields_3d.get("theta", None)
    if theta is None:
        # Very rough fallback
        return np.full(ter.shape, 1000.0, dtype=np.float32)

    nz, ny, nx = theta.shape
    theta_sfc = theta[0]
    pblh = np.full((ny, nx), 100.0, dtype=np.float32)  # minimum 100m

    for k in range(1, nz):
        # BL top where theta exceeds surface theta by 1.5 K
        exceeds = (theta[k] > theta_sfc + 1.5) & (pblh < 200.0)
        agl = z[k] - ter
        pblh = np.where(exceeds, np.maximum(agl, 100.0), pblh)

    return pblh


def _estimate_heights(raw_3d: dict, ter: np.ndarray) -> np.ndarray:
    """Estimate model level heights from pressure using hypsometric equation."""
    p = raw_3d.get("P", None)
    t = raw_3d.get("T", None)
    if p is None or t is None:
        raise ValueError("Cannot estimate heights without P and T")

    nz, ny, nx = p.shape
    z = np.zeros((nz, ny, nx), dtype=np.float32)
    z[0] = ter

    for k in range(1, nz):
        t_avg = 0.5 * (t[k - 1] + t[k])
        z[k] = z[k - 1] + 29.3 * t_avg * np.log(p[k - 1] / np.maximum(p[k], 1.0))

    return z
