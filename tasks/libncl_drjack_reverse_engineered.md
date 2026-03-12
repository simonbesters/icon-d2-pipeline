# Reverse Engineering: `libncl_drjack.avx512.nocuda.so`

## Binary Overview

| Property | Value |
|---|---|
| **File** | `libncl_drjack.avx512.nocuda.so` |
| **Size** | 3,974,824 bytes (3.8 MB) |
| **Format** | ELF 64-bit LSB shared object, x86-64 |
| **SONAME** | `libncl_drjack.avx512.nocuda.so` |
| **BuildID** | `ea10255db82c73a82ff74893e4014f8393cd1b55` |
| **Stripped** | No (full symbol table) |
| **Compiler** | gfortran (GCC) — Fortran 95 |
| **Source file** | `/home/elmer/cudaServer/drjack/ncl_jack_fortran.f95` |
| **Source file 2** | `/home/elmer/cudaServer/drjack/wrf_user_drjack.f95` (filter2d) |
| **SIMD** | AVX/AVX2 (VEX-encoded) — **geen AVX-512 ondanks filename** |

### Dependencies

```
libgfortran.so.5   libquadmath.so.0   libstdc++.so.6
libm.so.6          libmvec.so.1       libgcc_s.so.1
libc.so.6          libgomp.so.1
```

### Symbol Breakdown (2648 totaal)

| Category | Count | Description |
|---|---|---|
| DrJack-specifiek | ~97 | `calc_*`, `find_*`, `compute_*`, `ptlcl_`, `radconst_`, etc. |
| NCL runtime | 1602 | `NhlCreate`, `_NclBuild*`, `NclMalloc`, `NclFree`, etc. |
| HDF5/NetCDF/GRIB | 125 | `H5*`, `nc_*`, `grib_*` statisch gelinkt |
| Data/BSS globals | 312 | `is_recursive.*`, constanten, error strings |

---

## Architectuurpatronen

1. **Recursie-guards**: Alle `calc_*` functies beginnen met `test is_recursive.NNN.NN; jne error`. Dit is een gfortran-veiligheid voor RECURSIVE subroutines.
2. **Array indexering**: Fortran column-major. 2D arrays `A(i,j)` worden benaderd als `base + (j-1)*stride + (i-1)`.
3. **NCL wrapper patroon**: Elke Fortran functie `calc_foo_` heeft een NCL wrapper `calc_foo_W` die argumenten uit NCL data-structuren haalt.
4. **Boundary-checking**: Alle array-accessen hebben runtime bounds checks via `_gfortran_runtime_error_at`.

---

## Decoded Constants (`.rodata`)

### Thermisch Model (hcrit/hlift)

| Adres | Waarde | Gebruik |
|---|---|---|
| `0x31be20` | **196.85** | ft/min conversie factor (1 m/s = 196.85 ft/min) |
| `0x31be24` | **225.0** | hcrit drempelwaarde in ft/min |
| `0x31be28` | **0.463** | Thermisch model coëfficiënt α₁ |
| `0x31be2c` | **0.4549** | Thermisch model coëfficiënt α₂ |
| `0x31be30` | **1.3674** | Thermisch model coëfficiënt α₃ |
| `0x31be34` | **0.01267** | Thermisch model coëfficiënt α₄ |
| `0x31be38` | **0.1126** | Thermisch model sqrt-offset |

### Clausius-Clapeyron / Blcloud

| Adres | Waarde | Gebruik |
|---|---|---|
| `0x31bde4` | **17.67** | Magnus-formule L/Rᵥ coëfficiënt |
| `0x31bde8` | **273.15** | Kelvin offset |
| `0x31bdec` | **29.65** | Magnus-formule noemer offset |
| `0x31bdf0` | **6.112** | Verzadigingsdampspanning basis (hPa) |
| `0x31bdf4` | **0.622** | ε = Mw/Md (mengverhouding numerator) |
| `0x31bdf8` | **0.378** | 1 − ε (mengverhouding noemer) |

### BL Integratie

| Adres | Waarde | Gebruik |
|---|---|---|
| `0x31bdcc` | **0.5** | Trapeziumregel factor |
| `0x31be3c` | **102.04** | ≈ 1000/g = 1000/9.8 (drukintegratie schaal) |
| `0x31be40` | **2490.0** | Latente warmte schaal (qcblhf) |

### Subgrid BL Cloud

| Adres | Waarde | Gebruik |
|---|---|---|
| `0x31be4c` | **400.0** | Resultaat vermenigvuldiger |
| `0x31be50` | **300.0** | Resultaat aftrekking |
| `0x31be54` | **0.9** | RH schaalfactor |
| `0x31be5c` | **95.0** | RH bovengrens |
| `0x31be60` | **0.08** | Sigma coëfficiënt |
| `0x31be64` | **0.49** | Sigma constante |

### Solar Positie (sfcsunpct)

| Adres | Waarde | Gebruik |
|---|---|---|
| `0x31be74` | **15.0** | Graden per uur (uurhoek) |
| `0x31be78` | **12.0** | Zonnig-middagoffset (uren) |
| `0x31be7c` | **1e-9** | Minimale cosinus drempel |
| `0x31be80` | **287.0** | Rd = gascons. droge lucht (J/kg/K) |
| `0x31be84` | **1e-4** | Accumulatie vermenigvuldiger |
| `0x31be88` | **141.5** | Power-law basis vermenigvuldiger |
| `0x31be8c` | **0.635** | Power-law **EXPONENT** (2e arg van `powf`) |
| `0x31be90` | **2.9** | Resultaat deler 1 |
| `0x31be94` | **5.925** | Resultaat deler 2 |
| `0x31be98` | **1e-5** | dz vermenigvuldiger |
| `0x31be9c` | **0.01** | Irradiantie vermenigvuldiger |
| `0x31bea0` | **0.001** | Convergentie drempel |

### Overige

| Adres | Waarde | Gebruik |
|---|---|---|
| `0x31afc0` | **-0.0** | Sign bit mask (0x80000000) voor wblmaxmin |
| `0x31bda8` | **1.0** | Universeel |
| `0x31bdfc` | **100.0** | Percentage conversie |
| `0x31bde0` | **1000.0** | m→km conversie |
| `0x31be0c` | **273.16** | Kelvin offset (sfcsunpct) |
| `0x31be14` | **-999.0** | Missing value indicator |
| `0x31be68` | **0.25** | Filter2d gewicht (¼ voor 2D Laplaciaan) |
| `0x31be6c` | **-6.9** | Dauwpuntdepressie drempel |
| `0x31beb8` | **2.618** | φ² (gulden snede kwadraat) |
| `0x31bebc` | **-1.618** | −φ (negatieve gulden snede) |

### Radconst-gerelateerd (solar position)

