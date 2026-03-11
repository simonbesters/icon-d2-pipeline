"""Generate RASP-compatible PNG files (body, head, foot, side) for the web viewer.

Each parameter/timestep produces 4 PNGs:
- body.png: Colored data grid overlay (RGBA, positioned on Leaflet map)
- head.png: Title bar with parameter name, time, model info
- foot.png: Horizontal color scale bar
- side.png: Vertical color scale bar
"""

import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colormap: NCL BlAqGrYeOrReVi200 (exact values from NCAR/ncl)
# Blue(0-32) -> Cyan(33) -> Green(34-66) -> Yellow(67-99) ->
# Yellow(100) -> Orange(101-132) -> Red(133-166) -> Violet(167-199)
# ---------------------------------------------------------------------------
COLORMAP = np.array([
    [0,0,255],[0,8,255],[0,15,255],[0,23,255],[0,31,255],
    [0,39,255],[0,46,255],[0,54,255],[0,62,255],[0,70,255],
    [0,77,255],[0,85,255],[0,93,255],[0,100,255],[0,108,255],
    [0,116,255],[0,124,255],[0,131,255],[0,139,255],[0,147,255],
    [0,155,255],[0,162,255],[0,170,255],[0,178,255],[0,185,255],
    [0,193,255],[0,201,255],[0,209,255],[0,216,255],[0,224,255],
    [0,232,255],[0,240,255],[0,247,255],[0,255,255],[0,253,248],
    [0,250,240],[1,248,233],[1,246,226],[1,243,219],[1,241,211],
    [2,239,204],[2,237,197],[2,234,190],[2,232,182],[3,230,175],
    [3,227,168],[3,225,160],[3,223,153],[4,220,146],[4,218,139],
    [4,216,131],[4,214,124],[5,211,117],[5,209,110],[5,207,102],
    [5,204,95],[6,202,88],[6,200,80],[6,197,73],[6,195,66],
    [7,193,59],[7,191,51],[7,188,44],[7,186,37],[8,184,30],
    [8,181,22],[8,179,15],[15,181,15],[23,183,14],[30,186,14],
    [37,188,13],[44,190,13],[52,192,12],[59,195,12],[66,197,11],
    [73,199,11],[81,201,11],[88,204,10],[95,206,10],[102,208,9],
    [110,210,9],[117,213,8],[124,215,8],[132,217,8],[139,219,7],
    [146,221,7],[153,224,6],[161,226,6],[168,228,5],[175,230,5],
    [182,233,4],[190,235,4],[197,237,4],[204,239,3],[211,242,3],
    [219,244,2],[226,246,2],[233,248,1],[240,251,1],[248,253,0],
    [255,255,0],[255,252,0],[255,250,0],[255,247,0],[255,244,0],
    [255,241,0],[255,239,0],[255,236,0],[255,233,0],[255,230,0],
    [255,228,0],[255,225,0],[255,222,0],[255,220,0],[255,217,0],
    [255,214,0],[255,211,0],[255,209,0],[255,206,0],[255,203,0],
    [255,200,0],[255,198,0],[255,195,0],[255,192,0],[255,190,0],
    [255,187,0],[255,184,0],[255,181,0],[255,179,0],[255,176,0],
    [255,173,0],[255,170,0],[255,168,0],[255,165,0],[255,160,0],
    [255,155,0],[255,150,0],[255,145,0],[255,140,0],[255,135,0],
    [255,130,0],[255,125,0],[255,120,0],[255,115,0],[255,110,0],
    [255,105,0],[255,100,0],[255,95,0],[255,90,0],[255,85,0],
    [255,80,0],[255,75,0],[255,70,0],[255,65,0],[255,60,0],
    [255,55,0],[255,50,0],[255,45,0],[255,40,0],[255,35,0],
    [255,30,0],[255,25,0],[255,20,0],[255,15,0],[255,10,0],
    [255,5,0],[255,0,0],[250,0,4],[245,0,8],[240,0,12],
    [235,0,16],[230,0,21],[224,0,25],[219,0,29],[214,0,33],
    [209,0,37],[204,0,41],[199,0,45],[194,0,49],[189,0,54],
    [184,0,58],[179,0,62],[174,0,66],[168,0,70],[163,0,74],
    [158,0,78],[153,0,82],[148,0,87],[143,0,91],[138,0,95],
    [133,0,99],[128,0,103],[123,0,107],[118,0,111],[112,0,115],
    [107,0,120],[102,0,124],[97,0,128],[92,0,132],[87,0,136],
], dtype=np.uint8)

