import json
import unittest
from minefleet import ROOT
from reliability import analyze
from validation import check_disjoint, near_target, run


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c = json.loads((ROOT / 'data/scenario.json').read_text(encoding='utf-8'))
        cls.selection, _ = analyze(c, [2], 20)

    def test_overlapping_seeds_are_rejected(self):
        with self.assertRaises(ValueError):
            check_disjoint([2026, 3025], 3000, 100)
        with self.assertRaises(ValueError):
            run(self.selection, 0.95, 20, seed_start=2030)
        check_disjoint([2026, 3025], 3026, 100)
        check_disjoint([2026, 3025], 1000, 1026)

    def test_selection_and_validation_are_kept_separate_and_reproducible(self):
        report = run(self.selection, 0.95, 20, seed_start=10_000)
        self.assertEqual(report, run(self.selection, 0.95, 20, seed_start=10_000))
        self.assertEqual(report['selection_batch']['seed_range'], self.selection['seed_range'])
        self.assertEqual(report['validation_batch']['seed_range'], [10_000, 10_019])
        item = report['scenarios'][0]['criteria']['mean']
        chosen = item['selected']['allocation']
        sel_candidate = next(c for c in self.selection['scenarios'][0]['candidates'] if c['allocation'] == chosen)
        self.assertEqual(item['selected']['mean_tonnes'], sel_candidate['mean_tonnes'])
        self.assertNotEqual(item['validation']['mean_tonnes'], sel_candidate['mean_tonnes'])
        self.assertIn('stable', item)

    def test_near_target_counts_guards_exactly_at_the_target(self):
        c = {'route_mean_tonnes': [1390.0, 499.0], 'route_tonnes_distribution': [{'1390': 10}, {'475': 1, '500': 24}]}
        info = near_target(c, [500, 500], 25)
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]['front'], 1)
        self.assertAlmostEqual(info[0]['at'], 0.96)
        self.assertAlmostEqual(info[0]['below'], 0.04)
        self.assertEqual(info[0]['above'], 0)


if __name__ == '__main__':
    unittest.main()