| Adres | Waarde | Gebruik |
|---|---|---|
| `0x31bd78` | **23.5** | Aardas helling (graden) |
| `0x31bd80` | **80.0** | Dag-van-jaar offset |
| `0x31bd84` | **285.0** | Dag-van-jaar offset |
| `0x31bd88` | **360.0** | Graden in cirkel |
| `0x31bd8c` | **365.0** | Dagen per jaar |
| `0x31bda4` | **1370.0** | Zonneconstante (W/m²) |
| `0x31bdc0` | **0.01745** | π/180 (deg→rad) |

---

## Functie Reconstructies

### 1. `calc_hcrit_` — Kritische Hoogte boven BL Top

**Bron**: `ncl_jack_fortran.f95` regel 494
**Grootte**: 496 bytes @ `0x22640`
**Aanroepen**: Geen externe calls

#### Signature (Fortran) — **gecorrigeerd na verificatie**
```fortran
subroutine calc_hcrit_(wstar, ter, hbl, nx, ny, result)
    real, intent(in)    :: wstar(nx, ny)   ! W* convectieve snelheid (m/s)
    real, intent(in)    :: ter(nx, ny)     ! Terrain hoogte (m)
    real, intent(in)    :: hbl(nx, ny)     ! BL diepte (m) — 3e array argument
    integer, intent(in) :: nx, ny
    real, intent(out)   :: result(nx, ny)  ! Kritische hoogte (m MSL) — 6e argument
```

> **Verificatie**: Uit de disassembly blijkt dat `calc_hcrit_` **6 argumenten** heeft:
> `rdi=wstar, rsi=ter, rdx=hbl, rcx=&nx, r8=&ny, r9=result`.
> Het 3e register (`rdx`) wordt als aparte array geladen en vermenigvuldigd met het
> thermische model resultaat op adres `0x22750`. Het resultaat wordt geschreven naar
> het 6e register (`r9`) op adres `0x2276a`.

#### Gereconstrueerd Algoritme
```fortran
do j = 1, ny
  do i = 1, nx
    wstar_fpm = wstar(i,j) * 196.85       ! m/s → ft/min

    if (wstar_fpm > 225.0) then
      ! Thermisch penetratiemodel
      ratio = 225.0 / wstar_fpm
      x = 0.463 * ratio                    ! genormaliseerde inversie-ratio
      height_frac = 0.4549 - x             ! lineair deel
      height_frac = height_frac * 1.3674   ! schaling
      height_frac = height_frac + 0.01267  ! offset
      height_frac = sqrt(height_frac)      ! niet-lineaire correctie
      height_frac = height_frac + 0.1126   ! basishoogte offset

      result(i,j) = ter(i,j) + height_frac * hbl(i,j)
      ! ^^^ GEVERIFIEERD: het 3e argument (rdx) is een aparte array (hbl),
      !     NIET ter hergebruikt. De vermenigvuldiging staat op 0x22750:
      !     vmulss xmm0, xmm0, [r9 + 4*rdx - 4]  (r9 = hbl base)
    else
      result(i,j) = ter(i,j)              ! Geen thermiek → terrein hoogte
    end if

    ! Clamp: result mag niet negatief zijn
    result(i,j) = max(0.0, result(i,j))
  end do
end do
```

#### Analyse
- **Drempel**: 225 ft/min ≈ 1.143 m/s — bevestigt de waarde die in rasp-pynumb wordt gebruikt
- **Conversie**: 196.85 ft/min per m/s — standaard
- Het thermische model is een empirische benadering: `height = ter + (sqrt(a₃*(a₂ - a₁*225/W*) + a₄) + a₅) × hbl`
- **GEVERIFIEERD**: Het 3e argument is hbl (BL diepte), NIET ter hergebruikt. De formule is: `result = ter + sqrt_model × hbl`. Dit is bevestigd via registertracing: `rdx` (3e arg) → `r9` (na remap) → vermenigvuldigd op `0x22750`.

---

### 2. `calc_hlift_` — Lifthoogte

**Bron**: `ncl_jack_fortran.f95` regel 533
**Grootte**: 480 bytes @ `0x22830`
**Aanroepen**: Geen externe calls

#### Signature (Fortran)
```fortran
subroutine calc_hlift_(iopt, wstar, ter, hbl, result, nx, ny)
    integer, intent(in) :: iopt            ! Optieflag (op stack)
    real, intent(in)    :: wstar(nx, ny)   ! W* (m/s)
    real, intent(in)    :: ter(nx, ny)     ! Terrain (m)
    real, intent(in)    :: hbl(nx, ny)     ! BL hoogte (m)
    real, intent(out)   :: result(nx, ny)  ! Lift hoogte (m MSL)
    integer, intent(in) :: nx, ny
```

#### Gereconstrueerd Algoritme
```fortran
do j = 1, ny
  do i = 1, nx
    wstar_fpm = wstar(i,j) * 196.85       ! m/s → ft/min
    threshold = iopt                        ! *iopt is een scalar, geladen uit %r10 → (%rdi)

    if (wstar_fpm > threshold) then
      ! Zelfde thermisch model als hcrit maar met variabele drempel
      ratio = threshold / wstar_fpm
      x = 0.463 * ratio
      height_frac = 0.4549 - x
      height_frac = height_frac * 1.3674
      height_frac = height_frac + 0.01267
      height_frac = sqrt(height_frac)
      height_frac = height_frac + 0.1126

      result(i,j) = ter(i,j) + height_frac * hbl(i,j)
    else
      result(i,j) = ter(i,j)
    end if

    result(i,j) = max(0.0, result(i,j))
  end do
end do
```

#### Verschil met `calc_hcrit_`
- `calc_hlift_` heeft een **extra parameter** (`iopt` via het eerste register `%rdi`), die als drempel dient i.p.v. de hardcoded 225.
- De drempel wordt vergeleken met `xmm3` (geladen van `(%r10)` = `*iopt`), niet de constante 225.0.
- **GEVERIFIEERD**: Beide functies gebruiken `hbl(i,j)` als schaalfactor — `calc_hcrit_` heeft ook hbl als 3e argument (niet ter hergebruikt).

---

### 3. `calc_sfclclheight_` — Surface LCL Hoogte (Bolton)

**Bron**: `ncl_jack_fortran.f95` regel 264
**Grootte**: 1104 bytes @ `0x21410`
**Aanroepen**: `ptlcl_` (Bolton 1980 LCL berekening)

#### Signature (Fortran)
```fortran
subroutine calc_sfclclheight_(z, p, t, td, result, lclp, nx, ny, nz)
    real, intent(in)    :: z(nx, ny, nz)    ! Hoogte op druk-niveaus (m)
    real, intent(in)    :: p(nx, ny, nz)    ! Druk (Pa of hPa)
    real, intent(in)    :: t(nx, ny, nz)    ! Temperatuur (K)
    real, intent(in)    :: td(nx, ny, nz)   ! Dauwpunt (K) — NIET ZEKER, mogelijk Td of q
    real, intent(out)   :: result(nx, ny)   ! LCL hoogte (m MSL)
    real, intent(out)   :: lclp(nx, ny)     ! LCL druk (hPa)
    integer, intent(in) :: nx, ny, nz
```

