## Reverse Engineering Analyse: `ncl_jack_fortran.so`

### Identificatie

Dit is **Dr. Jack's BLIPMAP (Boundary Layer Information Prediction MAP) NCL Plugin** — een shared library plugin voor **NCAR Command Language (NCL)** die meteorologische berekeningen uitvoert specifiek gericht op **zweefvliegen/paragliding soaring forecasts** op basis van **WRF (Weather Research and Forecasting)** modeloutput.

| Eigenschap | Waarde |
|---|---|
| Formaat | ELF 64-bit LSB shared object, x86-64 |
| Grootte | 215 KB |
| Stripped | Nee (alle symbolen aanwezig) |
| BuildID | `f1ab22e4462e2bb6d3725148230e8bfa44ce5498` |
| Taal | **Fortran** (gecompileerd met gfortran) |
| Dependencies | `libgfortran.so.3`, `libc.so.6` |
| Bronbestand | `ncl_jack_fortran.f` (single source file) |

---

### Architectuur

De library volgt het NCL externe-library plugin patroon:

```
Init()
  ├── NewArgs(7)                    # allocate argument templates
  ├── SetArgTemplate(...)           # define parameter types (float, integer, double)
  ├── NclRegisterFunc(name, wrapper_fn, args)    # register functions
  └── NclRegisterProc(name, wrapper_fn, args)    # register procedures

Elke geregistreerde functie heeft een *_W (wrapper) en een _ (Fortran implementatie):
  calc_wstar_W  → roept calc_wstar_ aan  (C↔Fortran bridge)
```

---

### 50 Geregistreerde NCL Functies

Gegroepeerd per domein:

#### Boundary Layer (BL) Soaring Parameters
| Functie | Beschrijving (gereconstrueerd) |
|---|---|
| `CALC_WSTAR` | **Convectieve snelheidsschaal W*** — dé kernparameter voor thermieksterkte |
| `CALC_HCRIT` | Kritische hoogte voor thermieken |
| `CALC_HLIFT` | Verwachte liftbare hoogte |
| `CALC_BLAVG` | Gemiddelde over de boundary layer |
| `CALC_BLMAX` | Maximum waarde in de BL |
| `CALC_BLCLHEIGHT` | BL convectieve wolkenhoogte |
| `CALC_BLCLOUDBASE` | Wolkenbasis hoogte (BL top) |
| `CALC_CLOUDBASE` | Absolute wolkenbasis |
| `CALC_SFCLCLHEIGHT` | Oppervlakte LCL (Lifting Condensation Level) hoogte |
| `CALC_WBLMAXMIN` | BL wind max/min berekening |
| `CALC_BLWINDDIFF` | Windverschil over de BL |
| `CALC_BLTOPWIND` | Wind aan BL top |
| `CALC_BLTOP_POTTEMP_VARIABILITY` | Potentiële temperatuur variabiliteit aan BL top |
| `CALC_BLINTEG_MIXRATIO` | BL-geïntegreerde mengverhouding |
| `CALC_ABOVEBLINTEG_MIXRATIO` | Boven-BL geïntegreerde mengverhouding |
| `CALC_QCBLHF` | Cloud water BL height fraction |
| `CALC_SUBGRID_BLCLOUDPCT_GRADS` | Sub-grid bewolkingspercentage (GrADS methode) |
| `CALC_SUBGRID_BLCLOUDPCT_GFDLETA` | Sub-grid bewolkingspercentage (GFDL/Eta methode) |

#### Thermodynamische Berekeningen (Skew-T)
| Functie | Beschrijving |
|---|---|
| `DCAPETHERMOS` | **CAPE** (Convective Available Potential Energy) berekening |
| `CALC_CAPE2D` | 2D CAPE veld berekening |
| `DSHOWALSKEWT` | **Showalter Index** — stabiliteitsindex |
| `DPWSKEWT` | Precipitable Water (neerslag water) |
| `DPTLCLSKEWT` | Druk/Temperatuur aan het LCL |
| `DSATLFTSKEWT` | Saturatie-adiabatische lift |
| `DTDASKEWT` | Dauwpunt temperatuur |
| `DTMRSKEWT` | Mengverhouding |
| `DSKEWTY` / `DSKEWTX` | Skew-T diagram coördinaten |

