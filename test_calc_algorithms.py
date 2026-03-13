"""Unit tests for DrJack-matched calculation algorithms.

Tests thermal penetration model, BL cloud fraction, and sfcsunpct
against expected values derived from the reverse-engineered Fortran constants.
"""

import math
import numpy as np
import pytest

from icon_d2_pipeline.calc.thermal import (
    calc_wstar, calc_hcrit, calc_hlift, _drjack_height_frac,
    _MS_TO_FPM, _HCRIT_THRESHOLD, _ALPHA1, _ALPHA2, _ALPHA3, _ALPHA4, _ALPHA5,
)
from icon_d2_pipeline.calc.cloud import calc_blcloudpct
from icon_d2_pipeline.calc.surface import calc_sfcsunpct


# --- Thermal penetration model ---

class TestDrjackHeightFrac:
    """Test the sqrt-based thermal penetration model from Fortran binary."""

    def test_moderate_thermal(self):
        """wstar=3 m/s (590.55 fpm), threshold=225 fpm."""
        wstar_fpm = np.array([3.0 * _MS_TO_FPM])
        frac = _drjack_height_frac(225.0, wstar_fpm)
        # ratio = 225/590.55 = 0.38099
        # inner = 1.3674*(0.4549 - 0.463*0.38099) + 0.01267 = 0.39352
        # frac = sqrt(0.39352) + 0.1126 = 0.73991
        assert frac[0] == pytest.approx(0.7399, abs=0.001)

    def test_strong_thermal(self):
        """wstar=5 m/s (984.25 fpm) — strong thermal, high penetration."""
        wstar_fpm = np.array([5.0 * _MS_TO_FPM])
        frac = _drjack_height_frac(225.0, wstar_fpm)
        # ratio = 225/984.25 = 0.22864
        # inner = 1.3674*(0.4549 - 0.463*0.22864) + 0.01267 = 0.48972
        # frac = sqrt(0.48972) + 0.1126 = 0.81258
        assert frac[0] == pytest.approx(0.8126, abs=0.001)

    def test_barely_above_threshold(self):
        """wstar just above 225 fpm threshold — low penetration."""
        wstar_fpm = np.array([230.0])
        frac = _drjack_height_frac(225.0, wstar_fpm)
        # ratio ≈ 0.978, close to 1 → low height fraction
        assert frac[0] > 0.0
        assert frac[0] < 0.5

    def test_hlift_175_threshold(self):
        """calc_hlift with 175 fpm threshold (experimental1)."""
        wstar_fpm = np.array([3.0 * _MS_TO_FPM])
        frac = _drjack_height_frac(175.0, wstar_fpm)
        # Lower threshold → higher penetration than hcrit
        frac_225 = _drjack_height_frac(225.0, wstar_fpm)
        assert frac[0] > frac_225[0]


class TestCalcHcrit:
    """Test hcrit end-to-end."""

    def test_strong_wstar(self):
        """Strong thermal: result = ter + frac * pblh, well above terrain."""
        wstar = np.array([[3.0]])
        ter = np.array([[200.0]])
        pblh = np.array([[1500.0]])
        result = calc_hcrit(wstar, ter, pblh)
        # frac ≈ 0.7399, result ≈ 200 + 0.7399*1500 ≈ 1310
        assert result[0, 0] == pytest.approx(1310, abs=5)

    def test_weak_wstar_returns_terrain(self):
        """Weak thermal below threshold → returns terrain height."""
        wstar = np.array([[0.5]])  # 0.5 m/s = 98 fpm < 225
        ter = np.array([[300.0]])
        pblh = np.array([[1000.0]])
        result = calc_hcrit(wstar, ter, pblh)
        assert result[0, 0] == pytest.approx(300.0)

    def test_zero_wstar(self):
        """No thermals → terrain height."""
        wstar = np.array([[0.0]])
        ter = np.array([[150.0]])
        pblh = np.array([[800.0]])
        result = calc_hcrit(wstar, ter, pblh)
        assert result[0, 0] == pytest.approx(150.0)

    def test_result_not_negative(self):
        """Result is clamped to >= 0."""
        wstar = np.array([[0.0]])
        ter = np.array([[-50.0]])  # Dead Sea
        pblh = np.array([[500.0]])
        result = calc_hcrit(wstar, ter, pblh)
        assert result[0, 0] >= 0.0


class TestCalcHlift:
    """Test hlift with variable threshold."""

    def test_hlift_above_hcrit(self):
        """175 fpm threshold gives higher usable altitude than 225 fpm."""
        wstar = np.array([[3.0]])
        ter = np.array([[200.0]])
        pblh = np.array([[1500.0]])
        hcrit = calc_hcrit(wstar, ter, pblh)
        hlift = calc_hlift(175.0, wstar, ter, pblh)
        assert hlift[0, 0] > hcrit[0, 0]


# --- BL cloud fraction ---

