import copy
import json
import tempfile
import unittest
from pathlib import Path
from minefleet import ROOT
from sensitivity import compare, export


def load():
    return json.loads((ROOT / 'data/scenario.json').read_text(encoding='utf-8'))


class SensitivityTests(unittest.TestCase):
    def test_reference_results_and_no_mutation(self):
        c = load()
        original = copy.deepcopy(c)
        reports = compare(c, [5, 1, 2])  # se ordenan internamente
        self.assertEqual(c, original)
        self.assertEqual([r['ramp_min'] for r in reports], [1, 2, 5])
        self.assertEqual(reports[0]['report']['best']['allocation'], [4, 2])
        self.assertAlmostEqual(reports[0]['report']['best']['mean_tonnes'], 1917.5)
        self.assertEqual(reports[1]['report']['best']['allocation'], [3, 3])
        self.assertAlmostEqual(reports[1]['report']['best']['mean_tonnes'], 1792.5)
        self.assertIsNone(reports[2]['report']['best'])
        self.assertEqual(reports, compare(c, [5, 1, 2]))

    def test_other_fleet_sizes_are_supported(self):
        c = load()
        c.update(fleet=4, baseline=[2, 2], minimum_tonnes=[300, 300], replications=3)
        reports = compare(c, [2, 3])
        with tempfile.TemporaryDirectory() as tmp:
            export(c, reports, Path(tmp), highlight=None)
            self.assertIn('flota de 4', (Path(tmp) / 'dashboard.html').read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):
            compare(c, [2, 2])


if __name__ == '__main__':
    unittest.main()
