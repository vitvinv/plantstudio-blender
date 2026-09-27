"""Growth-% mirror math: percent of full growth <-> age in days.

Pure Python (no bpy) so headless code and tests can use it. The Blender
side stores these as the `ps_pct` / `ps_maturity` custom properties on
each plant object (see scene_bridge.py / animator.py).
"""

# ps_pct mirrors ps_day as a percent of the plant's full-growth day
# (ps_maturity). Stored per plant object so it can be keyed or
# driver-driven like ps_day; a driver on ps_pct wins over ps_day (see
# animator.reconcile_growth).
PCT_PROP = "ps_pct"
PCT_SCALE = 1000  # 0.1% steps keep the days<->% round trip exact


def pct_for_days(day, maturity):
    """Percent of full growth (0..100 in 1/PCT_SCALE steps) for a day count."""
    if maturity <= 0:
        return 0.0
    day = max(0, int(day))
    maturity = max(1, int(maturity))
    if day >= maturity:
        return 100.0
    if day <= 0:
        return 0.0
    # pick a pct inside the interval that maps back to this exact day
    # (day(i) = i*maturity//PCT_SCALE for i = pct in 0.1% steps), so
    # days->pct->days is the identity and mirroring never drifts
    lo = -(-day * PCT_SCALE // maturity)          # first 0.1% step of day
    hi = -(-(day + 1) * PCT_SCALE // maturity) - 1  # last step inside day
    mid = min(PCT_SCALE, (lo + hi) // 2)
    return mid / (PCT_SCALE / 100.0)


def days_for_pct(pct, maturity):
    """Days for a stored pct — exact inverse of pct_for_days."""
    if maturity <= 0:
        return 0
    maturity = max(1, int(maturity))
    i = max(0, min(PCT_SCALE, int(round(float(pct) * PCT_SCALE / 100.0))))
    return min(int(maturity), (i * maturity * 100) // (PCT_SCALE * 100))
