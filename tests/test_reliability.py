import copy
import json
import unittest
from pathlib import Path
from reliability import summarize, wilson, analyze

class ReliabilityTests(unittest.TestCase):
    def test_joint_is_not_product_of_marginals(self):
        runs=[{'tonnes':1100,'route_tonnes':[600,500]},
              {'tonnes':1000,'route_tonnes':[600,400]},
              {'tonnes':1000,'route_tonnes':[400,600]},
              {'tonnes':1100,'route_tonnes':[500,600]}]
        r=summarize(runs,[500,500],[3,3])
        self.assertTrue(r['mean_targets_met'])
        self.assertEqual(r['front_success_rates'],[0.75,0.75])
        self.assertEqual(r['joint_success_rate'],0.5)

    def test_wilson_extremes_and_known_value(self):
        self.assertAlmostEqual(wilson(5,10)[0],0.2365930905)
        self.assertAlmostEqual(wilson(5,10)[1],0.7634069095)
        self.assertGreater(wilson(0,30)[1],0)
        self.assertLess(wilson(30,30)[0],1)
        with self.assertRaises(ValueError): wilson(0,0)

    def test_repeatability_and_no_mutation(self):
        c=json.loads(Path('data/scenario.json').read_text())
        original=copy.deepcopy(c)
        first=analyze(c,[2],5)
        self.assertEqual(first,analyze(c,[2],5))
        self.assertEqual(c,original)
        self.assertEqual(len(first[1]),35)