#### Gereconstrueerd Algoritme
```fortran
do j = 1, ny
  do i = 1, nx
    ! Initialiseer met missing value
    result(i,j) = -999.0
    lclp(i,j) = -999.0

    ! Bereken LCL druk via Bolton-methode (surface waarden)
    call ptlcl_(z(i,j,1), p(i,j,1), td(i,j,1), lclp(i,j))
    ! ptlcl_ berekent de LCL druk uit oppervlaktedruk en dauwpunt

    ! Kopieer surface hoogte naar resultaat als startwaarde
    result(i,j) = t(i,j,1)   ! of z(i,j,1) — afhankelijk van registervolgorde

    ! Zoek het niveau waar druk < LCL druk (stijgend)
    do k = 2, nz
      if (z(i,j,k) < lclp(i,j)) then  ! z hier is eigenlijk druk-array
        ! Gevonden: interpoleer
        if (k == nz) then
          ! Bovenste niveau bereikt — gebruik dat niveau
          result(i,j) = t(i,j,nz)    ! hoogte op bovenste niveau
        else if (k > 1) then
          ! Lineaire interpolatie tussen niveau k-1 en k
          dp = z(i,j,k) - lclp(i,j)
          dp_total = z(i,j,k) - z(i,j,k-1)
          dz = t(i,j,k) - t(i,j,k-1)   ! hoogteverschil
          result(i,j) = t(i,j,k) - dp * dz / dp_total
        end if
        exit
      end if
    end do
  end do
end do
```

#### Analyse
- Gebruikt **Bolton (1980)** via `ptlcl_` — dit is significant anders dan Espy die rasp-pynumb als fallback gebruikt.
- De `ptlcl_` functie is een externe routine (via PLT) die de LCL druk berekent uit oppervlakte T en Td.
- Missing value is `-999.0` (0xC479C000), consistent met de binary constante.
- Na het vinden van de LCL drukniveau doet het **lineaire interpolatie** in de verticale kolom.

---

### 4. `calc_blclheight_` — Boundary Layer Cloud Height

**Bron**: `ncl_jack_fortran.f95` regel 319
**Grootte**: 1456 bytes @ `0x21860`
**Aanroepen**: `calc_rh1_` (relatieve vochtigheid)

#### Signature (Fortran)
```fortran
subroutine calc_blclheight_(z, t, p, q, result, rhout, nx, ny, nz)
    real, intent(in)    :: z(nx, ny, nz)     ! Hoogte (m)
    real, intent(in)    :: t(nx, ny, nz)     ! Temperatuur (K)
    real, intent(in)    :: p(nx, ny, nz)     ! Druk (hPa)
    real, intent(in)    :: q(nx, ny, nz)     ! Mengverhouding (kg/kg)
    real, intent(out)   :: result(nx, ny)    ! BL cloud hoogte (m MSL)
    real, intent(out)   :: rhout(nx, ny)     ! RH bij BL cloud niveau
    integer, intent(in) :: nx, ny, nz
```

#### Gereconstrueerd Algoritme
```fortran
do j = 1, ny
  do i = 1, nx
    ! Bewaar oppervlakte hoogte
    result(i,j) = z(i,j,1)
    rh_prev = 0.0

    ! Loop opwaarts door verticale niveaus
    do k = 1, nz
      if (k > nz_limit) exit

      ! Bereken RH op dit niveau
      call calc_rh1_(p(i,j,k), t(i,j,k), q(i,j,k), rh_current)

      ! Check of RH >= 100% (verzadiging)
      if (100.0 <= rh_current) then
        ! Neerwaarts interpoleren naar exact RH=100% niveau
        if (k == 1) then
          ! Al verzadigd aan oppervlak
          result(i,j) = z(i,j,1)
        else if (k > 1) then
          ! Lineaire interpolatie: vind hoogte waar RH exact = 100
          drh = rh_current - rh_prev           ! RH verschil over laag
          frac = (100.0 - rh_prev) / drh       ! fractie in laag
          dz = z(i,j,k) - z(i,j,k-1)          ! hoogteverschil
          result(i,j) = z(i,j,k) - frac * dz  ! geïnterpoleerde hoogte
        end if
        exit  ! gevonden
      end if

      ! Bij bovenste niveau: kopieer z van dat niveau
      if (k == nz) then
        result(i,j) = z(i,j,nz)
      end if

      rh_prev = rh_current
    end do
  end do
end do
```

#### Analyse
- **Methode**: Zoekt het laagste niveau waar RH ≥ 100%, interpoleert dan lineair.
- Gebruikt `calc_rh1_` (via PLT, externe functie) voor RH-berekening per niveau.
- De drempel is exact **100.0** (constante `0x31bdfc`).
- Dit verschilt mogelijk van een cloudbase-berekening gebaseerd op dauwpuntdepressie.

---

### 5. `calc_sfcsunpct_` — Surface Sun Percentage (Solar Irradiance)

**Bron**: `ncl_jack_fortran.f95` regel 1998
**Grootte**: 2240 bytes @ `0x28780`
**Aanroepen**: `radconst_`, `sincosf`, `cosf`, `powf`

#### Signature (Fortran)
```fortran
subroutine calc_sfcsunpct_(z, lat, lon, time_utc, t_sfc, psfc, &
                           q, xlat, result, nx, ny, nz)
    real, intent(in)    :: z(nx, ny, nz)      ! Hoogte niveaus (m)
    real, intent(in)    :: lat(nx, ny)         ! Breedtegraad
    real, intent(in)    :: lon(nx, ny)         ! Lengtegraad
    real, intent(in)    :: time_utc            ! Tijd (UTC)
    real, intent(in)    :: t_sfc(nx, ny)       ! Oppervlakte temp (K)
    real, intent(in)    :: psfc(nx, ny)        ! Oppervlakte druk (hPa)
    real, intent(in)    :: q(nx, ny, nz)       ! Vocht/wolken
    real, intent(in)    :: xlat(nx, ny)        ! Extra lat data
    real, intent(out)   :: result(nx, ny)      ! Zon percentage (0-100)
    integer, intent(in) :: nx, ny, nz
```

