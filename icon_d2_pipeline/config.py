"""Configuration constants for the ICON-D2 soaring weather pipeline."""

REGION = "NL2KMICOND2"
RUN_MODEL = "icon-d2"

# Domain bounding box for Netherlands soaring area
NL_BBOX = {
    "lat_min": 49.0,
    "lat_max": 54.5,
    "lon_min": 2.0,
    "lon_max": 12.0,
}

# DWD open data base URL for ICON-D2
ICON_D2_BASE_URL = "https://opendata.dwd.de/weather/nwp/icon-d2/grib/"

# ICON-D2 has 65 model levels (66 half-levels for HHL)
ICON_D2_NUM_LEVELS = 65
ICON_D2_NUM_HALF_LEVELS = 66

# 22 half-hour timesteps from 07:30 to 18:00 local time
TIMESTEPS_LOCAL = [
    "0730", "0800", "0830", "0900", "0930", "1000", "1030", "1100",
    "1130", "1200", "1230", "1300", "1330", "1400", "1430", "1500",
    "1530", "1600", "1630", "1700", "1730", "1800",
]

# Physical constants
GRAVITY = 9.81  # m/s^2
RDCP = 0.286  # R_d / c_p (Poisson constant)
P_REF = 100000.0  # Reference pressure in Pa for potential temperature
T0 = 273.15  # 0 C in Kelvin

# BL drag coefficient for bsratio (from wrf2gm.ncl:108)
CDBL = 0.003

# Cloud water base criterion (from wrf2gm.ncl:109)
CWBASE_CRITERIA = 0.000010

# Max cloud base height in meters (equals 18000ft)
MAX_CWBASE_M = 5486.40

# Glider polars from XCSoar polar store
# https://github.com/XCSoar/XCSoar/blob/master/src/Polar/PolarStore.cpp
GLIDER_POLARS = {
    # LS-4 used for pfd_tot and pfd_tot2
    "LS-4": {
        "mdg": 361,  # MassDryGross (kg)
        "v1": 100, "w1": -0.69,
        "v2": 120, "w2": -0.87,
        "v3": 150, "w3": -1.44,
        "pilot_weight": 75,  # kg including chute
        "water_ballast": 0,  # kg
        "sink_rate_turn": 0.9,  # m/s
    },
    # ASG-29E (18m) used for pfd_tot3
    "ASG-29E": {
        "mdg": 400,
        "v1": 90, "w1": -0.499,
        "v2": 95.5, "w2": -0.510,
        "v3": 196.4, "w3": -2.12,
        "pilot_weight": 75,
        "water_ballast": 0,
        "sink_rate_turn": 0.9,
    },
}

# PFD weather corrections thresholds (from calc_funcs.ncl:677-679)
PFD_CU_CLOUDBASE_MIN_AGL = 600  # m - zero wstar if cu cloudbase AGL < this
PFD_BLUE_THERMAL_MIN_AGL = 800  # m - zero wstar if blue thermals AGL < this

# PFD simple (pfd_tot) hardcoded polar coefficients from calc_funcs.ncl pfd()
# These are NOT derived from the glider polar — they are the NCL reference values.
PFD_SIMPLE_A = -0.000302016415111608
PFD_SIMPLE_B = 0.0729181700942301
PFD_SIMPLE_C = -5.21488508245734
PFD_SIMPLE_SRIT = 1.15  # m/s — NCL hardcoded sink rate (not from glider polar)

# Pressure levels for output interpolation (hPa) — for press955..press540 params
PRESSURE_LEVELS = [955, 899, 846, 795, 701, 616, 540]

# DWD pressure levels available on regular-lat-lon grid (hPa)
# Used for downloading fi, relhum, omega
ICON_D2_PRESSURE_LEVELS_HPA = [1000, 975, 950, 850, 700, 600, 500, 400, 300, 250, 200]

# ICON-D2 GRIB variables to download
# 3D model-level variables (icosahedral grid — requires remapping to regular-lat-lon)
GRIB_3D_VARS = ["T", "QV", "QC", "P", "U", "V", "W"]

# 3D pressure-level variables (regular-lat-lon grid)
GRIB_PRESSURE_LEVEL_VARS = ["FI", "RELHUM", "OMEGA"]

