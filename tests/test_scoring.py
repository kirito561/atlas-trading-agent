import unittest

from engine.analysis.scoring import finalize_conviction, should_enter
from engine.config import Config
from engine.models import Analysis


def make_analysis(direction="long", score=2.0):
    return Analysis(symbol="BTC/USDT", direction=direction, score=score,
                    conviction=0, price=100, atr_pct=0.02, stop_pct=0.03,
                    signals=[], factors={})


class TestConviction(unittest.TestCase):
    def test_high_score_high_conviction(self):
        a = make_analysis(score=3.5)
        out = finalize_conviction(a, Config())
        self.assertEqual(out.conviction, 10)

    def test_weak_score_low_conviction(self):
        a = make_analysis(score=0.3)
        out = finalize_conviction(a, Config())
        self.assertLessEqual(out.conviction, 5)

    def test_score_magnitude_maps_symmetrically(self):
        cfg = Config()
        conversions = []
        for score in (-3.5, -2.5, -1.8, -1.0, -0.4, 0.4, 1.0, 1.8, 2.5, 3.5):
            a = make_analysis(score=score)
            conversions.append(finalize_conviction(a, cfg).conviction)
        self.assertEqual(conversions[:5], list(reversed(conversions[5:])))


class TestShouldEnter(unittest.TestCase):
    def test_neutral_skipped(self):
        cfg = Config(min_conviction=7)
        a = make_analysis(direction="neutral", score=0.1)
        finalize_conviction(a, cfg)
        ok, _ = should_enter(a, cfg)
        self.assertFalse(ok)

    def test_below_threshold_skipped(self):
        cfg = Config(min_conviction=7)
        a = make_analysis(direction="long", score=0.6)
        finalize_conviction(a, cfg)
        ok, reason = should_enter(a, cfg)
        self.assertFalse(ok)
        self.assertIn("below", reason)

    def test_short_disabled(self):
        cfg = Config(min_conviction=7, allow_short=False)
        a = make_analysis(direction="short", score=2.5)
        finalize_conviction(a, cfg)
        ok, reason = should_enter(a, cfg)
        self.assertFalse(ok)
        self.assertIn("shorting disabled", reason)

    def test_short_enabled(self):
        cfg = Config(min_conviction=7, allow_short=True)
        a = make_analysis(direction="short", score=2.5)
        finalize_conviction(a, cfg)
        ok, _ = should_enter(a, cfg)
        self.assertTrue(ok)

    def test_enter_high_conviction(self):
        cfg = Config(min_conviction=7)
        a = make_analysis(direction="long", score=2.5)
        finalize_conviction(a, cfg)
        ok, _ = should_enter(a, cfg)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()