"""Small physics helpers shared by the simulator and the feature pipeline."""
from __future__ import annotations

import numpy as np


def sat_vapor_pressure_hpa(t_c):
    """Magnus formula (WMO), over water."""
    t_c = np.asarray(t_c, dtype=float)
    return 6.112 * np.exp(17.62 * t_c / (243.12 + t_c))


def abs_humidity_gm3(t_c, rh_pct):
    return 216.7 * (np.asarray(rh_pct) / 100.0) * sat_vapor_pressure_hpa(t_c) / (np.asarray(t_c) + 273.15)


def rh_from_abs_humidity(t_c, ah_gm3):
    rho_sat = 216.7 * sat_vapor_pressure_hpa(t_c) / (np.asarray(t_c) + 273.15)
    return np.clip(100.0 * np.asarray(ah_gm3) / rho_sat, 0.0, 100.0)


def dew_point_c(t_c, rh_pct):
    rh = np.clip(np.asarray(rh_pct, dtype=float), 0.1, 100.0)
    t_c = np.asarray(t_c, dtype=float)
    g = np.log(rh / 100.0) + 17.62 * t_c / (243.12 + t_c)
    return 243.12 * g / (17.62 - g)


CU_ALPHA = 0.00393  # 1/K, copper resistivity temperature coefficient
CU_REF_C = 50.0     # normalisation point, so the fitted `a` stays "rise at rated current"


def copper_factor(t_c):
    """R(T)/R(T_ref) for copper: makes the thermal model valid outside the commissioning load range."""
    return (1 + CU_ALPHA * (np.asarray(t_c, dtype=float) - 20.0)) / (1 + CU_ALPHA * (CU_REF_C - 20.0))


def first_order(x: np.ndarray, t_min: np.ndarray, tau_min: float) -> np.ndarray:
    """First-order low-pass (thermal RC) with irregular sampling; NaNs hold the state."""
    x = np.asarray(x, dtype=float)
    y = np.empty_like(x)
    state = np.nan
    prev_t = None
    for i, (xi, ti) in enumerate(zip(x, t_min)):
        if np.isnan(state):
            state = xi
        elif not np.isnan(xi):
            a = 1.0 - np.exp(-(ti - prev_t) / tau_min)
            state = state + a * (xi - state)
        y[i] = state
        prev_t = ti
    return y