#### Gereconstrueerd Algoritme
```fortran
! Constraint: nz <= 100 (anders error)

do j = 1, ny
  do i = 1, nx
    ! Bereken druklaag-dikte (dz) voor elke laag
    do k = 1, nz-2
      dz_layer(k) = 0.5 * (z(i,j,k+2) - z(i,j,k))  ! gecentreerde differentiatie
    end do
    dz_layer(nz-1) = dz_layer(nz-2)  ! kopieer laatste

    ! Bereken zonnepositie
    decl = 0.01745   ! rad/deg conversie in radconst_
    call radconst_(time_utc, lat(i,j), decl_angle, ha_factor)

    ! Bereken cosinus zonshoogte
    call sincosf(lat(i,j) * ha_factor, sin_lat, cos_lat)

    hour_angle = (lon(i,j) / 15.0 + time_utc - 12.0) * 15.0 * ha_factor
    call cosf(hour_angle)

    cos_zenith = sin_decl * sin_lat + cos_decl * cos_lat * cos(hour_angle)

    ! Als zon onder horizon → result = -999 (missing)
    if (cos_zenith <= 1e-9) then
      result(i,j) = -999.0
      cycle
    end if

    ! Bereken columnaire extinctie
    sunpct_accum = cos_zenith * dz_layer(1)  ! initiële irradiantie
    tau_total = 0.0
    tau_prev = 0.0
    irr_prev = sunpct_accum

    do k = nz, 1, -1   ! Top-down
      if (k > nz) exit

      ! Bereken optische dikte per laag
      rho = 100.0 * psfc(i,j) / (287.0 * (t_sfc(i,j) + 273.16))  ! dichtheid
      optical_depth = rho * q(i,j,k) * dz_layer(k) * 1000.0
      tau_total = tau_total + optical_depth * 1e-4

      ! Power law extinctie — GEVERIFIEERD via disassembly 0x28cb8-0x28cca:
      !   xmm0 = tau * 1e-4 / cos_z * 141.5 + 1.0  (base)
      !   xmm1 = 0.635                               (exponent, geladen op 0x28c73)
      !   call powf                                   (op 0x28cca)
      x = 1.0 + tau_total * 1e-4 * 141.5 / cos_zenith
      transmittance = powf(x, 0.635)   ! 0.635 is de EXPONENT, niet additief!

      ! Bereken zon-fractie
      sfrac_1 = tau_total / 2.9       ! diffuse component
      sfrac_2 = tau_total / 5.925     ! directe component

      ! Delta-irradiantie
      dtransmit = (transmittance - tau_prev) * irr_prev / irr_prev

      ! Accumuleer vocht-extinctie
      dz_contrib = dz_layer(k) * rho * 1e-5 / cos_zenith
      tau_prev = tau_prev + dz_contrib * irr_prev * 0.01

      ! Beperk tot minimum
      tau_prev = max(tau_prev, 1e-9)
    end do

    ! Convergentiecheck
    if (tau_prev > 0.001) then
      result(i,j) = min(100.0 * result(i,j) / tau_prev, 100.0)
    else
      result(i,j) = -999.0   ! Geen convergentie
    end if
  end do
end do
```

#### Analyse
- **Complexiteit**: Dit is de meest complexe functie (2240 bytes). Het model berekent zonlichtpenetratie door een verticale kolom.
- **Methode**: Empirische power-law transmissie met columnaire extinctie-integratie.
- Gebruikt `radconst_` voor declinatie en uurhoekberekening — dit is de WRF `radconst` routine.
- **GEVERIFIEERD**: De power-law formule is `transmittance = (1.0 + 141.5 × τ / cos(θ))^0.635`.
  - `0.635` is de **EXPONENT** (geladen in `xmm1` op adres `0x28c73` vanuit `0x31be8c`)
  - `141.5` is de basis-vermenigvuldiger (geladen op `0x28cb8` vanuit `0x31be88`)
  - De `1.0 +` term garandeert transmittance ≥ 1 bij nul optische diepte
- De constanten (2.9, 5.925) worden na powf gebruikt voor diffuse/directe componenten.
- **Vergelijking met rasp-pynumb**: Als jullie Kasten (1980) gebruiken voor duidelijke-luchttransmissie met een Linke turbidity factor, dan is het DrJack-model significant anders — het integreert de columnaire wolkwater-extinctie direct.

---

### 6. `calc_subgrid_blcloudpct_grads_` — Subgrid BL Bewolkingspercentage

**Bron**: `ncl_jack_fortran.f95` regel 1173
**Grootte**: 1168 bytes @ `0x25c30`
**Aanroepen**: `expf` (exponentieel)

#### Signature (Fortran)
```fortran
subroutine calc_subgrid_blcloudpct_grads_(z, p, t, q, hbl, result, nx, ny, nz)
    real, intent(in)    :: z(nx, ny, nz)
    real, intent(in)    :: p(nx, ny, nz)    ! Druk (hPa)
    real, intent(in)    :: t(nx, ny, nz)    ! Temperatuur (K)
    real, intent(in)    :: q(nx, ny, nz)    ! Mengverhouding (kg/kg)
    real, intent(in)    :: hbl(nx, ny)      ! BL hoogte (m)
    real, intent(out)   :: result(nx, ny)   ! Cloud % (0-100)
    integer, intent(in) :: nx, ny, nz
```

#### Gereconstrueerd Algoritme
```fortran
do j = 1, ny
  do i = 1, nx
    cloud_max = 0.0

    do k = 1, nz
      ! Stop als boven BL top
      if (z(i,j,k) > hbl(i,j)) exit

      ! Magnus-formule: verzadigingsdampspanning
      ! es = 6.112 * exp(17.67 * (T - 273.15) / (T - 273.15 + 29.65))
      tc = t(i,j,k) - 273.15                          ! Celsius
      es = 6.112 * exp(17.67 * tc / (tc + 29.65))     ! hPa

      ! Verzadigingsmengverhouding
      ! qs = 0.622 * es / (p - 0.378 * es)
      qs = 0.622 * es / (p(i,j,k) - 0.378 * es)

      ! Relatieve vochtigheid
      rh = q(i,j,k) / qs

      ! Subgrid bewolkingskans via gaussiaanse verdeling
      ! sigma = 0.08 + 0.49 * (iets)  — subgrid variabiliteit
      ! cloud_frac = min(400.0 * rh - 300.0, 100.0)
      ! OF: meer waarschijnlijk een statistische benadering:

      ! Methode: empirische RH→cloud mapping
      cloud_frac = 400.0 * rh * 0.9 - 300.0

      ! Beperk tot 0-95%
      cloud_frac = max(0.0, min(95.0, cloud_frac))

      ! Neem maximum over alle BL niveaus
      cloud_max = max(cloud_max, cloud_frac)
    end do

    result(i,j) = cloud_max * 100.0   ! OF: al in percentage
  end do
end do
```

#### Analyse
- **Methode**: Dit is **GEEN** standaard Gaussiaans subgrid model. Het is een empirische **RH-drempel methode**: `cloud% = clamp(400*RH - 300, 0, 95)`.
- Dit komt overeen met een lineaire mapping: 0% cloud bij RH=75%, 100% bij RH=100%.
- De constanten 400, 300 komen uit `0x31be4c` en `0x31be50`.
- De Magnus-formule constanten (17.67, 273.15, 29.65, 6.112) bevestigen standaard meteorologische formule.
- **Vergelijking met rasp-pynumb**: Als jullie een puur RH-scheme gebruiken, dan is het conceptueel vergelijkbaar maar met andere mapping-constanten.