#### WRF Model Utilities
| Functie | Beschrijving |
|---|---|
| `COMPUTE_TK` / `COMPUTE_TK_2D` | Temperatuur (K) uit θ en druk: **T = θ × (P/100000)^0.286** |
| `COMPUTE_PI` | Exner functie (π = Cp × (P/P0)^(R/Cp)) |
| `COMPUTE_RH` / `CALC_RH1` | Relatieve vochtigheid |
| `COMPUTE_TD` / `COMPUTE_TD_2D` | Dauwpunt temperatuur |
| `COMPUTE_SEAPRS` | Zeeniveau druk reductie |
| `COMPUTE_UVMET` | U/V wind naar meteorologisch coördinatenstelsel |
| `COMPUTE_ICLW` | Integrated Cloud Liquid Water |

#### Interpolatie & Grid
| Functie | Beschrijving |
|---|---|
| `INTERP_3DZ` | 3D interpolatie naar z-niveaus |
| `INTERP_2D_XY` | 2D XY interpolatie |
| `INTERP_1D` | 1D interpolatie |
| `Z_STAG` | Z-staggering (WRF Arakawa-C grid) |
| `CALC_LATLON` | Lat/lon berekening uit grid |
| `GET_IJ_LAT_LONG` | Grid i,j indices voor lat/lon |

#### I/O & Utilities
| Functie | Beschrijving |
|---|---|
| `READ_BLIP_DATA_SIZE` | Lees BLIPMAP bestandsgrootte |
| `READ_BLIP_DATA_INFO` | Lees BLIPMAP header (Lambert/LatLon projectie) |
| `READ_BLIP_DATAFILE` | Lees BLIPMAP databestand |
| `OUTPUT_MAPDATAFILE` | Schrijf kaartdata |
| `ARRAYW3FB12` | WRF W3FB12 map projectie routine |
| `CALC_SFCSUNPCT` | Oppervlakte zonpercentage (schaduw/zon) |
| `UV2WDWS_4LATLON` / `WDWS2UV_4LATLON` | U/V ↔ windrichting/snelheid conversie |
| `FILTER2D` | 2D smoothing filter |

---

### Gereconstrueerde Kernalgoritmen

#### `calc_wstar_` — Convectieve snelheidsschaal (W*)

```fortran
! W* = (g/θ × H × Qsfc)^(1/3)
! Cruciaal voor thermieksterkte-voorspelling
subroutine calc_wstar(hfx, pblh, result, isize, jsize)
  do j = 1, jsize
    do i = 1, isize
      if (hfx(i,j) > 0.0 .AND. pblh(i,j) > 0.0) then
        ! constante ≈ g/θ_ref = 9.81/300 ≈ 0.0000337 (matches 3.369e-05)
        result(i,j) = (hfx(i,j) * pblh(i,j) * 3.369e-05) ** 0.3333
      else
        result(i,j) = 0.0
      endif
    enddo
  enddo
end
```

#### `compute_tk_` — Temperatuur uit potentiële temperatuur

```fortran
! T = θ × (P / 100000)^(R/Cp)
! 100000 Pa = reference pressure, R/Cp ≈ 0.286
subroutine compute_tk(pressure, theta, tk, nx, ny, nz)
  do k = 1, nz
    do j = 1, ny
      do i = 1, nx
        tk(i,j,k) = theta(i,j,k) * (pressure(i,j,k) / 100000.0) ** 0.286
      enddo
    enddo
  enddo
end
```

#### `ptlcl_` — Lifted Condensation Level

```fortran
! Bolton (1980) formule voor LCL
subroutine ptlcl(p, t, td, tlcl, plcl)
  ! constanten: 0.001571, 0.212, 0.000436, 273.16, 3.4978
  tlcl = t - (0.001571*t + 0.212 - 0.000436*td) * (td - t)
  plcl = p * ((tlcl + 273.16) / (t + 273.16)) ** 3.4978
end
```

#### `radconst_` — Zonnestralingsconstanten

