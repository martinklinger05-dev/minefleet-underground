import copy
import json
import unittest
from minefleet import ROOT
from reliability import analyze, summarize, wilson


class ReliabilityTests(unittest.TestCase):
    def test_joint_is_not_product_of_marginals(self):
        runs = [{'tonnes': 1100, 'route_tonnes': [600, 500]},
                {'tonnes': 1000, 'route_tonnes': [600, 400]},
                {'tonnes': 1000, 'route_tonnes': [400, 600]},
                {'tonnes': 1100, 'route_tonnes': [500, 600]}]
        r = summarize(runs, [500, 500], [3, 3])
        self.assertTrue(r['mean_targets_met'])
        self.assertEqual(r['front_success_rates'], [0.75, 0.75])
        self.assertEqual(r['joint_success_rate'], 0.5)
        self.assertEqual(r['route_tonnes_distribution'][1], {'400': 1, '500': 1, '600': 2})

    def test_wilson_extremes_and_known_value(self):
        self.assertAlmostEqual(wilson(5, 10)[0], 0.2365930905)
        self.assertAlmostEqual(wilson(5, 10)[1], 0.7634069095)
        self.assertGreater(wilson(0, 30)[1], 0)
        self.assertLess(wilson(30, 30)[0], 1)
        self.assertAlmostEqual(wilson(996, 1000)[0], 0.98977, places=4)
        for bad in ((0, 0), (11, 10), (-1, 10), (1.5, 10)):
            with self.assertRaises(ValueError):
                wilson(*bad)

    def test_repeatability_and_no_mutation(self):
        c = json.loads((ROOT / 'data/scenario.json').read_text(encoding='utf-8'))
        original = copy.deepcopy(c)
        first = analyze(c, [2], 5)
        self.assertEqual(first, analyze(c, [2], 5))
        self.assertEqual(c, original)
        self.assertEqual(len(first[1]), 35)
        self.assertEqual(first[0]['seed_range'], [c['seed'], c['seed'] + 4])
        shifted = analyze(c, [2], 5, seed_start=500)
        self.assertEqual(shifted[0]['seed_range'], [500, 504])


if __name__ == '__main__':
    unittest.main()
