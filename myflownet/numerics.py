"""Small numerical helpers (no SciPy dependency)."""
from __future__ import annotations

import math


def brentq(f, a: float, b: float, xtol: float = 1e-14, rtol: float = 1e-12, maxiter: int = 200,
           fa: float | None = None, fb: float | None = None) -> float:
    """Brent's root finder.  f(a) and f(b) must bracket a root."""
    fa = f(a) if fa is None else fa
    fb = f(b) if fb is None else fb
    if fa == 0.0:
        return a
    if fb == 0.0:
        return b
    if (fa > 0) == (fb > 0):
        raise ValueError("brentq: root not bracketed")
    c, fc = a, fa
    d = e = b - a
    for _ in range(maxiter):
        if (fb > 0) == (fc > 0):
            c, fc = a, fa
            d = e = b - a
        if abs(fc) < abs(fb):
            a, b, c = b, c, b
            fa, fb, fc = fb, fc, fb
        tol = 2.0 * rtol * abs(b) + 0.5 * xtol
        m = 0.5 * (c - b)
        if abs(m) <= tol or fb == 0.0:
            return b
        if abs(e) >= tol and abs(fa) > abs(fb):
            s = fb / fa
            if a == c:
                p = 2.0 * m * s
                q = 1.0 - s
            else:
                q = fa / fc
                r = fb / fc
                p = s * (2.0 * m * q * (q - r) - (b - a) * (r - 1.0))
                q = (q - 1.0) * (r - 1.0) * (s - 1.0)
            if p > 0:
                q = -q
            else:
                p = -p
            if 2.0 * p < min(3.0 * m * q - abs(tol * q), abs(e * q)):
                e = d
                d = p / q
            else:
                d = m
                e = m
        else:
            d = m
            e = m
        a, fa = b, fb
        if abs(d) > tol:
            b += d
        else:
            b += math.copysign(tol, m)
        fb = f(b)
    return b


def bisect_feasible(feasible, lo: float, hi: float, iters: int = 60) -> float:
    """Largest x in [lo, hi] with feasible(x) True, assuming monotone feasibility
    (feasible(lo) True)."""
    if feasible(hi):
        return hi
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if feasible(mid):
            lo = mid
        else:
            hi = mid
    return lo