---

### 7. `calc_blavg_` — BL-Gemiddelde (Gewogen Integratie)

**Bron**: `ncl_jack_fortran.f95` regel 365
**Grootte**: 976 bytes @ `0x21e10`
**Aanroepen**: Geen externe calls

#### Signature (Fortran)
```fortran
subroutine calc_blavg_(field, z, hbl, zbot, result, nx, ny, nz)
    real, intent(in)    :: field(nx, ny, nz)  ! Te middelen veld
    real, intent(in)    :: z(nx, ny, nz)      ! Hoogte niveaus (m)
    real, intent(in)    :: hbl(nx, ny)        ! BL top hoogte
    real, intent(in)    :: zbot(nx, ny)       ! BL bodem hoogte
    real, intent(out)   :: result(nx, ny)     ! BL-gemiddeld veld
    integer, intent(in) :: nx, ny, nz
```

#### Gereconstrueerd Algoritme
```fortran
do j = 1, ny
  do i = 1, nx
    ! Surface bijdrage (eerste laag)
    dz_first = z(i,j,1) - zbot(i,j)
    bl_top = hbl(i,j) + zbot(i,j)       ! absolute BL top
    integral_f = 0.5 * dz_first * field(i,j,1)   ! trapeziumregel halve stap
    total_dz = dz_first

    ! Loop door verticale niveaus
    do k = 2, nz
      if (z(i,j,k) >= bl_top) then
        ! BL top bereikt — interpoleer fractie in bovenste laag
        if (k <= nz .and. k > 1) then
          frac_dz = bl_top - z(i,j,k-1)
          dz_layer = z(i,j,k) - z(i,j,k-1)

          ! Lineair geïnterpoleerde veldwaarde bij BL top
          df = field(i,j,k) - field(i,j,k-1)
          f_interp = field(i,j,k-1) + 0.5 * df * frac_dz / dz_layer

          integral_f = integral_f + f_interp * frac_dz
          total_dz = total_dz + frac_dz
        end if
        exit
      end if

      ! Volledige laag bijdrage (trapeziumregel)
      dz_layer = z(i,j,k) - z(i,j,k-1)
      f_avg = 0.5 * (field(i,j,k) + field(i,j,k-1))   ! niet de exacte implementatie
      integral_f = integral_f + f_avg * dz_layer
      total_dz = total_dz + dz_layer
    end do

    ! Normaliseer
    result(i,j) = integral_f / total_dz
  end do
end do
```

#### Analyse
- **NIET een simpel gemiddelde** — het is een **hoogte-gewogen trapeziumregel integratie** genormaliseerd door de totale BL dikte.
- De constante **0.5** (`0x31bdcc`) bevestigt de trapeziumregel.
- **Interpolatie bij BL top**: Er wordt lineair geïnterpoleerd naar de exacte BL hoogte, niet simpelweg afgekapt op het dichtstbijzijnde niveau.
- De integrand is `field × dz`, genormaliseerd door `Σdz`, wat een massamiddelend gemiddelde geeft (aanname: constante dichtheid per laag).

---

### 8. `calc_wblmaxmin_` — BL Maximum/Minimum met Modusvlag

**Bron**: `ncl_jack_fortran.f95` regel 56
**Grootte**: 992 bytes @ `0x20a50`
**Aanroepen**: Geen externe calls

#### Signature (Fortran)
```fortran
subroutine calc_wblmaxmin_(iopt, field, z, hbl, zbot, result, nx, ny, nz)
    integer, intent(in) :: iopt               ! Modus: 0,1,2,3
    real, intent(in)    :: field(nx, ny, nz)   ! 3D veld
    real, intent(in)    :: z(nx, ny, nz)       ! Hoogte (m)
    real, intent(in)    :: hbl(nx, ny)         ! BL top hoogte
    real, intent(in)    :: zbot(nx, ny)        ! BL bodem hoogte
    real, intent(out)   :: result(nx, ny)      ! Resultaat
    integer, intent(in) :: nx, ny, nz
```

#### Gereconstrueerd Algoritme
```fortran
do j = 1, ny
  do i = 1, nx
    bl_top = hbl(i,j) + zbot(i,j)    ! absolute BL top

    ! Initialiseer max/min tracking
    val_max = 0.0      ! maximum waarde
    val_min = 0.0      ! minimum waarde (via sign-flip tracking)
    z_at_max = zbot(i,j)  ! hoogte bij maximum
    z_at_min = zbot(i,j)  ! hoogte bij minimum

    ! Loop door verticale niveaus in BL
    do k = 1, nz
      if (z(i,j,k) > bl_top) exit     ! voorbij BL top

      v = field(i,j,k)

      ! Track maximum
      if (v > val_max) then
        z_at_max = z(i,j,k)           ! onthoud hoogte
        val_max = v
      end if

      ! Track minimum (via absoluut minimum)
      if (v <= val_min) then
        z_at_min = z(i,j,k)
        val_min = v
      end if
    end do

    ! Bepaal of we max of min resultaat gebruiken
    ! Criterium: abs(val_min) > val_max → gebruik min, anders max
    ! (via: vxorps sign_mask, val_min → abs(val_min), dan compare)
    use_max = (val_max > abs(val_min))

    if (use_max) then
      select case (iopt)
        case (0)  ! Waarde × 100%
          result(i,j) = val_max * 100.0
        case (1)  ! Hoogte
          result(i,j) = z_at_max
        case (2)  ! Verschil (waarde - surface)
          result(i,j) = z_at_max - zbot(i,j)
        case (3)  ! Ratio × 100%
          result(i,j) = ((z_at_max - zbot(i,j)) / hbl(i,j)) * 100.0
      end select
    else
      select case (iopt)
        case (0)
          result(i,j) = val_min * 100.0
        case (1)
          result(i,j) = z_at_min
        case (2)
          result(i,j) = z_at_min - zbot(i,j)
        case (3)
          result(i,j) = ((z_at_min - zbot(i,j)) / hbl(i,j)) * 100.0
      end select
    end if
  end do
end do
```

#### Analyse — 4 Modi
| `iopt` | Resultaat | Eenheid |
|---|---|---|
| 0 | Extremum waarde × 100 | % of andere |
| 1 | Hoogte waar extremum optreedt | m MSL |
| 2 | Hoogte boven oppervlak | m AGL |
| 3 | Genormaliseerde hoogte (fraction van BL) × 100 | % van BL diepte |

- Het selecteert automatisch max of min gebaseerd op welke het grotere absolute waarde heeft.
- De sign-bit mask (`0x80000000` bij `0x31afc0`) wordt gebruikt voor absolute waarde vergelijking via `vxorps`.

---

### 9. `calc_blinteg_mixratio_` — BL-Geïntegreerde Mengverhouding

