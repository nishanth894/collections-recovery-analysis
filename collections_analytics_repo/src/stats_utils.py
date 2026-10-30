"""Small, transparent statistical helpers (no black boxes). All unit-tested in tests/test_stats_utils.py."""
import numpy as np
import pandas as pd
from scipy import stats


def bh_adjust(pvals):
    """Benjamini-Hochberg FDR-adjusted p-values (same order as input)."""
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order] * n / (np.arange(n) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.minimum(ranked, 1.0)
    return out


def chi2_homogeneity(df, dim, outcome):
    """Chi-square test that P(outcome=1) is equal across levels of `dim`."""
    ct = pd.crosstab(df[dim], df[outcome])
    chi, p, dof, _ = stats.chi2_contingency(ct)
    rates = df.groupby(dim, observed=True)[outcome].mean()
    return {"levels": int(len(rates)), "min_rate": float(rates.min()), "max_rate": float(rates.max()),
            "spread_pp": float((rates.max() - rates.min()) * 100), "chi2": float(chi), "p": float(p)}


def overdispersion_test(successes, trials):
    """Is variance across units (e.g. agents) larger than binomial noise around the pooled rate?"""
    s, n = np.asarray(successes, float), np.asarray(trials, float)
    p0 = s.sum() / n.sum()
    chi = (((s - n * p0) ** 2) / (n * p0 * (1 - p0))).sum()
    dof = len(s) - 1
    return {"chi2": float(chi), "dof": int(dof), "p": float(1 - stats.chi2.cdf(chi, dof))}


def shift_share(df, stratum, period, p0, p1, value, weight):
    """Kitagawa decomposition of change in a weighted-average rate between two periods.
    rate_p = sum_s share_{s,p} * rate_{s,p}.  total = mix effect + rate effect (+ interaction folded into rate).
    value = numerator column, weight = denominator column (summed within stratum x period)."""
    g = df[df[period].isin([p0, p1])].groupby([stratum, period])[[value, weight]].sum().unstack(period)
    w0, w1 = g[(weight, p0)], g[(weight, p1)]
    r0, r1 = g[(value, p0)] / w0, g[(value, p1)] / w1
    s0, s1 = w0 / w0.sum(), w1 / w1.sum()
    total = (s1 * r1).sum() - (s0 * r0).sum()
    mix = ((s1 - s0) * r0).sum()
    rate = (s1 * (r1 - r0)).sum()
    return {"rate_p0": float((s0 * r0).sum()), "rate_p1": float((s1 * r1).sum()), "total_change": float(total),
            "mix_effect": float(mix), "rate_effect": float(rate)}


def n_per_arm_two_prop(p0, rel_uplift, alpha=0.05, power=0.8):
    p1 = p0 * (1 + rel_uplift)
    za, zb = stats.norm.ppf(1 - alpha / 2), stats.norm.ppf(power)
    pbar = (p0 + p1) / 2
    n = ((za * np.sqrt(2 * pbar * (1 - pbar)) + zb * np.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) ** 2) / (p1 - p0) ** 2
    return int(np.ceil(n))


def mde_rel_two_prop(p0, n_per_arm, alpha=0.05, power=0.8):
    """Smallest relative uplift detectable with n per arm (binary outcome)."""
    lo, hi = 1e-4, 2.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if n_per_arm_two_prop(p0, mid, alpha, power) > n_per_arm:
            lo = mid
        else:
            hi = mid
    return hi


def mde_rel_mean(mean, sd, n_per_arm, alpha=0.05, power=0.8):
    """Smallest relative uplift in a continuous mean (e.g. rupees per account) detectable with n per arm."""
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return float(z * sd * np.sqrt(2.0 / n_per_arm) / mean)


def within_ols_cluster(y, x, groups):
    """Account/entity fixed-effects slope of y on x with cluster-robust SE (within transformation)."""
    d = pd.DataFrame({"y": y, "x": x, "g": groups})
    d["yd"] = d.y - d.groupby("g").y.transform("mean")
    d["xd"] = d.x - d.groupby("g").x.transform("mean")
    sxx = (d.xd ** 2).sum()
    if sxx == 0:
        return {"slope": 0.0, "se": np.nan, "p": np.nan, "n": len(d)}
    b = (d.xd * d.yd).sum() / sxx
    d["e"] = d.yd - b * d.xd
    meat = (d.assign(s=d.xd * d.e).groupby("g").s.sum() ** 2).sum()
    G = d.g.nunique()
    se = np.sqrt(meat) / sxx * np.sqrt(G / max(G - 1, 1))
    p = 2 * (1 - stats.norm.cdf(abs(b / se)))
    return {"slope": float(b), "se": float(se), "p": float(p), "n": int(len(d))}


def boot_ci(values, stat=np.mean, n=2000, seed=0, alpha=0.05):
    rng = np.random.default_rng(seed)
    v = np.asarray(values)
    s = [stat(rng.choice(v, len(v), replace=True)) for _ in range(n)]
    return float(np.percentile(s, 100 * alpha / 2)), float(np.percentile(s, 100 * (1 - alpha / 2)))


def perm_p_diff_means(a, b, n=5000, seed=0):
    rng = np.random.default_rng(seed)
    a, b = np.asarray(a, float), np.asarray(b, float)
    obs = a.mean() - b.mean()
    pooled = np.concatenate([a, b])
    cnt = 0
    for _ in range(n):
        rng.shuffle(pooled)
        if abs(pooled[:len(a)].mean() - pooled[len(a):].mean()) >= abs(obs):
            cnt += 1
    return float(obs), float((cnt + 1) / (n + 1))
