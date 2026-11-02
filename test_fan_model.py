"""Exercise the exact native control math without reading or writing hardware."""
import ctypes
import math
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


@unittest.skipUnless(shutil.which('clang'), 'clang is required for native fan model tests')
class PredictiveFanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        source = Path(cls.temp.name) / 'model.c'
        source.write_text('''#include "fan_model.h"
#include <stdlib.h>
void *create(void) { MCFanModel *m = calloc(1, sizeof(*m)); mcModelInit(m); return m; }
void destroy(void *p) { free(p); }
int step(void *p, double t, double temp, double load, double fan, double goal) {
    return mcModelStep(p, t, temp, load, fan, goal);
}
double get(void *p, int key) {
    MCFanModel *m = p;
    switch(key) {
        case 0: return m->demand; case 1: return m->forecast;
        case 2: return m->samples; case 3: return m->headroom;
        case 4: return m->safety; case 5: return m->error;
        default: return m->theta[key-6];
    }
}
''')
        binary = Path(cls.temp.name) / 'model.dylib'
        subprocess.run(['clang', '-shared', '-fPIC', '-O2', '-I', str(ROOT/'native'), str(source), '-o', str(binary)], check=True)
        cls.lib = ctypes.CDLL(str(binary))
        cls.lib.create.restype = ctypes.c_void_p
        cls.lib.destroy.argtypes = [ctypes.c_void_p]
        cls.lib.step.argtypes = [ctypes.c_void_p] + [ctypes.c_double]*5
        cls.lib.step.restype = ctypes.c_int
        cls.lib.get.argtypes = [ctypes.c_void_p, ctypes.c_int]
        cls.lib.get.restype = ctypes.c_double

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        self.models = []
        self.model = self.new_model()

    def new_model(self):
        model = self.lib.create(); self.models.append(model); return model

    def tearDown(self):
        for model in self.models: self.lib.destroy(model)

    def step(self, t, temp, load=.4, fan=.5, goal=70, model=None):
        return self.lib.step(model or self.model, t, temp, load, fan, goal)

    def get(self, key, model=None): return self.lib.get(model or self.model, key)

    def test_heating_predicts_crossing_and_accelerates_below_target(self):
        self.step(0, 58, .2)
        for t in range(2, 32, 2): self.step(t, 58, .2)
        before = self.get(0)
        self.step(32, 61, .8)
        self.assertGreater(self.get(1), 70)
        self.assertGreater(self.get(0), before)
        self.assertEqual(self.get(4), 0)  # Still below emergency threshold.

    def test_load_jump_increases_forecast_at_same_temperature(self):
        other = self.new_model()
        for model in [self.model, other]:
            self.step(0, 60, .1, model=model)
            self.step(2, 60, .1, model=model)
        self.step(4, 60, .1)
        self.step(4, 60, .9, model=other)
        self.assertGreater(self.get(1, other), self.get(1)+5)

    def test_at_target_or_90_degrees_forces_maximum(self):
        for goal in [50, 70, 85]:
            self.step(0, goal-10, goal=goal)
            self.step(2, goal, goal=goal)
            self.assertEqual(self.get(0), 1)
            self.assertEqual(self.get(4), 1)
        self.step(4, 91, goal=85)
        self.assertEqual(self.get(0), 1)

    def test_invalid_telemetry_is_rejected_without_mutating_model(self):
        self.step(0, 65)
        demand = self.get(0)
        for args in [(2, math.nan, .4, .5, 70), (2, 130, .4, .5, 70),
                     (2, 65, math.nan, .5, 70), (2, 65, 1.1, .5, 70),
                     (2, 65, .4, math.inf, 70), (2, 65, .4, -1, 70),
                     (math.nan, 65, .4, .5, 70), (2, 65, .4, .5, 86)]:
            self.assertFalse(self.lib.step(self.model, *args))
        self.assertEqual(self.get(2), 0)
        self.assertEqual(self.get(0), demand)

    def test_sleep_gap_discards_trend_and_does_not_learn(self):
        self.step(0, 60); self.step(2, 63)
        learned = self.get(2)
        self.step(100, 50, .1, .1)
        self.assertEqual(self.get(2), learned)
        self.assertAlmostEqual(self.get(0), .97)
        self.assertLess(self.get(1), 70)

    def test_ramp_down_is_time_based_and_slower_than_ramp_up(self):
        self.step(0, 45, .1, 0)
        before = self.get(0)
        self.step(2, 45, .1, 0)
        self.assertAlmostEqual(before-self.get(0), .03)
        self.step(3, 45, .1, 0)
        self.assertAlmostEqual(before-self.get(0), .045)

    def test_logged_response_identifies_different_cooling_effects(self):
        rng = random.Random(13)
        other = self.new_model()
        for model, cooling in [(self.model, .4), (other, 1.5)]:
            temperature = 65
            self.step(0, temperature, .5, .5, model=model)
            for i in range(1, 1801):
                load = rng.uniform(0, 1); fan = rng.uniform(0, 1)
                # Midpoint regression assumes a smoothly sampled plant input.
                # Hold each random input across the interval for identification.
                self.step(4*i-2, temperature, load, fan, model=model)
                temperature += 2*(.15-.4*(temperature-40)/40+load-cooling*fan)
                self.step(4*i, temperature, load, fan, model=model)
        self.assertGreater(self.get(9, other), self.get(9)+.4)
        self.assertGreater(self.get(2), 3000)

    def test_demand_and_coefficients_stay_bounded_under_noise(self):
        rng = random.Random(5)
        for i in range(2000):
            self.step(2*i, rng.uniform(40, 95), rng.random(), rng.random())
            self.assertTrue(0 <= self.get(0) <= 1)
            self.assertTrue(2 <= self.get(3) <= 5)
            self.assertTrue(.15 <= self.get(9) <= 4)
            self.assertTrue(math.isfinite(self.get(1)))

    def test_workload_step_stays_below_target_where_legacy_curve_overshoots(self):
        peaks = {}
        for mode in ['predictive', 'legacy']:
            temperature, fan, demand, integral = 60., .5, 1., 0.
            peak = 0
            for i in range(900):
                load = .15 if i < 300 else .7
                if mode == 'predictive':
                    self.step(2*i, temperature, load, fan)
                    demand = self.get(0)
                else:
                    error = temperature-70
                    points = [(-15, 0), (-10, .15), (-5, .35), (0, .6), (3, .85), (6, 1)]
                    base = 0 if error <= -15 else 1
                    for (a, b), (c, d) in zip(points, points[1:]):
                        if a <= error <= c:
                            base = b+(error-a)/(c-a)*(d-b); break
                    integral = max(-.35, min(.25, integral+error*.003))
                    desired = max(0, min(1, base+integral))
                    demand = 1 if temperature >= 90 or error >= 6 else max(demand-.05, min(demand+.25, desired))
                # The same synthetic plant and eight-second fan response for both.
                fan += .25*(demand-fan)
                temperature += 2*(.15-.4*(temperature-40)/40+load-.95*fan)
                if i >= 300: peak = max(peak, temperature)
            peaks[mode] = peak
        self.assertLess(peaks['predictive'], 70)
        self.assertGreater(peaks['legacy'], 70)
        self.assertLess(peaks['predictive'], peaks['legacy']-2)

    def test_closed_loop_settles_below_target_with_fan_lag(self):
        temperature, fan, peak = 60., .5, 0
        for i in range(900):
            self.step(2*i, temperature, .7, fan)
            fan += .25*(self.get(0)-fan)
            temperature += 2*(.15-.4*(temperature-40)/40+.7-.95*fan)
            if i > 300: peak = max(peak, temperature)
        self.assertLess(peak, 70)
        self.assertGreater(temperature, 50)


if __name__ == '__main__': unittest.main()