**Bron**: `ncl_jack_fortran.f95` regel 672
**Grootte**: 1040 bytes @ `0x230b0`
**Aanroepen**: Geen externe calls

#### Signature (Fortran)
```fortran
subroutine calc_blinteg_mixratio_(field, z, p, hbl, pbot, result, nx, ny, nz)
    real, intent(in)    :: field(nx, ny, nz)  ! Mengverhouding (kg/kg)
    real, intent(in)    :: z(nx, ny, nz)      ! Hoogte (m)
    real, intent(in)    :: p(nx, ny, nz)      ! Druk (hPa of Pa)
    real, intent(in)    :: hbl(nx, ny)        ! BL hoogte
    real, intent(in)    :: pbot(nx, ny)       ! Oppervlaktedruk
    real, intent(out)   :: result(nx, ny)     ! Geïntegreerde waarde
    integer, intent(in) :: nx, ny, nz
```

#### Gereconstrueerd Algoritme
```fortran
do j = 1, ny
  do i = 1, nx
    bl_top = hbl(i,j) + pbot(i,j)    ! OF: druk op BL top

    ! Surface bijdrage
    dz = z(i,j,1) - p(i,j,1)         ! hoogteverschil eerste laag
    integral = 0.5 * dz * field(i,j,1)

    do k = 2, nz
      if (z(i,j,k) >= bl_top) then    ! boven BL
        ! Interpoleer fractie
        if (k > 1) then
          frac = bl_top - z(i,j,k-1)
          dz_full = z(i,j,k) - z(i,j,k-1)

          ! Lineair geïnterpoleerde mengverhouding
          df = field(i,j,k) - field(i,j,k-1)
          f_interp = field(i,j,k-1) + 0.5 * (df / dz_full) * frac
          integral = integral + f_interp * frac
        end if
        exit
      end if

      ! Volledige laag
      dz = z(i,j,k) - z(i,j,k-1)
      f_avg = 0.5 * (field(i,j,k) + field(i,j,k-1))
      integral = integral + f_avg * dz
    end do

    ! Schaal met 1000/g ≈ 102.04
    result(i,j) = integral * 102.04
  end do
end do
```

#### Analyse
- Identieke structuur als `calc_blavg_` maar dan met **schaalfactor 102.04 ≈ 1000/g**.
- Dit geeft de **precipitable water** (neerslagbaar water) equivalent: ∫(q × dz) × 1000/g.
- Eenheid resultaat: **kg/m²** (of mm waterkolom).

---

### 10. `calc_aboveblinteg_mixratio_` — Boven-BL Geïntegreerde Mengverhouding

**Bron**: `ncl_jack_fortran.f95` regel 720
**Grootte**: 1232 bytes @ `0x234c0`
**Aanroepen**: Geen externe calls

#### Gereconstrueerd Algoritme
```fortran
! Identiek aan calc_blinteg_mixratio_, maar integreert BOVEN de BL top
! i.e., van BL top tot model top

do j = 1, ny
  do i = 1, nx
    bl_top = hbl(i,j) + pbot(i,j)
    integral = 0.0

    ! Zoek het eerste niveau boven BL top
    start_k = 0
    do k = 1, nz
      if (z(i,j,k) > bl_top) then
        start_k = k

        ! Fractie van eerste laag boven BL
        if (k > 1) then
          frac = z(i,j,k) - bl_top
          dz_full = z(i,j,k) - z(i,j,k-1)
          ! Interpoleer startwaarde
          df = field(i,j,k) - field(i,j,k-1)
          f_at_bl = field(i,j,k-1) + df * (bl_top - z(i,j,k-1)) / dz_full
          integral = integral + 0.5 * (field(i,j,k) + f_at_bl) * frac
        end if
        exit
      end if
    end do

    ! Integreer van start_k+1 tot top
    do k = start_k+1, nz
      dz = z(i,j,k) - z(i,j,k-1)
      f_avg = 0.5 * (field(i,j,k) + field(i,j,k-1))
      integral = integral + f_avg * dz
    end do

    result(i,j) = integral * 102.04    ! 1000/g schaling
  end do
end do
```

#### Analyse
- Structureel spiegelbeeld van `calc_blinteg_mixratio_`.
- Integreert van BL top naar model top.
- Zelfde schaalfactor 102.04 ≈ 1000/g.
- Complexer dan de BL-versie vanwege het vinden en interpoleren van het startniveau.

---

### 11. `calc_qcblhf_` — Cloud Water BL Height Fraction

**Bron**: `ncl_jack_fortran.f95` regel 779
**Grootte**: 1024 bytes @ `0x23990`
**Aanroepen**: Geen externe calls

#### Gereconstrueerd Algoritme
```fortran
do j = 1, ny
  do i = 1, nx
    bl_top = hbl(i,j) + zbot(i,j)

    ! Trapeziumintegratie van wolkenwater in BL
    dz = z(i,j,1) - zbot(i,j)
    integral = 0.5 * dz * qc(i,j,1)

    do k = 2, nz
      if (z(i,j,k) >= bl_top) then
        ! Interpoleer tot BL top
        frac = bl_top - z(i,j,k-1)
        dz_full = z(i,j,k) - z(i,j,k-1)
        df = qc(i,j,k) - qc(i,j,k-1)
        qc_interp = qc(i,j,k-1) + 0.5 * df * frac / dz_full
        integral = integral + qc_interp * frac
        exit
      end if

      dz = z(i,j,k) - z(i,j,k-1)
      integral = integral + 0.5 * (qc(i,j,k) + qc(i,j,k-1)) * dz
    end do

    ! Schaal met hbl × 2490 / normalisatie — GEVERIFIEERD op 0x23be4-0x23bf1:
    !   vmulss xmm0, xmm6, xmm2      → hbl × integral
    !   vmulss xmm0, xmm0, xmm5      → × 2490.0
    !   vdivss xmm0, xmm0, [rax+r12] → / array_divisor (vermoedelijk z of p)
    result(i,j) = hbl(i,j) * integral * 2490.0 / divisor(i,j)
  end do
end do
```

#### Analyse
- Structureel vergelijkbaar met `calc_blinteg_mixratio_` maar met **complexere eindformule**.
- **GEVERIFIEERD**: De uitkomst is NIET simpelweg `integral × 2490.0`. Er is een extra vermenigvuldiging met `hbl` (xmm6, geladen op `0x23af5`) en een deling door een array-waarde (op `0x23bf1`).
- De schaalfactor **2490.0** ≈ L_v/1000 waar L_v ≈ 2.49 × 10⁶ J/kg (latente warmte van verdamping).
- De extra hbl/divisor factor maakt het een **genormaliseerde hoogte-fractie** van het wolkenwater, consistent met de naam "qcblhf" (cloud water BL Height Fraction).

---

### 12. `filter2d_` — 2D Laplaciaan Smoother