```fortran
! Berekent solar declination & radiation
! Constanten: 23.5° (axiale tilt), 24h, 80d (equinox offset),
!   365d, solar constant = 1370 W/m²
subroutine radconst(decl, solcon, lat, julian_day, gmt, ndays)
  sindecl = sin(lat * 23.5)    ! degrees → declination
  dayangle = (julian_day - 1 + gmt/24.0)
  if (dayangle >= 80) dayangle = (dayangle - 80) * ndays  
  ! Solar hour angle via sincos
  ! Fourier series voor equation of time:
  !   1.0001 + 0.03422*cos(ω) + 0.00128*sin(ω) + 0.000719*cos(2ω) + 0.000077*sin(2ω)
  solcon = result * 1370.0   ! Solar constant
end
```

---

### Belangrijke Constanten (gedecodeerd uit `.rodata`)

| Offset | Waarde | Betekenis |
|---|---|---|
| `0x2d300` | 0.0 | Nuldrempel |
| `0x2d304` | 1.0 | Eenheid |
| `0x2d30c` | 6,371,200 | Aardstraal (m) |
| `0x2d310` | 0.01745 | π/180 (graden→radialen) |
| `0x2d320` | 3.14159 | π |
| `0x2d32c` | 17.67 | Clausius-Clapeyron constante |
| `0x2d330` | 273.15 | 0°C in Kelvin |
| `0x2d334` | 29.65 | Vochtigheid constante |
| `0x2d338` | 6.112 | Saturatie dampdruk bij 0°C (hPa) |
| `0x2d33c` | 0.622 | ε = Mv/Md (mengverhouding) |
| `0x2d348` | 0.001571 | Bolton LCL coëfficiënt |
| `0x2d354` | 273.16 | Triple point water (K) |
| `0x2d358` | 3.4978 | Poisson exponent voor LCL |
| `0x2d35c` | -999.0 | Missing value sentinel |
| `0x2d360` | 3.369e-5 | g/θ_ref voor W* |
| `0x2d364` | 0.3333 | 1/3 (kubiekewortel) |
| `0x2d368` | 196.85 | m→ft conversie (×100/0.3048?) |
| `0x2d388` | 2490 | Latente warmte gerelateerd |
| `0x2d38c` | -987654 | Missing value flag |
| `0x2d3a4` | 100000 | Referentiedruk P0 (Pa) |
| `0x2d3b8` | 0.25 | 1/4 |
| `0x2d2f8` | 1370 | Zonneconstante (W/m²) |

---

### Dataformaat Ondersteuning

- **Invoer**: WRF model output (3D velden: `wa`, `z`, `ter`, `pblh`, `bparam`, `theta`, `qvapor`, `qcloud`)
- **Projecties**: Lambert Conformal & LatLon
- **BLIPMAP formaat**: Eigen binair formaat met header (projectie-info), leest via Fortran formatted I/O
- **Unzip support**: Kan gecomprimeerde databestanden uitpakken via systeemaanroep

### Interne Helpers (niet geëxporteerd naar NCL)

- `dcapedjss_` — CAPE berekening kern (Doswell/Schultz methode)
- `dbrents_`, `dmnbrak_`, `dlinmins_` — Numerical Recipes optimalisatie (Brent's method, bracket, line minimization)
- `dfuncshea_` — Shear functie voor optimalisatie
- `desatskewt_`, `deswskewt_`, `dwmrskewt_`, `deptskewt_`, `dtconskewt_`, `dtsaskewt_`, `dwxskewt_`, `dwobfskewt_`, `dtmlapskewt_`, `dinterpskewt_` — Complete Skew-T thermodynamische toolkit
- `radconst_` — Zonnestralingsconstanten
- `datafile_unzip_` — Bestandsdecompressie
- `squeeze_blanks_` — String utility

---

### Conclusie

Dit is **Dr. Jack Glendening's BLIPMAP soaring forecast library** — een NCL plugin geschreven in Fortran die WRF numeriek weermodel output omzet in parameters relevant voor zweefvliegers en paragliders. Het berekent:

1. **Thermieksterkte** (W*, hcrit, hlift)
2. **Boundary layer structuur** (BL hoogte, wind, temperatuur)
3. **Bewolking** (wolkenbasis, BL cloud percentage)
4. **Stabiliteitsindices** (CAPE, Showalter)
5. **Zonnestraling** (surface sun percentage)

Het is afkomstig van het **DrJack RASP (Regional Atmospheric Soaring Prediction)** project, een bekende tool in de zweefvlieggemeenschap.