# 2D single-level variables (regular-lat-lon grid)
GRIB_2D_VARS = [
    "T_2M", "TD_2M", "U_10M", "V_10M", "PS", "PMSL",
    "ASWDIR_S", "ASWDIFD_S", "TOT_PREC",
    "ASHFL_S", "ALHFL_S",
    "MH",       # Mixing layer height (PBL height) — replaces HPBL
    "CAPE_ML",  # CAPE (directly from ICON-D2, no need to compute)
    "CLCL",     # Low cloud cover (directly available, replaces cfrac calc)
    "CLCM",     # Mid cloud cover
    "CLCH",     # High cloud cover
]

# Time-invariant variables (only need forecast hour 0)
GRIB_INVARIANT_VARS = ["HSURF", "HHL", "FR_LAND"]

# Icosahedral grid coordinate files (needed for remapping model-level data)
GRIB_ICO_COORD_VARS = ["CLAT", "CLON"]

# Parameter list matching existing WRF pipeline output
# From rasp.run.parameters.NL4KMICON line 54
PARAMETER_LIST = [
    "sfctemp", "sfcsunpct", "hbl", "experimental1", "hglider",
    "bltopvariab", "wstar175", "bsratio", "sfcwind0", "blwind",
    "bltopwind", "blwindshear", "wblmaxmin", "zwblmaxmin",
    "zsfclcldif", "zsfclclmask", "zblcl", "zblcldif", "zblclmask",
    "sfcdewpt", "cape", "rain1", "cfracl", "cfracm", "cfrach",
    "press955", "press899", "press846", "press795", "press701",
    "press616", "press540", "wstar", "blcloudpct",
    "wrf=slp", "wrf=HGT",
    "pfd_tot", "pfd_tot2", "pfd_tot3",
]

# Parameters that produce data files (exclude display-only and special params)
# wstar175 is just wstar with different contour levels, same data
# wrf=slp -> outputs as mslpress, wrf=HGT -> outputs as terrain height

# Units and multipliers for metric output
# Internal calculations are in SI (m/s, K, Pa, m)
# .data files store values multiplied by these factors
PARAM_UNITS = {
    "wstar": {"unit": "cm/s", "mult": 100.0},
    "wstar175": {"unit": "cm/s", "mult": 100.0},
    "hbl": {"unit": "m", "mult": 1.0},
    "experimental1": {"unit": "m", "mult": 1.0},
    "hglider": {"unit": "m", "mult": 1.0},
    "bltopvariab": {"unit": "m", "mult": 1.0},
    "bsratio": {"unit": "nondim", "mult": 1.0},
    "sfcwind0": {"unit": "m/s", "mult": 1.0},
    "blwind": {"unit": "m/s", "mult": 1.0},
    "bltopwind": {"unit": "m/s", "mult": 1.0},
    "blwindshear": {"unit": "m/s", "mult": 1.0},
    "wblmaxmin": {"unit": "cm/s", "mult": 1.0},  # Fortran already returns cm/s
    "zwblmaxmin": {"unit": "m", "mult": 1.0},
    "zsfclcl": {"unit": "m", "mult": 1.0},
    "zsfclcldif": {"unit": "m", "mult": 1.0},
    "zsfclclmask": {"unit": "m", "mult": 1.0},
    "zblcl": {"unit": "m", "mult": 1.0},
    "zblcldif": {"unit": "m", "mult": 1.0},
    "zblclmask": {"unit": "m", "mult": 1.0},
    "sfctemp": {"unit": "C", "mult": 1.0},
    "sfcdewpt": {"unit": "C", "mult": 1.0},
    "sfcsunpct": {"unit": "%", "mult": 1.0},
    "cape": {"unit": "J/kg", "mult": 1.0},
    "rain1": {"unit": "mm", "mult": 1.0},
    "cfracl": {"unit": "%", "mult": 1.0},
    "cfracm": {"unit": "%", "mult": 1.0},
    "cfrach": {"unit": "%", "mult": 1.0},
    "blcloudpct": {"unit": "%", "mult": 1.0},
    "wrf=slp": {"unit": "mb", "mult": 1.0},
    "wrf=HGT": {"unit": "m", "mult": 1.0},
    "pfd_tot": {"unit": "km", "mult": 1.0},
    "pfd_tot2": {"unit": "km", "mult": 1.0},
    "pfd_tot3": {"unit": "km", "mult": 1.0},
}

# Add pressure level units
for plev in PRESSURE_LEVELS:
    PARAM_UNITS[f"press{plev}"] = {"unit": "m/s", "mult": 1.0}