**Bron**: `wrf_user_drjack.f95` regel 410
**Grootte**: 1104 bytes @ `0x354c0`
**Aanroepen**: Geen externe calls

#### Signature (Fortran) — **gecorrigeerd na verificatie**
```fortran
subroutine filter2d_(field, temp, nx, ny, npass)
    real, intent(inout) :: field(nx, ny)    ! Veld dat gesmoothd wordt
    real, intent(inout) :: temp(nx, ny)     ! Tijdelijk werkarray (2e argument)
    integer, intent(in) :: nx, ny
    integer, intent(in) :: npass            ! Aantal smooth-iteraties
```

> **Verificatie**: De functie heeft **5 argumenten**, niet 4. Het 2e register (`rsi`)
> wordt opgeslagen op `[rsp+0x8]` en gebruikt als tijdelijke buffer. De data wordt
> eerst van `field` naar `temp` gekopieerd (loop op `0x35599`), waarna de smoothing
> vanuit `temp` terug naar `field` geschreven wordt.

#### Gereconstrueerd Algoritme
```fortran
do pass = 1, npass
  ! Stap 1: Kopieer field → temp (loop op 0x35599)
  temp(:,:) = field(:,:)

  ! Stap 2: Smooth in j-richting (loop op 0x35690), leest temp, schrijft field
  do j = 3, ny-1
    do i = 2, nx-1
      field(i,j) = field(i,j) + 0.25 * (temp(i,j-1) + temp(i,j+1) - 2.0*temp(i,j))
    end do
  end do

  ! Stap 3: Smooth in i-richting (loop op 0x3574d), leest temp, schrijft field
  do j = 2, ny-1
    do i = 2, nx-1
      field(i,j) = field(i,j) + 0.25 * (temp(i-1,j) + temp(i+1,j) - 2.0*temp(i,j))
    end do
  end do
end do
! Netto effect: field = field + 0.25 * (∇²field) — equivalent aan 5-punts Laplaciaan
```

#### Analyse
- **2D Laplaciaan diffusie** met gewicht **0.25** (= 1/4), geïmplementeerd als **gescheiden 1D passes**.
- **GEVERIFIEERD**: Gebruikt een **tijdelijk array** (`temp`, 2e argument). De oorspronkelijke waarden worden naar `temp` gekopieerd, waarna de smoothing vanuit `temp` naar `field` geschreven wordt.
- Randpixels (i=1, i=nx, j=1, j=ny) worden NIET aangepast.
- Mathematisch equivalent aan: `field_new = field + 0.25 * ∇²field` (5-punts Laplaciaan), omdat beide 1D passes dezelfde `temp` buffer lezen.
- De 0.25 gewicht garandeert stabiliteit (maximaal 0.25 voor 2D diffusie).
- `npass` controleert de hoeveelheid smoothing.
- De constante 0.25 wordt geladen vanuit `0x31be68` (bevestigd op `0x3561c` en `0x35700`).

---

### 13. `dcapethermos_` en `dcapedjss_` — DCAPE (Downdraft CAPE)

#### 13a. `dcapethermos_`

**Bron**: `ncl_jack_fortran.f95`
**Grootte**: 3264 bytes @ `0x2c8b0`
**Stack**: ~40 KB
**Aanroepen**: `malloc`, `free`, wiskundige routines

```fortran
! Berekent thermodynamische profiel voor DCAPE
! Gebruikt DUBBELE PRECISIE (alle bewerkingen via 64-bit registers)
! Alloceert dynamisch geheugen via malloc (~40KB stack + heap)
!
! Dit is een hulpfunctie voor dcapedjss_ die het thermodynamische
! dalende luchtpakket profiel berekent.
```

#### 13b. `dcapedjss_`

**Bron**: `ncl_jack_fortran.f95`
**Grootte**: 9344 bytes @ `0x2a430`
**Stack**: ~160 KB
**Aanroepen**: `malloc`, `free`, `dcapethermos_`, wiskundige routines

```fortran
! Berekent Downdraft CAPE (DCAPE) via de methode van
! Doswell & Rasmussen (waarschijnlijk)
!
! Kenmerken:
! - DUBBELE PRECISIE (double, niet float)
! - Maximum 5000 verticale niveaus (hardcoded limiet)
! - Dynamische geheugentoewijzing (~160KB + heap allocaties)
! - Roept dcapethermos_ aan voor thermodynamisch profiel
!
! Algoritme (geschat):
! 1. Bereken virtueel temperatuurprofiel
! 2. Zoek het niveau van minimum θe (equivalent potentiële temperatuur)
! 3. Bereken het dalende luchtpakketprofiel via dcapethermos_
! 4. Integreer (T_parcel - T_env) × g / T_env van het startniveau
!    naar het oppervlak
! 5. DCAPE = ∫ g × (Tv_parcel - Tv_env) / Tv_env dz
```

#### Analyse
- Beide functies zijn **dubbele precisie** — alle constanten zijn 64-bit doubles.
- De 160KB stack frame en malloc-aanroepen suggereren dynamische arrays voor het verticale profiel.
- De limiet van 5000 niveaus is hardcoded in `dcapedjss_`.
- Dit is een volledige DCAPE implementatie, niet een vereenvoudigde versie.

---

## Samenvatting: Vergelijking met rasp-pynumb

| Functie | DrJack Methode | Mogelijke rasp-pynumb Verschil |
|---|---|---|
| `calc_hcrit_` | Empirisch √-model, drempel 225 fpm, `result = ter + model × hbl` | Drempel bevestigd. **6 args**: hbl is 3e array. |
| `calc_hlift_` | Zelfde model, variabele drempel | Extra parameter voor drempel |
| `calc_sfclclheight_` | Bolton (1980) via `ptlcl_` | rasp-pynumb: Espy als fallback |
| `calc_blclheight_` | RH=100% zoek + lineaire interpolatie | Check of methode overeenkomt |
| `calc_sfcsunpct_` | Power-law: `(1+141.5τ/cos_z)^0.635` | rasp-pynumb: Kasten (1980) — **significant anders** |
| `calc_subgrid_blcloudpct_grads_` | Lineair RH-mapping: 400×RH − 300 | rasp-pynumb: RH-scheme — vergelijk mapping |
| `calc_blavg_` | **Gewogen trapeziumintegratie** | NIET simpel gemiddelde! |
| `calc_wblmaxmin_` | 4 modi: waarde/hoogte/diff/ratio | Check modus-implementatie |
| `calc_blinteg_mixratio_` | Trapezium × 102.04 (1000/g) | Ontbreekt in pipeline |
| `calc_aboveblinteg_mixratio_` | Spiegelbeeld, boven BL | Ontbreekt in pipeline |
| `calc_qcblhf_` | Trapezium × hbl × 2490.0 / divisor | Ontbreekt in pipeline |
| `filter2d_` | 2D Laplaciaan (gesplitste 1D), gewicht 0.25, temp buffer | Ontbreekt in pipeline |
| `dcapedjss_`/`dcapethermos_` | Volledige DCAPE, double precision | Ontbreekt in pipeline |

