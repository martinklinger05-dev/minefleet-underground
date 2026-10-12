import copy
import json
import unittest
from pathlib import Path
from sensitivity import compare

class SensitivityTests(unittest.TestCase):
    def test_reproduction_and_no_mutation(self):
        c = json.loads(Path('data/scenario.json').read_text())
        original = copy.deepcopy(c)
        reports = compare(c, [2,3,5])
        self.assertEqual(c, original)
        self.assertEqual(reports[0]['report']['best']['allocation'], [4,2])
        self.assertAlmostEqual(reports[0]['report']['best']['mean_tonnes'],1890)
        self.assertEqual(reports[1]['report']['best']['allocation'], [3,3])
        self.assertIsNone(reports[2]['report']['best'])
        self.assertEqual(reports, compare(c,[2,3,5]))
