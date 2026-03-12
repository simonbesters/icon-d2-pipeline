#!/usr/bin/env python3
"""Extract meteogram site data from ICON-D2 pipeline output .data files.

Reads all .data files from a pipeline OUT directory, extracts the nearest
gridpoint value for a given lat/lon, and outputs a JSON suitable for
the interactive meteogram frontend.

Usage:
    python extract_meteogram.py /path/to/OUT --lat 51.5675 --lon 4.9319 --name "Gilze-Rijen"
    python extract_meteogram.py /path/to/OUT --sites sitedata.ncl

Can also fetch .data files from a remote URL:
    python extract_meteogram.py https://rasp.besters.digital/NL4KMGFS/NL+0-ICOND2PY \
        --lat 51.5675 --lon 4.9319 --name "Gilze-Rijen" --remote
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

# All parameters we want to extract for the meteogram
METEOGRAM_PARAMS = [
    # Thermal
    "wstar", "hbl", "hglider", "experimental1", "bltopvariab", "bsratio",
    # Cloud
    "zsfclcl", "zsfclcldif", "zsfclclmask", "zblcl", "zblcldif",
    "blcloudpct", "cfracl", "cfracm", "cfrach", "sfcsunpct",
    # Wind
    "sfcwind0", "blwind", "bltopwind", "blwindshear",
    "wblmaxmin", "zwblmaxmin",
    # Surface
    "sfctemp", "sfcdewpt", "cape", "rain1",
    # Pressure level winds (vertical velocity + direction/speed)
    "press955", "press899", "press846", "press795", "press701", "press616", "press540",
    "press955wspd", "press899wspd", "press846wspd", "press795wspd",
    "press701wspd", "press616wspd", "press540wspd",
    "press955wdir", "press899wdir", "press846wdir", "press795wdir",
    "press701wdir", "press616wdir", "press540wdir",
    # MSL pressure
    "wrf=slp",
]

# Timesteps to look for
TIMESTEPS = [
    "0730", "0800", "0830", "0900", "0930", "1000", "1030", "1100",
    "1130", "1200", "1230", "1300", "1330", "1400", "1430", "1500",
    "1530", "1600", "1630", "1700", "1730", "1800",
]

# Parameter metadata for the frontend
PARAM_META = {
    "wstar":        {"label": "W*", "unit": "m/s", "decimals": 1, "mult": 0.01},
    "hbl":          {"label": "BL hoogte", "unit": "m AGL", "decimals": 0},
    "hglider":      {"label": "Bruikbare hoogte", "unit": "m MSL", "decimals": 0},
    "experimental1":{"label": "Hlift 175fpm", "unit": "m MSL", "decimals": 0},
    "bltopvariab":  {"label": "BL top variabiliteit", "unit": "m", "decimals": 0},
    "bsratio":      {"label": "B/S ratio", "unit": "", "decimals": 1},
    "zsfclcl":      {"label": "Cu basis (sfc LCL)", "unit": "m MSL", "decimals": 0},
    "zsfclcldif":   {"label": "Cu potentie", "unit": "m", "decimals": 0},
    "zblcl":        {"label": "OD basis (BL CL)", "unit": "m MSL", "decimals": 0},
    "zblcldif":     {"label": "OD potentie", "unit": "m", "decimals": 0},
    "blcloudpct":   {"label": "BL bewolking", "unit": "%", "decimals": 0},
    "cfracl":       {"label": "Bewolking laag", "unit": "%", "decimals": 0},
    "cfracm":       {"label": "Bewolking midden", "unit": "%", "decimals": 0},
    "cfrach":       {"label": "Bewolking hoog", "unit": "%", "decimals": 0},
    "sfcsunpct":    {"label": "Zon", "unit": "%", "decimals": 0},
    "sfcwind0":     {"label": "Wind 10m", "unit": "m/s", "decimals": 1},
    "blwind":       {"label": "BL gem. wind", "unit": "m/s", "decimals": 1},
    "bltopwind":    {"label": "Wind BL top", "unit": "m/s", "decimals": 1},
    "blwindshear":  {"label": "BL windshear", "unit": "m/s", "decimals": 1},
    "wblmaxmin":    {"label": "BL max up/down", "unit": "cm/s", "decimals": 0},
    "zwblmaxmin":   {"label": "Hoogte max W", "unit": "m MSL", "decimals": 0},
    "sfctemp":      {"label": "Temp 2m", "unit": "°C", "decimals": 1},
    "sfcdewpt":     {"label": "Dauwpunt 2m", "unit": "°C", "decimals": 1},
    "cape":         {"label": "CAPE", "unit": "J/kg", "decimals": 0},
    "rain1":        {"label": "Neerslag 1h", "unit": "mm", "decimals": 1},
    "wrf=slp":      {"label": "Luchtdruk MSL", "unit": "hPa", "decimals": 1},
}

# Add pressure level params
for plev in [955, 899, 846, 795, 701, 616, 540]:
    PARAM_META[f"press{plev}"] = {"label": f"W {plev}hPa", "unit": "m/s", "decimals": 1}
    PARAM_META[f"press{plev}wspd"] = {"label": f"Wind {plev}hPa", "unit": "m/s", "decimals": 1}
    PARAM_META[f"press{plev}wdir"] = {"label": f"Richting {plev}hPa", "unit": "°", "decimals": 0}


def parse_data_file(filepath):
    """Parse a .data file and return (grid_info, data_2d).

    Returns:
        grid_info: dict with lat_min, lat_max, lon_min, lon_max, dlat, dlon, ny, nx
        data: 2D numpy array (ny, nx)
    """
    with open(filepath, "r") as f:
        lines = f.readlines()

    if len(lines) < 5:
        return None, None

    # Parse grid info from line 2 (or 3 — they're identical for LatLon)
    # Format: "... Proj= LatLon {dlat} {dlon} {lat_min} {lat_max} {lon_min} {lon_max}"
    grid_line = lines[1]

    proj_match = re.search(
        r'Proj=\s*LatLon\s+([\d.]+)\s+([\d.]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)',
        grid_line
    )
    idx_match = re.search(r'Indexs=\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)', grid_line)

    if not proj_match or not idx_match:
        return None, None

    dlat = float(proj_match.group(1))
    dlon = float(proj_match.group(2))
    lat_min = float(proj_match.group(3))
    lat_max = float(proj_match.group(4))
    lon_min = float(proj_match.group(5))
    lon_max = float(proj_match.group(6))
    nx = int(idx_match.group(2))
    ny = int(idx_match.group(4))

    grid_info = {
        "dlat": dlat, "dlon": dlon,
        "lat_min": lat_min, "lat_max": lat_max,
        "lon_min": lon_min, "lon_max": lon_max,
        "ny": ny, "nx": nx,
    }

    # Parse data (lines 4+)
    try:
        data_lines = lines[4:]
        data = np.loadtxt(data_lines)
        if data.shape != (ny, nx):
            # Try to reshape
            data = data.flatten()[:ny * nx].reshape(ny, nx)
    except Exception as e:
        print(f"  Warning: could not parse data from {filepath}: {e}", file=sys.stderr)
        return grid_info, None

    return grid_info, data


def find_nearest_idx(lat_site, lon_site, grid_info):
    """Find nearest (j, i) gridpoint for a site.

    The .data grid has lat going from lat_min to lat_max (south to north)
    since ICON-D2 is N->S but subsetted and possibly flipped.
    We need to check the actual data layout.
    """
    lat_min = grid_info["lat_min"]
    lat_max = grid_info["lat_max"]
    lon_min = grid_info["lon_min"]
    lon_max = grid_info["lon_max"]
    ny = grid_info["ny"]
    nx = grid_info["nx"]
    dlat = grid_info["dlat"]
    dlon = grid_info["dlon"]

    # Build lat/lon arrays
    # ICON-D2 regular grid: lat decreasing (N->S), so in the .data file
    # row 0 = northernmost latitude
    lat = np.linspace(lat_max, lat_min, ny)  # N->S
    lon = np.linspace(lon_min, lon_max, nx)

    j = int(np.argmin(np.abs(lat - lat_site)))
    i = int(np.argmin(np.abs(lon - lon_site)))

    actual_lat = lat[j]
    actual_lon = lon[i]

    return j, i, actual_lat, actual_lon


def extract_site_timeseries(out_dir, lat, lon, site_name="Site"):
    """Extract all parameters for all timesteps at a given lat/lon.

    Args:
        out_dir: Path to pipeline OUT directory containing .data files
        lat: Site latitude
        lon: Site longitude
        site_name: Human-readable site name

    Returns:
        dict suitable for JSON serialization
    """
    out_dir = Path(out_dir)

    # Find grid info from first available .data file
    sample = next(out_dir.glob("*.data"), None)
    if sample is None:
        print(f"Error: no .data files found in {out_dir}", file=sys.stderr)
        sys.exit(1)

    grid_info, _ = parse_data_file(sample)
    if grid_info is None:
        print(f"Error: could not parse grid info from {sample}", file=sys.stderr)
        sys.exit(1)

    j, i, actual_lat, actual_lon = find_nearest_idx(lat, lon, grid_info)
    print(f"Site: {site_name} ({lat:.4f}N, {lon:.4f}E)")
    print(f"Nearest gridpoint: ({actual_lat:.4f}N, {actual_lon:.4f}E) [j={j}, i={i}]")
    print(f"Grid: {grid_info['ny']}x{grid_info['nx']}, "
          f"dlat={grid_info['dlat']:.4f}, dlon={grid_info['dlon']:.4f}")

    # Extract values for each param × timestep
    timeseries = {}
    found_params = set()

    for param in METEOGRAM_PARAMS:
        values = []
        for ts in TIMESTEPS:
            # Try standard filename pattern
            fname = f"{param}.curr.{ts}lst.d2.data"
            fpath = out_dir / fname

            if not fpath.exists():
                values.append(None)
                continue

            _, data = parse_data_file(fpath)
            if data is None:
                values.append(None)
                continue

            val = float(data[j, i])

            # Handle missing values
            if val <= -999000 or not math.isfinite(val):
                values.append(None)
                continue

            # Apply inverse mult for wstar (stored as cm/s in .data, want m/s)
            meta = PARAM_META.get(param, {})
            mult = meta.get("mult", None)
            if mult:
                val = val * mult

            # Round
            decimals = meta.get("decimals", 1)
            val = round(val, decimals)
            if decimals == 0:
                val = int(val)

            values.append(val)
            found_params.add(param)

        timeseries[param] = values

    # Also try to get PFD (single-timestep files)
    for pfd_param in ["pfd_tot", "pfd_tot2", "pfd_tot3"]:
        # PFD might be at the last timestep or without timestep
        for pattern in [f"{pfd_param}.data", f"{pfd_param}.curr.1800lst.d2.data"]:
            fpath = out_dir / pattern
            if fpath.exists():
                _, data = parse_data_file(fpath)
                if data is not None:
                    val = float(data[j, i])
                    if val > -999000 and math.isfinite(val):
                        timeseries[pfd_param] = round(val, 1)
                        found_params.add(pfd_param)
                        break

    # Parse date/init from a .data file header
    date_info = {}
    sample_data_file = next(out_dir.glob("wstar.curr.*lst.d2.data"), None)
    if sample_data_file is None:
        sample_data_file = next(out_dir.glob("sfctemp.curr.*lst.d2.data"), None)
    if sample_data_file:
        with open(sample_data_file) as f:
            header_lines = [f.readline() for _ in range(4)]
        # Line 4: "Day= 2026 3 12 Thu ValidLST= 1300 CET ..."
        day_match = re.search(
            r'Day=\s*(\d+)\s+(\d+)\s+(\d+)\s+(\w+).*Init=\s*(\d+)',
            header_lines[3]
        )
        if day_match:
            date_info = {
                "year": int(day_match.group(1)),
                "month": int(day_match.group(2)),
                "day": int(day_match.group(3)),
                "weekday": day_match.group(4),
                "init_hour": int(day_match.group(5)),
            }

    # Get terrain height at site
    ter_val = None
    for pattern in ["wrf=HGT.curr.0800lst.d2.data", "wrf=HGT.curr.1200lst.d2.data"]:
        fpath = out_dir / pattern
        if fpath.exists():
            _, data = parse_data_file(fpath)
            if data is not None:
                ter_val = int(float(data[j, i]))
                break

    print(f"Found {len(found_params)} parameters with data")
    print(f"Parameters: {sorted(found_params)}")

    # Build output JSON
    result = {
        "site": {
            "name": site_name,
            "lat": round(actual_lat, 4),
            "lon": round(actual_lon, 4),
            "elevation_m": ter_val,
            "requested_lat": lat,
            "requested_lon": lon,
        },
        "model": {
            "name": "ICON-D2",
            "source": "DWD",
            "region": "NL2KMICOND2",
            "resolution_km": 2.2,
            **date_info,
        },
        "times": [f"{ts[:2]}:{ts[2:]}" for ts in TIMESTEPS],
        "parameters": {},
        "pfd": {},
    }

    # Add parameter timeseries
    for param, values in timeseries.items():
        if param in ["pfd_tot", "pfd_tot2", "pfd_tot3"]:
            if not isinstance(values, list):
                result["pfd"][param] = values
            continue

        meta = PARAM_META.get(param, {"label": param, "unit": "", "decimals": 1})
        result["parameters"][param] = {
            "label": meta["label"],
            "unit": meta["unit"],
            "values": values,
        }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Extract meteogram JSON from ICON-D2 pipeline .data files"
    )
    parser.add_argument("out_dir", help="Path to pipeline OUT directory")
    parser.add_argument("--lat", type=float, default=51.5675,
                        help="Site latitude (default: Gilze-Rijen)")
    parser.add_argument("--lon", type=float, default=4.9319,
                        help="Site longitude (default: Gilze-Rijen)")
    parser.add_argument("--name", default="Gilze-Rijen",
                        help="Site name")
    parser.add_argument("-o", "--output", default=None,
                        help="Output JSON file (default: stdout)")

    args = parser.parse_args()

    result = extract_site_timeseries(args.out_dir, args.lat, args.lon, args.name)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"\nWrote {args.output}")
    else:
        print("\n" + output_json)


if __name__ == "__main__":
    main()