# PFD custom colormap (from pfd.rgb)
_PFD_COLORS = np.array([
    [254, 254, 254], [254, 198, 254], [252, 100, 252],
    [127, 147, 226], [46, 93, 229], [0, 153, 0],
    [87, 252, 0], [255, 233, 0], [240, 130, 0], [174, 23, 0],
], dtype=np.uint8)

# ---------------------------------------------------------------------------
# Contour level definitions per parameter
# (min, max, step) — if min==max==0, auto-scale from data
# ---------------------------------------------------------------------------
CONTOUR_PARAMS = {
    "wstar":        (25, 525, 25),
    "wstar175":     (25, 525, 25),
    "hbl":          (200, 3200, 200),
    "experimental1": (0, 0, 200),
    "hglider":      (0, 0, 200),
    "bltopvariab":  (0, 0, 200),
    "bsratio":      (1, 10, 1),
    "sfcwind0":     (0, 0, 2),
    "blwind":       (0, 0, 2),
    "bltopwind":    (0, 0, 2),
    "blwindshear":  (2, 32, 2),
    "wblmaxmin":    (0, 0, 50),
    "zwblmaxmin":   (0, 0, 200),
    "sfctemp":      (0, 0, 1),
    "sfcdewpt":     (0, 0, 1),
    "sfcsunpct":    (5, 100, 5),
    "cape":         (0, 0, 100),
    "rain1":        (0, 0, 1),
    "blcloudpct":   (5, 100, 5),
    "cfracl":       (5, 100, 5),
    "cfracm":       (5, 100, 5),
    "cfrach":       (5, 100, 5),
    "zsfclcl":      (0, 0, 500),
    "zsfclcldif":   (0, 0, 500),
    "zsfclclmask":  (0, 0, 500),
    "zblcl":        (0, 0, 500),
    "zblcldif":     (0, 0, 500),
    "zblclmask":    (0, 0, 500),
    "wrf=slp":      (0, 0, 2),
    "wrf=HGT":      (0, 0, 100),
    "pfd_tot":      (100, 1000, 100),
    "pfd_tot2":     (100, 1000, 100),
    "pfd_tot3":     (100, 1000, 100),
}
# Pressure level params
for _p in [955, 899, 846, 795, 701, 616, 540]:
    CONTOUR_PARAMS[f"press{_p}"] = (0, 0, 2)
    CONTOUR_PARAMS[f"press{_p}wdir"] = (0, 360, 30)
    CONTOUR_PARAMS[f"press{_p}wspd"] = (0, 0, 2)

# Parameter display names
PARAM_TITLES = {
    "wstar": "Thermal Updraft Velocity (W*)",
    "wstar175": "Thermal Updraft Velocity (W*)",
    "hbl": "Height of BL Top",
    "experimental1": "Thermal Height (Hcrit)",
    "hglider": "Thermalling Height",
    "bltopvariab": "BL Top Variability",
    "bsratio": "Buoyancy/Shear Ratio",
    "sfcwind0": "Surface Wind",
    "blwind": "BL Avg. Wind",
    "bltopwind": "Wind at BL Top",
    "blwindshear": "BL Wind Shear",
    "wblmaxmin": "BL Max. Up/Down Motion",
    "zwblmaxmin": "Height of BL Max. Up/Down",
    "sfctemp": "Surface Temperature",
    "sfcdewpt": "Surface Dewpoint",
    "sfcsunpct": "Normalized Sfc. Sun",
    "cape": "CAPE",
    "rain1": "Precipitation",
    "blcloudpct": "BL Cloud Cover",
    "cfracl": "Low Cloud Cover",
    "cfracm": "Mid Cloud Cover",
    "cfrach": "High Cloud Cover",
    "zsfclcl": "Cu Cloudbase (Sfc.LCL)",
    "zsfclcldif": "OD Cloudbase Diff.",
    "zsfclclmask": "Cu Cloudbase where Cu",
    "zblcl": "OD Cloudbase (BL CL)",
    "zblcldif": "OD Cloudbase Diff.",
    "zblclmask": "OD Cloudbase where OD",
    "wrf=slp": "MSL Pressure",
    "wrf=HGT": "Terrain Height",
    "pfd_tot": "Pot. Flight Distance (LS-4)",
    "pfd_tot2": "Pot. Flight Distance (LS-4 v2)",
    "pfd_tot3": "Pot. Flight Distance (ASG-29E)",
}

