"""The statistical verdict. One implementation, imported everywhere.

Extracted from bench/run.py so the DTU-based ablation harness cannot drift from
the local overhead benchmark. There is exactly one place in this repo that
decides whether a difference is real, and this is it.

The rule this module enforces, from context/methodology/evidence-standards.md:

    positive      strictly positive effect, adequately powered
    no-effect     adequately powered AND the effect is below detectable
    inconclusive  underpowered -- the test could not have found the effect

`inconclusive` means KEEP LOOKING. It does not mean "no effect". Accepting the
null from a test that could never have rejected it is how a benchmark lies, and
this repo's own harness did exactly that once (commit dd34bcb) before this
function required significance as well as effect size.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

MIN_N_PER_ARM = 5
MEDIUM_EFFECT = 0.5  # |Cohen's d| below this is not distinguishable from noise


@dataclass
class Comparison:
    verdict: str  # positive | no-effect | inconclusive
    detail: str
    n_control: int
    n_treat: int
    mean_control: float
    mean_treat: float
    delta: float
    delta_pct: float
    cohens_d: float
    welch_t: float
    df: float
    significant: bool


def _crit(df: float) -> float:
    """Two-sided ~p<0.05 critical value. Conservative, dependency-free."""
    if df < 6:
        return 2.57
    if df < 8:
        return 2.45
    if df < 10:
        return 2.31
    if df < 20:
        return 2.09
    return 1.96


def compare(
    control: list[float], treat: list[float], n_min: int = MIN_N_PER_ARM
) -> Comparison:
    """Compare two arms. Requires BOTH a meaningful effect size AND significance."""
    nc, nt = len(control), len(treat)
    if nc < n_min or nt < n_min or nc < 2 or nt < 2:
        return Comparison(
            "inconclusive",
            f"n={min(nc, nt)} < {n_min} per arm",
            nc,
            nt,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            False,
        )

    mc, mt = statistics.mean(control), statistics.mean(treat)
    sc, st = statistics.stdev(control), statistics.stdev(treat)
    delta = mt - mc
    pct = (delta / mc * 100) if mc else 0.0
    pooled = ((sc**2 + st**2) / 2) ** 0.5
    d = delta / pooled if pooled else 0.0

    se = (sc**2 / nc + st**2 / nt) ** 0.5
    if se == 0:
        v = "no-effect" if delta == 0 else "positive"
        return Comparison(
            v, "zero variance", nc, nt, mc, mt, delta, pct, d, 0.0, 0.0, delta != 0
        )

    t = delta / se
    df = (sc**2 / nc + st**2 / nt) ** 2 / (
        (sc**2 / nc) ** 2 / (nc - 1) + (st**2 / nt) ** 2 / (nt - 1)
    )
    sig = abs(t) >= _crit(df)
    detail = f"delta={delta:+.3f} ({pct:+.1f}%)  d={d:+.2f}  t={t:.2f} df={df:.1f}"

    if sig and abs(d) >= MEDIUM_EFFECT:
        verdict = "positive"
    elif not sig and abs(d) >= MEDIUM_EFFECT:
        # Looks real, cannot be established. NOT no-effect.
        verdict = "inconclusive"
        detail += "  (d is large but n is too small to confirm)"
    else:
        verdict = "no-effect"

    return Comparison(verdict, detail, nc, nt, mc, mt, delta, pct, d, t, df, sig)


def required_n(control: list[float], target_d: float = MEDIUM_EFFECT) -> int:
    """Rough n per arm needed to detect `target_d` at ~80% power, p<0.05.

    The 15.7 constant is 2*(1.96+0.84)^2. Use it to state up front what the
    experiment can and cannot see, rather than discovering it afterwards.
    """
    if len(control) < 2 or target_d <= 0:
        return MIN_N_PER_ARM
    return max(MIN_N_PER_ARM, int(15.7 / (target_d**2)) + 1)