class TestCalcBlcloudpct:
    """Test DrJack's linear RH→cloud mapping: clamp(400*RH - 300, 0, 95)."""

    def _make_uniform_bl(self, rh_target, nz=5, ny=1, nx=1):
        """Create synthetic BL with uniform RH at all levels."""
        tc = np.full((nz, ny, nx), 15.0, dtype=np.float32)  # 15°C
        pmb = np.full((nz, ny, nx), 850.0, dtype=np.float32)  # 850 hPa

        # es = 6.112 * exp(17.67 * 15 / (15 + 243.5)) = 17.044 hPa
        es = 6.112 * np.exp(17.67 * 15.0 / (15.0 + 243.5))
        qs = 0.622 * es / (850.0 - 0.378 * es)
        qvapor = np.full((nz, ny, nx), rh_target * qs, dtype=np.float32)
        qcloud = np.zeros((nz, ny, nx), dtype=np.float32)

        z = np.zeros((nz, ny, nx), dtype=np.float32)
        for k in range(nz):
            z[k] = 500.0 + k * 200.0  # 500-1300m MSL

        ter = np.full((ny, nx), 100.0, dtype=np.float32)
        pblh = np.full((ny, nx), 1500.0, dtype=np.float32)  # BL top at 1600m

        return qvapor, qcloud, tc, pmb, z, ter, pblh

    def test_dry_bl_zero_cloud(self):
        """RH=50% → well below 75% threshold → 0% cloud."""
        args = self._make_uniform_bl(0.50)
        result = calc_blcloudpct(*args)
        assert result[0, 0] == pytest.approx(0.0, abs=0.1)

    def test_rh_at_threshold(self):
        """RH=75% → 400*0.75 - 300 = 0% (threshold)."""
        args = self._make_uniform_bl(0.75)
        result = calc_blcloudpct(*args)
        assert result[0, 0] == pytest.approx(0.0, abs=1.0)

    def test_rh_85_gives_40pct(self):
        """RH=85% → 400*0.85 - 300 = 40%."""
        args = self._make_uniform_bl(0.85)
        result = calc_blcloudpct(*args)
        assert result[0, 0] == pytest.approx(40.0, abs=2.0)

    def test_saturated_caps_at_95(self):
        """RH=100% → 400*1.0 - 300 = 100 → capped at 95%."""
        args = self._make_uniform_bl(1.0)
        result = calc_blcloudpct(*args)
        assert result[0, 0] == pytest.approx(95.0, abs=1.0)

    def test_max_over_levels(self):
        """Result is the maximum cloud fraction over BL levels, not average."""
        # Create BL with one moist level and rest dry
        nz, ny, nx = 5, 1, 1
        tc = np.full((nz, ny, nx), 15.0, dtype=np.float32)
        pmb = np.full((nz, ny, nx), 850.0, dtype=np.float32)
        es = 6.112 * np.exp(17.67 * 15.0 / (15.0 + 243.5))
        qs = 0.622 * es / (850.0 - 0.378 * es)

        qvapor = np.full((nz, ny, nx), 0.5 * qs, dtype=np.float32)  # dry
        qvapor[2] = 0.90 * qs  # one moist level: RH=90% → 60%
        qcloud = np.zeros((nz, ny, nx), dtype=np.float32)

        z = np.zeros((nz, ny, nx), dtype=np.float32)
        for k in range(nz):
            z[k] = 500.0 + k * 200.0
        ter = np.full((ny, nx), 100.0, dtype=np.float32)
        pblh = np.full((ny, nx), 1500.0, dtype=np.float32)

        result = calc_blcloudpct(qvapor, qcloud, tc, pmb, z, ter, pblh)
        # Should reflect the max (RH=0.90 → 60%), not average
        assert result[0, 0] == pytest.approx(60.0, abs=3.0)


# --- Surface sun percentage ---

class TestCalcSfcsunpct:
    """Test solar geometry and below-horizon behavior."""

    def _make_solar_inputs(self, swdown_val, gmthr, jday=172):
        """Create inputs for a single gridpoint at ~52°N, 5°E (Netherlands)."""
        ny, nx = 1, 1
        nz = 3
        swdown = np.full((ny, nx), swdown_val, dtype=np.float32)
        lat = np.array([52.0])
        lon = np.array([5.0])
        ter = np.full((ny, nx), 10.0, dtype=np.float32)
        z = np.zeros((nz, ny, nx), dtype=np.float32)
        for k in range(nz):
            z[k] = 100.0 + k * 500.0
        pmb = np.array([[[1000.0]], [[850.0]], [[700.0]]], dtype=np.float32)
        tc = np.array([[[15.0]], [[5.0]], [[-5.0]]], dtype=np.float32)
        qvapor = np.full((nz, ny, nx), 0.005, dtype=np.float32)
        return swdown, jday, gmthr, lat, lon, ter, z, pmb, tc, qvapor

    def test_below_horizon_returns_minus999(self):
        """Sun below horizon (midnight) → -999.0."""
        args = self._make_solar_inputs(0.0, gmthr=0.0, jday=172)
        result = calc_sfcsunpct(*args)
        assert result[0, 0] == pytest.approx(-999.0)

    def test_midday_summer_high_sun(self):
        """Solar noon in summer, full clear sky → near 100%."""
        # At solar noon, clear sky swdown ≈ clear_sky radiation
        # We set swdown equal to what clear sky would give
        args = self._make_solar_inputs(800.0, gmthr=11.67, jday=172)
        result = calc_sfcsunpct(*args)
        # Should be high (near 100%) since swdown matches clear sky
        assert 50.0 < result[0, 0] <= 100.0

    def test_overcast_gives_low_pct(self):
        """Midday with very low swdown → low sun percentage."""
        args = self._make_solar_inputs(50.0, gmthr=12.0, jday=172)
        result = calc_sfcsunpct(*args)
        assert result[0, 0] < 30.0

    def test_winter_night_returns_minus999(self):
        """Winter evening at 52°N → below horizon."""
        args = self._make_solar_inputs(0.0, gmthr=18.0, jday=355)
        result = calc_sfcsunpct(*args)
        assert result[0, 0] == pytest.approx(-999.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])