# Units for display
PARAM_DISPLAY_UNITS = {
    "wstar": "cm/sec", "wstar175": "cm/sec",
    "hbl": "m MSL", "experimental1": "m MSL", "hglider": "m MSL",
    "bltopvariab": "m", "bsratio": "", "sfcwind0": "m/s",
    "blwind": "m/s", "bltopwind": "m/s", "blwindshear": "m/s",
    "wblmaxmin": "cm/s", "zwblmaxmin": "m",
    "sfctemp": "°C", "sfcdewpt": "°C", "sfcsunpct": "%",
    "cape": "J/kg", "rain1": "mm",
    "blcloudpct": "%", "cfracl": "%", "cfracm": "%", "cfrach": "%",
    "zsfclcl": "m MSL", "zsfclcldif": "m",
    "zsfclclmask": "m MSL", "zblcl": "m MSL",
    "zblcldif": "m", "zblclmask": "m MSL",
    "wrf=slp": "hPa", "wrf=HGT": "m",
    "pfd_tot": "km", "pfd_tot2": "km", "pfd_tot3": "km",
}

# ---------------------------------------------------------------------------
# Font loading
# ---------------------------------------------------------------------------
_font_cache = {}

def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Get a font at the given size, with fallback to default."""
    if size in _font_cache:
        return _font_cache[size]
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        try:
            font = ImageFont.truetype(path, size)
            _font_cache[size] = font
            return font
        except (OSError, IOError):
            continue
    font = ImageFont.load_default()
    _font_cache[size] = font
    return font


# ---------------------------------------------------------------------------
# Contour level computation
# ---------------------------------------------------------------------------
def _compute_levels(param_name: str, data: np.ndarray, mult: float) -> tuple:
    """Compute contour levels and colors for a parameter.

    Returns: (levels, colors, unit_str, is_fixed)
        levels: 1D array of level boundaries
        colors: (N, 3) uint8 array of RGB colors for each bin
        unit_str: display unit string
        is_fixed: whether this is a fixed or auto scale
    """
    scaled = data * mult
    # Treat -999999 fill values as NaN so they don't affect auto-scaling
    scaled = np.where(scaled <= -999000, np.nan, scaled)
    cp = CONTOUR_PARAMS.get(param_name, (0, 0, 0))
    cmin, cmax, step = cp

    is_pfd = param_name.startswith("pfd_tot")

    if cmin < cmax and step > 0:
        # Fixed scale
        levels = np.arange(cmin, cmax + step * 0.01, step)
        is_fixed = True
    else:
        # Auto-scale from data
        vmin = float(np.nanmin(scaled))
        vmax = float(np.nanmax(scaled))
        if step <= 0:
            step = max(1, int((vmax - vmin) / 20))
        # Nice rounding
        vmin = np.floor(vmin / step) * step
        vmax = np.ceil(vmax / step) * step
        if vmin >= vmax:
            vmax = vmin + step
        levels = np.arange(vmin, vmax + step * 0.01, step)
        is_fixed = False

    # Limit to 26 levels max
    if len(levels) > 26:
        new_step = step * max(1, len(levels) // 26)
        levels = np.arange(levels[0], levels[-1] + new_step * 0.01, new_step)

    n_bins = max(len(levels) - 1, 1)

    if is_pfd:
        # PFD uses custom colormap
        colors = _PFD_COLORS[:n_bins] if n_bins <= len(_PFD_COLORS) else \
            _PFD_COLORS[np.linspace(0, len(_PFD_COLORS) - 1, n_bins).astype(int)]
    else:
        # Sample from BlAqGrYeOrReVi200
        indices = np.linspace(2, len(COLORMAP) - 1, n_bins).astype(int)
        colors = COLORMAP[indices]

    unit_str = PARAM_DISPLAY_UNITS.get(param_name, "")

    return levels, colors, unit_str, is_fixed


# ---------------------------------------------------------------------------
# Body PNG rendering
# ---------------------------------------------------------------------------
def render_body(data: np.ndarray, levels: np.ndarray,
                colors: np.ndarray) -> Image.Image:
    """Render the data grid as a colored RGBA image.

    Args:
        data: 2D array (ny, nx) of values (already scaled by mult).
        levels: 1D array of contour level boundaries.
        colors: (N, 3) array of RGB colors for each bin.

    Returns:
        PIL Image in RGBA mode.
    """
    ny, nx = data.shape
    # Mask NaN / fill values
    nodata = np.isnan(data) | (data <= -999000)
    clean = np.where(nodata, 0, data)

    # Digitize: map each value to a bin index
    bin_idx = np.digitize(clean, levels) - 1
    bin_idx = np.clip(bin_idx, 0, len(colors) - 1)

    # Build RGB image
    rgb = colors[bin_idx]  # (ny, nx, 3)

    # Flip vertically: data row 0 = south, image row 0 = top (north)
    rgb = rgb[::-1]
    nodata = nodata[::-1]

    # Create RGBA — transparent where no data
    rgba = np.zeros((ny, nx, 4), dtype=np.uint8)
    rgba[:, :, :3] = rgb
    rgba[:, :, 3] = np.where(nodata, 0, 255)

    return Image.fromarray(rgba, "RGBA")


# ---------------------------------------------------------------------------
# Head PNG rendering (title bar)
# ---------------------------------------------------------------------------
def render_head(param_name: str, valid_dt, forecast_str: str,
                init_hour: int, tz_id: str,
                width: int = 1600, height: int = 137) -> Image.Image:
    """Render the title bar PNG."""
    img = Image.new("L", (width, height), 255)  # white background, grayscale
    draw = ImageDraw.Draw(img)

    title = PARAM_TITLES.get(param_name, param_name)
    day_name = valid_dt.strftime("%a").upper()
    date_str = valid_dt.strftime("%-d %b %Y")
    local_time = valid_dt.strftime("%H%M")
    utc_hour = valid_dt.hour - (1 if tz_id == "CET" else 2)
    utc_str = f"{utc_hour:02d}00z"

    line1 = title
    line2 = f"Valid {local_time} {tz_id} ({utc_str}) {day_name} {date_str} [{forecast_str}hrFcst@{init_hour:02d}00z]"
    line3 = "ICON-D2 2.2km direct pipeline"

    font_large = _get_font(28)
    font_med = _get_font(20)
    font_small = _get_font(16)

    # Center text
    y = 10
    for text, font in [(line1, font_large), (line2, font_med), (line3, font_small)]:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((width - tw) // 2, y), text, fill=0, font=font)
        y += bbox[3] - bbox[1] + 8

    return img


# ---------------------------------------------------------------------------
# Foot PNG rendering (horizontal colorbar)
# ---------------------------------------------------------------------------
def render_foot(levels: np.ndarray, colors: np.ndarray,
                unit_str: str, is_fixed: bool,
                width: int = 1600, height: int = 96) -> Image.Image:
    """Render the horizontal color scale bar."""
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    n_bins = len(colors)
    font = _get_font(14)
    font_unit = _get_font(16)

    # Layout
    margin_x = 90
    bar_y = 10
    bar_h = 30
    bar_w = width - 2 * margin_x
    cell_w = bar_w / n_bins

    # Draw color cells
    for i in range(n_bins):
        x0 = int(margin_x + i * cell_w)
        x1 = int(margin_x + (i + 1) * cell_w)
        color = tuple(colors[i])
        draw.rectangle([x0, bar_y, x1, bar_y + bar_h], fill=color, outline=color)

    # Draw border
    draw.rectangle([margin_x, bar_y, margin_x + bar_w, bar_y + bar_h],
                    outline=(0, 0, 0))

    # Labels at level boundaries
    label_y = bar_y + bar_h + 4
    max_labels = min(len(levels), 30)
    skip = max(1, len(levels) // max_labels)
    for i in range(0, len(levels), skip):
        x = int(margin_x + i * cell_w)
        val = levels[i]
        label = f"{val:g}" if val == int(val) else f"{val:.1f}"
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        draw.text((x - tw // 2, label_y), label, fill=(0, 0, 0), font=font)

    # Unit labels
    scale_text = "FIXED\nSCALE" if is_fixed else "SCALE"
    unit_text = f"[{unit_str}]" if unit_str else ""

    # Left unit
    draw.text((5, bar_y), scale_text, fill=(0, 0, 0), font=font)
    if unit_str:
        draw.text((5, label_y + 20), unit_text, fill=(0, 0, 0), font=font_unit)

    # Right unit
    bbox_s = draw.textbbox((0, 0), scale_text, font=font)
    draw.text((width - bbox_s[2] - 5, bar_y), scale_text, fill=(0, 0, 0), font=font)
    if unit_str:
        bbox_u = draw.textbbox((0, 0), unit_text, font=font_unit)
        draw.text((width - bbox_u[2] - 5, label_y + 20), unit_text,
                   fill=(0, 0, 0), font=font_unit)

    return img


# ---------------------------------------------------------------------------
# Side PNG rendering (vertical colorbar)
# ---------------------------------------------------------------------------
def render_side(levels: np.ndarray, colors: np.ndarray,
                unit_str: str, is_fixed: bool,
                width: int = 144, height: int = 1600) -> Image.Image:
    """Render the vertical color scale bar."""
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    n_bins = len(colors)
    font = _get_font(14)
    font_unit = _get_font(13)

    # Layout — bar in center, labels on right
    margin_y = 80
    bar_x = 40
    bar_w = 30
    bar_h = height - 2 * margin_y
    cell_h = bar_h / n_bins

    # Draw color cells (bottom = low, top = high)
    for i in range(n_bins):
        y0 = int(margin_y + (n_bins - 1 - i) * cell_h)
        y1 = int(margin_y + (n_bins - i) * cell_h)
        color = tuple(colors[i])
        draw.rectangle([bar_x, y0, bar_x + bar_w, y1], fill=color, outline=color)

    # Border
    draw.rectangle([bar_x, margin_y, bar_x + bar_w, margin_y + bar_h],
                    outline=(0, 0, 0))

    # Labels
    label_x = bar_x + bar_w + 5
    max_labels = min(len(levels), 30)
    skip = max(1, len(levels) // max_labels)
    for i in range(0, len(levels), skip):
        y = int(margin_y + (n_bins - i) * cell_h)
        val = levels[i]
        label = f"{val:g}" if val == int(val) else f"{val:.1f}"
        bbox = draw.textbbox((0, 0), label, font=font)
        th = bbox[3] - bbox[1]
        draw.text((label_x, y - th // 2), label, fill=(0, 0, 0), font=font)

    # Unit label top and bottom
    scale_text = "FIXED" if is_fixed else ""
    unit_text = unit_str if unit_str else ""
    header = f"{scale_text}\n{unit_text}\nSCALE" if scale_text else f"{unit_text}\nSCALE"

    for ty in [10, height - 70]:
        for li, line in enumerate(header.strip().split("\n")):
            bbox = draw.textbbox((0, 0), line, font=font_unit)
            tw = bbox[2] - bbox[0]
            draw.text(((width - tw) // 2, ty + li * 18), line,
                       fill=(0, 0, 0), font=font_unit)

    return img


# ---------------------------------------------------------------------------
# Public API: generate all PNGs for one parameter/timestep
# ---------------------------------------------------------------------------
def write_pngs(data: np.ndarray, param_name: str, ts_local: str,
               out_dir: Path, valid_dt, forecast_str: str,
               init_hour: int, tz_id: str, mult: float = 1.0):
    """Generate body/head/foot/side PNGs for a parameter at one timestep.

    Args:
        data: 2D array of parameter values (SI units).
        param_name: Parameter code (e.g. "wstar").
        ts_local: Local time string (e.g. "1200").
        out_dir: Output directory.
        valid_dt: Valid datetime.
        forecast_str: Forecast hour string.
        init_hour: Model init hour.
        tz_id: Timezone ID ("CET" or "CEST").
        mult: Unit multiplier (e.g. 100 for wstar m/s → cm/s).
    """
    # Skip auxiliary fields
    if param_name.endswith("_u") or param_name.endswith("_v"):
        return

    scaled = data * mult
    levels, colors, unit_str, is_fixed = _compute_levels(param_name, data, mult)

    base = f"{param_name}.curr.{ts_local}lst.d2"

    # Body
    body = render_body(scaled, levels, colors)
    body.save(out_dir / f"{base}.body.png", optimize=True)

    # Head
    head = render_head(param_name, valid_dt, forecast_str, init_hour, tz_id)
    head.save(out_dir / f"{base}.head.png", optimize=True)

    # Foot
    foot = render_foot(levels, colors, unit_str, is_fixed)
    foot.save(out_dir / f"{base}.foot.png", optimize=True)

    # Side
    side = render_side(levels, colors, unit_str, is_fixed)
    side.save(out_dir / f"{base}.side.png", optimize=True)
