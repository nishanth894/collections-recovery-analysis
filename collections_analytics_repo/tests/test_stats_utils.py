import unittest
import numpy as np
import pandas as pd
from src import stats_utils as su


class TestStats(unittest.TestCase):
    def test_bh(self):
        q = su.bh_adjust([0.01, 0.04, 0.03, 0.5])
        np.testing.assert_allclose(q, [0.04, 0.0533333, 0.0533333, 0.5], atol=1e-6)

    def test_shift_share_identity(self):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({"s": rng.choice(list("ABC"), 600), "p": rng.choice(["x", "y"], 600), "num": rng.integers(0, 2, 600), "den": 1})
        r = su.shift_share(df, "s", "p", "x", "y", "num", "den")
        self.assertAlmostEqual(r["total_change"], r["mix_effect"] + r["rate_effect"], places=10)
        self.assertAlmostEqual(r["total_change"], r["rate_p1"] - r["rate_p0"], places=10)

    def test_shift_share_detects_pure_mix(self):
        df = pd.DataFrame({"s": ["A"] * 100 + ["B"] * 100 + ["A"] * 20 + ["B"] * 180, "p": ["x"] * 200 + ["y"] * 200,
                           "num": [1] * 100 + [0] * 100 + [1] * 20 + [0] * 180, "den": 1})
        r = su.shift_share(df, "s", "p", "x", "y", "num", "den")
        self.assertAlmostEqual(r["rate_effect"], 0.0, places=10); self.assertLess(r["mix_effect"], 0)

    def test_power_monotonic(self):
        self.assertGreater(su.n_per_arm_two_prop(0.08, 0.05), su.n_per_arm_two_prop(0.08, 0.10))
        n = su.n_per_arm_two_prop(0.08, 0.10); self.assertAlmostEqual(su.mde_rel_two_prop(0.08, n), 0.10, places=2)

    def test_within_ols_recovers_slope_with_fixed_effects(self):
        rng = np.random.default_rng(1); g = np.repeat(np.arange(500), 8)
        fe = np.repeat(rng.normal(0, 5, 500), 8); x = rng.normal(0, 1, len(g)) + 0.8 * fe  # x correlated with FE
        y = 2.0 * x * 0 + 0.5 * (x - 0.8 * fe) + fe + rng.normal(0, 1, len(g))
        r = su.within_ols_cluster(y, x, g)
        self.assertAlmostEqual(r["slope"], 0.5, delta=0.15)

    def test_overdispersion_null_calibrated(self):
        rng = np.random.default_rng(2); n = np.full(300, 200); s = rng.binomial(n, 0.2)
        self.assertGreater(su.overdispersion_test(s, n)["p"], 0.01)
        s2 = rng.binomial(n, rng.uniform(0.1, 0.3, 300)); self.assertLess(su.overdispersion_test(s2, n)["p"], 0.001)


if __name__ == "__main__":
    unittest.main()
