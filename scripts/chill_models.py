"""Chill models computed from hourly air temperature in degrees F.

Usage: from chill_models import chill_hours, hours_below, utah_units, dynamic_portions
Each takes a pandas Series of hourly deg F (index = hour timestamps, NaN = missing) and
returns a Series of per-hour increments, so daily/seasonal totals are just sums:
  chill_hours      - 1 if 32 <= T <= 45F
  hours_below      - 1 if T < 45F
  utah_units       - Richardson et al. 1974 (thresholds converted to F)
  dynamic_portions - Fishman/Erez Dynamic model, chillR Dynamic_Model parameters. Path
                     dependent: pass a series that starts at the accumulation start (Sep 1).
Missing hours contribute 0 (Dynamic: the state is carried over unchanged; matches FNRIC).
Feed CIMIS data through hour_beginning() before daily() so days line up with FNRIC.
"""

import numpy as np
import pandas as pd

E0, E1, A0, A1, SLP, TETMLT = 4153.5, 12888.8, 139500.0, 2.567e18, 1.6, 277.0


def f_to_c(f):
    return (f - 32) * 5 / 9


def chill_hours(t, lo=32, hi=45):
    # FNRIC convention (matches exactly): lo < T <= hi
    return ((t > lo) & (t <= hi)).astype(float)


def hours_below(t, hi=45):
    # FNRIC's "hours < 45" is actually T <= 45 (matches exactly)
    return (t <= hi).astype(float)


def utah_units(t):
    # Richardson bins in F, upper-inclusive (T <= edge stays in the lower bin); this
    # reproduces FNRIC to within ~0.01 units/day.
    edges = [34, 36, 48, 54, 60, 65]
    vals = np.array([0, 0.5, 1, 0.5, 0, -0.5, -1])
    u = pd.Series(vals[np.searchsorted(edges, t.values, side="left")], index=t.index)
    return u.where(t.notna(), 0.0)


def hour_beginning(t):
    """CIMIS stamps are hour-ending PST (0100..2400). FNRIC labels each reading by the
    hour it ends, minus 1h, so 2400 belongs to the same calendar day. Dynamic model
    then matches exactly."""
    return t.set_axis(t.index - pd.Timedelta(hours=1))


def dynamic_portions(t):
    """Hourly chill-portion increments from the Dynamic model (one step per index entry)."""
    tk = f_to_c(t.values.astype(float)) + 273.0
    out = np.zeros(len(tk))
    aa, ee = A0 / A1, E1 - E0
    e = 0.0
    for i, k in enumerate(tk):
        if np.isnan(k):
            continue
        sr = np.exp(SLP * TETMLT * (k - TETMLT) / k)
        xi = sr / (1 + sr)
        xs = aa * np.exp(ee / k)
        ak1 = A1 * np.exp(-E1 / k)
        e = xs - (xs - e) * np.exp(-ak1)
        if e >= 1:
            out[i] = xi * e
            e -= out[i]
    return pd.Series(out, index=t.index)


def daily(t, models=("hours_32_45", "hours_lt_45", "units_utah", "portions_dynamic")):
    """Daily table of all models for one hourly series (accumulation starts at first index)."""
    fn = dict(hours_32_45=chill_hours, hours_lt_45=hours_below, units_utah=utah_units,
              portions_dynamic=dynamic_portions)
    d = pd.DataFrame({m: fn[m](t) for m in models})
    d["n_hours"] = t.notna().astype(int)
    return d.groupby(d.index.normalize()).sum()
