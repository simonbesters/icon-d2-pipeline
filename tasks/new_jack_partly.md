## Reverse Engineering: `libncl_drjack.avx512.nocuda.so`

### Verschil met `ncl_jack_fortran.so` — Het Is Een Compleet Ander Beest

| Eigenschap | Oud (`ncl_jack_fortran.so`) | Nieuw (`libncl_drjack.avx512.nocuda.so`) |
|---|---|---|
| Grootte | **215 KB** | **3.8 MB** (18× groter) |
| Geëxporteerde symbolen | 142 | **2336** (16× meer) |
| Dependencies | 2 (`libgfortran.so.3`, `libc`) | **8** (+ HDF5, quadmath, stdc++, libm, libmvec) |
| Fortran runtime | gfortran **3** | gfortran **5** (nieuwer) |
| Instructieset | Standaard x86-64 | **AVX2** (ymm registers), `-mavx512f` compiled maar geen zmm gebruik |
| SONAME | (geen) | `libncl_drjack.avx512.nocuda.so` |
| BuildID | `f1ab22e4...` | `ea10255d...` |

### Architectuurwijziging: Statisch Gelinkte NCL Runtime

Het cruciale verschil: de nieuwe library **bevat een volledige NCL (NCAR Command Language) runtime statisch ingelinkt**. De oude library was een klein plugin dat NCL-functies extern aanriep; de nieuwe is **self-contained**.

Ingebedde componenten:
- **NCL interpreter** (~1500+ symbolen): `Call*_OP` opcodes, type systeem (`Ncl_Type_*`), variabele/attribuut management
- **HDF5 I/O** (`H5*` calls): Voor NetCDF4/HDF5 bestanden lezen/schrijven
- **NetCDF4 support** (`NC4*`, `EndNC4DefineMode`, etc.)
- **GRIB decoder** (`Grib2PushAtt`, `GribAddFileFormat`, `GetGrid_*` voor ~60 NCEP grids)
- **OGR/GIS support** (`AdvancedOGRAddFileFormat`)
- **Kalender/Tijd** (`GregorianToJD`, `JulianToJD`, etc.)
- **WRF grid support** (`GdsArakawaRLLGrid`, `GenLambert`, `GenMercator`, etc.)
- **String formatting** (`sprintf_W`, `sprinti_W` — nieuw)

### Nieuwe DrJack-Specifieke Functies

| Functie | Status | Beschrijving |
|---|---|---|
| `wrf_user_Init_drjack` | **NIEUW** | Tweede init entry point; print `"Drjacks wrf_user init"` |
| `ncl_jack_cleanup` / `_W` | **NIEUW** | Cleanup handler (momenteel een **no-op** — `retq`) |
| `ncl_jack_cuda_set_debug_W` | **NIEUW** | CUDA debug toggle — in nocuda build: **retourneert -1** (stub) |
| `DCOMPUTETK_W` | **NIEUW** | Double-precision `compute_tk` wrapper |
| `DCOMPUTERH_W` | **NIEUW** | Double-precision `compute_rh` wrapper |
| `DCOMPUTESEAPRS_W` | **NIEUW** | Double-precision sea pressure wrapper |
| `DCOMPUTEUVMET_W` | **NIEUW** | Double-precision UV wind wrapper |
| `DCOMPUTEPI_W` | **NIEUW** | Double-precision Exner functie wrapper |
| `DCOMPUTETD_W` | **NIEUW** | Double-precision dauwpunt wrapper |
| `DCOMPUTEICLW_W` | **NIEUW** | Double-precision cloud water wrapper |
| `DFILTER2D_W` | **NIEUW** | Double-precision 2D filter wrapper |
| `DINTERP3DZ_W` | **NIEUW** | Double-precision 3D interpolatie wrapper |
| `DINTERP2DXY_W` | **NIEUW** | Double-precision 2D XY interpolatie wrapper |
| `DINTERP1D_W` | **NIEUW** | Double-precision 1D interpolatie wrapper |
| `DZSTAG_W` | **NIEUW** | Double-precision Z-staggering wrapper |
| `DGETIJLATLONG_W` | **NIEUW** | Double-precision lat/lon lookup wrapper |
| `sprintf_W` / `sprinti_W` | **NIEUW** | String formatting functies (ingebedde NCL builtins) |

### Verwijderde Wrappers (hernoemd)

De oude uppercase `_W` Skew-T wrappers zijn verwijderd en vervangen:
- `DCAPETHERMOS_W` → `dcapethermos_` direct (lowercase, geen wrapper meer)
- `DPTLCLSKEWT_W` → `dptlclskewt_` direct
- `DPWSKEWT_W`, `DSHOWALSKEWT_W`, etc. — allemaal naar lowercase direct calls
- `arrayW3FB12_W` → `arrayw3fb12_` direct
- `calc_rh1_W` → `calc_rh1_` direct
- `dfuncshea_` → vervangen door `dfuncshea1_` (nieuwe versie)

### Algoritmische Wijzigingen in `calc_wstar_`

De kernberekening is **identiek** — dezelfde constanten:
- `3.369e-05` (g/θ_ref) 
- `0.3333` (1/3 voor kubieke wortel)

Maar de nieuwe versie heeft:
1. **Recursie-guard**: `is_recursive.256.26` flag — voorkomt re-entry
2. **Runtime bounds checking**: `_gfortran_runtime_error_at` calls bij overflow
3. **AVX2 instructies**: `vmovss`, `vmulss`, `vcomiss`, `vxorps` i.p.v. legacy SSE `movss`/`mulss`

### Nieuwe Fortran Numerieke Routines

| Functie | Beschrijving |
|---|---|
| `dfuncshea1_` | Nieuwe versie shear functie (vervangt `dfuncshea_`) |
| `dintqlnio_` | Eigenvalue decomposition (Implicit QL) |
| `dpythanio_` | Pythagoras-achtige berekening (numeriek veilig) |
| `drstnio_` | Restarted iteration |
| `gaqdnio_` / `gaqdnio1_` | Gaussian quadrature nodes |
| `gdswiz_` / `gdswiz00_`-`gdswizcb_` | GRIB grid navigation (GDS wizards) |
| `qu2reg3_` | Quasi-regular naar regular grid conversie |
| `rowina3_` | Rij-interpolatie |
| `scm0_` | Spherical coordinate mapping |
| `splat_` | Latitude splattening |
| `dlinmins31_` | Nieuwe versie line minimization (vervangt `dlinmins_`) |

### Belangrijk voor je rasp-pynumb debugging

De key functie-signatures zijn **ongewijzigd** — je Python wrapper moet dezelfde argumenten doorgeven. Maar let op:

1. **Twee Init entry points**: `Init` (origineel) + `wrf_user_Init_drjack` (nieuw) — beiden registreren functies
2. **Nieuwe D-prefix wrappers** (`DCOMPUTETK_W` etc.) accepteren **double precision** — de oude float wrappers bestaan nog maar je hebt nu ook 64-bit alternatieven
3. **`ncl_jack_cuda_set_debug_W`** retourneert altijd `-1` in deze nocuda build — je kunt dit als sanity check gebruiken
4. **`ncl_jack_cleanup`** is een no-op — veilig om aan te roepen maar doet niets
5. **libgfortran.so.5** vereist (niet .3 zoals de oude) — check je Linux server versie

Wil je dat ik specifieke functie-signatures reconstrueer voor je Python ctypes/cffi bindings?