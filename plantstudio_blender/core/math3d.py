"""Math helpers ported from PlantStudio's umath.py (subset needed for growth)."""

import math


def min(a, b):
    return a if a < b else b


def max(a, b):
    return a if a > b else b


def safediv(x, y):
    if y == 0:
        return 0
    return x / y


def safedivExcept(x, y, exceptionResult):
    if y == 0:
        return exceptionResult
    return x / y


def safeLn(x):
    if x <= 0:
        return 0.0
    return math.log(x)


def scurve(x, c1, c2):
    """PlantStudio s-curve: y = x / (x + exp(c1 - c2*x))."""
    try:
        temp = c1 - c2 * x
        if temp > 85.0:
            temp = 85.0
        return safediv(x, x + math.exp(temp))
    except (ValueError, OverflowError):
        return x


def calcSCurveCoeffs(sCurve):
    """
    Compute c1/c2 from the 4-param s-curve definition.
    PlantStudio: c2 = (ln(x1/y1 - x1) - ln(x2/y2 - x2)) / (x2 - x1); c1 = ln(x1/y1 - x1) + x1*c2
    """
    try:
        if (sCurve.x1 <= 0.0) or (sCurve.y1 <= 0.0) or (sCurve.x2 <= 0.0) or (sCurve.y2 <= 0.0) \
                or (sCurve.x1 >= 1.0) or (sCurve.y1 >= 1.0) or (sCurve.x2 >= 1.0) or (sCurve.y2 >= 1.0):
            sCurve.x1 = 0.25
            sCurve.y1 = 0.1
            sCurve.x2 = 0.65
            sCurve.y2 = 0.85
        xx = safeLn(safediv(sCurve.x1, sCurve.y1) - sCurve.x1)
        sCurve.c2 = safediv(xx - safeLn(safediv(sCurve.x2, sCurve.y2) - sCurve.x2),
                            sCurve.x2 - sCurve.x1)
        sCurve.c1 = xx + sCurve.x1 * sCurve.c2
    except (ValueError, ZeroDivisionError):
        sCurve.x1 = 0.25
        sCurve.y1 = 0.1
        sCurve.x2 = 0.65
        sCurve.y2 = 0.85
        sCurve.c1 = 0.0
        sCurve.c2 = 0.0


def linearGrowthWithFactor(current, optimal, minDays, growthFactor):
    """One day of linear growth toward optimal, scaled by growthFactor."""
    if current >= optimal:
        return current
    if minDays <= 0:
        return optimal
    return current + (optimal - current) * growthFactor / minDays


def linearGrowth(current, optimal, minDays):
    return linearGrowthWithFactor(current, optimal, minDays, 1.0)


def linearGrowthResult(current, optimal, minDays):
    """Daily biomass DEMAND increment toward optimal — exact port of the
    original utravers.linearGrowthResult.

    Original:
        amountNeeded = optimal - current
        maxPossible  = safedivExcept(optimal, minDays, optimal)
        amountNeeded = max(0.0, min(amountNeeded, maxPossible))
        result = amountNeeded

    Returns the clamped per-day increment (0 when current >= optimal), NOT
    the new total. Callers add this to liveBiomass, so returning the new
    total would double-count the existing biomass and run away (e.g. an
    inflorescence reaching liveBiomass 127 against optimal 0.83).
    """
    if minDays <= 0:
        maxPossible = optimal
    else:
        maxPossible = optimal / minDays
    amountNeeded = optimal - current
    return max(0.0, min(amountNeeded, maxPossible))


class SCurve:
    """4-param S-curve: x1 y1 x2 y2 + computed c1 c2."""

    def __init__(self, x1=0.25, y1=0.1, x2=0.65, y2=0.85):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.c1 = 0.0
        self.c2 = 0.0
        calcSCurveCoeffs(self)

    def __repr__(self):
        return f"SCurve({self.x1},{self.y1},{self.x2},{self.y2})"