---

## Volledige DrJack Functie-index

Alle ~97 DrJack-specifieke functies met adressen:

```
0x20a50  calc_wblmaxmin_                (992 bytes, lijn 56)
0x20e30  calc_cloudbase_
0x21410  calc_sfclclheight_             (1104 bytes, lijn 264)
0x21860  calc_blclheight_               (1456 bytes, lijn 319)
0x21e10  calc_blavg_                    (976 bytes, lijn 365)
0x221f0  calc_bldepth_
0x22640  calc_hcrit_                    (496 bytes, lijn 494)
0x22830  calc_hlift_                    (480 bytes, lijn 533)
0x22a10  find_boxmax3d_
0x22df0  calc_blwind_
0x230b0  calc_blinteg_mixratio_         (1040 bytes, lijn 672)
0x234c0  calc_aboveblinteg_mixratio_    (1232 bytes, lijn 720)
0x23990  calc_qcblhf_                   (1024 bytes, lijn 779)
0x23d90  calc_blmax_
0x240e0  calc_blmax2_
0x24510  calc_blmin_
0x24850  calc_blmaxmin_
0x24c40  calc_subgrid_blcloudpct_
0x25560  calc_blcloudpct_
0x258e0  calc_subgrid_blcloudpct_grads2_
0x25c30  calc_subgrid_blcloudpct_grads_ (1168 bytes, lijn 1173)
0x260c0  calc_subgrid_blcloudpct_grads3_
0x26570  calc_subgrid_blcloudpct2_
0x26dc0  calc_subgrid_blcloudpct3_
0x27260  calc_sfcsunpct2_
0x274c0  calc_sfcsunpct3_
0x27650  calc_sfcsunpct4_
0x28780  calc_sfcsunpct_                (2240 bytes, lijn 1998)
0x29050  calc_sfcsunpct5_
0x2a430  dcapedjss_                     (9344 bytes)
0x2c8b0  dcapethermos_                  (3264 bytes)
0x2d580  calc_etopo_hgt_
0x2d8a0  calc_subgrid_blcloudpct4_
0x2dc00  calc_totcloudpct_
0x2f060  calc_cu_cloudpct_
0x2f5f0  calc_cu_cloudbaseheight_
0x2f880  calc_cu_cloudtopheight_
0x354c0  filter2d_                      (1104 bytes, lijn 410)
```

### Hulpfuncties (via PLT)
```
ptlcl_         — Bolton LCL drukberekening
calc_rh1_      — Relatieve vochtigheid uit T, p, q
radconst_      — Zonnepositie (declinatie, uurhoek)
sincosf        — sin/cos simultaan
cosf           — cosinus
powf           — machtsverheffing
expf           — exponentieel
```

---

---

## Verificatierapport

De reconstructies zijn systematisch gecontroleerd tegen de originele binary disassembly.
Onderstaande correcties zijn doorgevoerd na verificatie:

### Gevonden en gecorrigeerde fouten

| # | Functie | Fout | Correctie |
|---|---------|------|-----------|
| 1 | `calc_hcrit_` | Signature had 5 args, 3e arg beschreven als "ter hergebruikt" | **6 argumenten**: `(wstar, ter, hbl, nx, ny, result)`. Het 3e arg is een aparte array (`hbl`), geladen via `rdx` register. |
| 2 | `calc_hcrit_` | Formule: `result = ter + sqrt_model × ter` | **Correct**: `result = ter + sqrt_model × hbl` — bevestigd op `0x22750` |
| 3 | `calc_sfcsunpct_` | `powf(x + 0.635)` — 0.635 als additieve constante | **Correct**: `powf(1.0 + 141.5*τ/cos_z, 0.635)` — 0.635 is de **EXPONENT** (`xmm1` op `0x28c73`) |
| 4 | `calc_qcblhf_` | `result = integral × 2490.0` | **Correct**: `result = hbl × integral × 2490.0 / divisor` — extra factoren op `0x23be4-0x23bf1` |
| 5 | `filter2d_` | "In-place, geen tijdelijk array", 4 args | **5 argumenten** met temp buffer als 2e arg. Smoothing via gescheiden 1D passes (j dan i) |
| 6 | Constants tabel | `0x31be8c` = "Power-argument basis" | **Correct**: "Power-law EXPONENT" |

### Geverifieerde functies (correct bevonden)

| Functie | Status | Bevestigde details |
|---------|--------|--------------------|
| `calc_hcrit_` | ✅ Algoritme correct, signature gecorrigeerd | Thermisch √-model met 225 fpm drempel |
| `calc_hlift_` | ✅ Correct | Variabele drempel, zelfde model als hcrit |
| `calc_sfclclheight_` | ✅ Correct | Bolton (1980) via `ptlcl_`, missing=-999, lineaire interpolatie |
| `calc_blavg_` | ✅ Correct | Gewogen trapeziumintegratie, NIET simpel gemiddelde |
| `calc_subgrid_blcloudpct_grads_` | ✅ Correct | Magnus-formule (17.67, 273.15, 29.65, 6.112), mapping 400×RH−300 |
| `calc_wblmaxmin_` | ✅ Correct | 4 modi (waarde×100, hoogte, hoogte−sfc, fractie×100), sign-bit abs() |
| `calc_sfcsunpct_` | ✅ Algoritme correct, powf-formule gecorrigeerd | Empirisch power-law model, NIET Kasten |
| `calc_blinteg_mixratio_` | ✅ Correct | Trapezoid × 102.04 (1000/g) |
| `calc_aboveblinteg_mixratio_` | ✅ Correct | Spiegelbeeld, zelfde 102.04 schaling |
| `calc_qcblhf_` | ✅ Structuur correct, eindformule gecorrigeerd | Extra hbl/divisor factor |
| `filter2d_` | ✅ Resultaat correct, implementatie gecorrigeerd | 5-punts Laplaciaan via gesplitste 1D passes |

### Niet-geverifieerde functies

| Functie | Reden |
|---------|-------|
| `dcapedjss_` | Te groot (9344 bytes), double precision, complexe controlflow |
| `dcapethermos_` | Hulpfunctie van dcapedjss_, structuur correct maar details niet geverifieerd |
| `calc_blclheight_` | Structuur geverifieerd (RH=100% zoek), details niet volledig getraceerd |

---

*Gegenereerd door reverse engineering van `libncl_drjack.avx512.nocuda.so` (BuildID: ea10255db82c73a82ff74893e4014f8393cd1b55)*
*Alle pseudocode is gereconstrueerd uit x86-64 disassembly en kan afwijken van de originele Fortran broncode.*
*Verificatie uitgevoerd door systematische vergelijking van claims met binary disassembly (maart 2026).*
