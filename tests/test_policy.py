import copy
import random
import unittest
from policy import apply, select, validate_reliability


def cand(allocation, mean, met, joint, lo=None, hi=None, n=1000):
    return {'allocation': allocation, 'mean_tonnes': mean, 'mean_targets_met': met,
            'joint_success_count': joint, 'replications': n,
            'joint_wilson_95': [joint / n - 0.01 if lo is None else lo, min(1.0, joint / n + 0.005) if hi is None else hi]}


def data(cands):
    return {'analysis_replications': 1000, 'seed_range': [2026, 3025], 'scenarios': [{'ramp_min': 2, 'candidates': cands}]}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.cands = [cand([3, 3], 1796.1, True, 1000, 0.9962, 1.0),
                      cand([4, 2], 1889.65, False, 996, 0.98977, 0.99844),
                      cand([5, 1], 1975.0, False, 0, 0.0, 0.0038)]

    def test_criteria_differ_and_threshold_is_inclusive(self):
        report = apply(data(self.cands), 0.95)
        sel = report['scenarios'][0]['selections']
        self.assertEqual(sel['mean']['allocation'], [3, 3])
        self.assertEqual(sel['frequency']['allocation'], [4, 2])
        self.assertEqual(sel['wilson']['allocation'], [4, 2])
        self.assertEqual(select(self.cands, 'frequency', 0.996)['allocation'], [4, 2])  # 996/1000 == 0.996
        self.assertEqual(select(self.cands, 'frequency', 0.9961)['allocation'], [3, 3])
        self.assertEqual(select(self.cands, 'wilson', 0.99)['allocation'], [3, 3])

    def test_no_eligible_and_invalid_parameters(self):
        cands = [cand([3, 3], 1700, False, 100), cand([4, 2], 1800, False, 50)]
        report = apply(data(cands), 0.95)
        self.assertTrue(all(v is None for v in report['scenarios'][0]['selections'].values()))
        for bad in (-0.1, 1.1, float('nan'), '0.9', True):
            with self.assertRaises(ValueError):
                apply(data(self.cands), bad)

    def test_order_independence_tie_break_and_no_mutation(self):
        original = copy.deepcopy(self.cands)
        shuffled = self.cands[:]
        random.Random(1).shuffle(shuffled)
        self.assertEqual(apply(data(shuffled), 0.95)['scenarios'][0]['selections'],
                         apply(data(self.cands), 0.95)['scenarios'][0]['selections'])
        self.assertEqual(self.cands, original)
        tie = [cand([4, 2], 1800, True, 1000), cand([2, 4], 1800, True, 1000)]
        self.assertEqual(select(tie, 'mean', 0.95)['allocation'], [2, 4])

    def test_input_json_is_validated(self):
        bad_inputs = [{}, {'scenarios': []}, data([{'allocation': [3, 3]}]),
                      data([cand([3, 3], 1, True, 5, n=4)]),
                      data([cand([3, 3], 1, True, 5), cand([3, 3], 2, True, 5)]),
                      data([dict(cand([3, 3], 1, True, 5), joint_wilson_95=[0.5, 0.2])]),
                      data([dict(cand([3, 3], 1, True, 5), mean_targets_met='yes')])]
        for bad in bad_inputs:
            with self.assertRaises(ValueError):
                validate_reliability(bad)


if __name__ == '__main__':
    unittest.main()
