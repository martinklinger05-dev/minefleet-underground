import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from minefleet import ROOT, export, optimize, simulate, validate

DATA = ROOT / 'data'


def load(name='scenario.json'):
    return json.loads((DATA / name).read_text(encoding='utf-8'))


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.c = load()

    # --- ocho pruebas originales (adaptadas al modelo v2) ---
    def test_repeatable(self):
        self.assertEqual(simulate(self.c, [3, 3], 9), simulate(self.c, [3, 3], 9))

    def test_resource_exclusion(self):
        result = simulate(self.c, [3, 3], keep_events=True)
        for resource in ('load0', 'load1', 'dump', 'ramp'):
            events = sorted((e for e in result['events'] if e['resource'] == resource), key=lambda e: e['start'])
            for a, b in zip(events, events[1:]):
                self.assertLessEqual(a['end'], b['start'] + 1e-4)
        delivered = sum(e['stage'] == 'dump' and e['end'] <= self.c['shift_min'] for e in result['events'])
        self.assertEqual(result['tonnes'], delivered * self.c['payload_t'])
        self.assertEqual(result['trips'], delivered)

    def test_single_truck_manual(self):
        c = copy.deepcopy(self.c); c.update(fleet=1, variability=0, shift_min=450)
        # Primera descarga al minuto 21 (6+10+2+3) y luego cada 30 min: 15 descargas = 375 t.
        self.assertEqual(simulate(c, [1, 0])['tonnes'], 375)

    def test_shift_cutoff(self):
        c = copy.deepcopy(self.c); c.update(fleet=1, variability=0, shift_min=20)
        self.assertEqual(simulate(c, [1, 0])['tonnes'], 0)
        c['shift_min'] = 21
        self.assertEqual(simulate(c, [1, 0])['tonnes'], 25)

    def test_invalid_allocation(self):
        with self.assertRaises(ValueError): simulate(self.c, [4, 4])
        self.c['routes'][0]['enabled'] = False
        with self.assertRaises(ValueError): simulate(self.c, [3, 3])

    def test_no_feasible_solution(self):
        self.c['minimum_tonnes'] = [100000, 100000]
        self.c['replications'] = 2
        self.assertIsNone(optimize(self.c)['best'])

    def test_exhaustive_optimum(self):
        r = optimize(self.c)
        self.assertEqual(len(r['candidates']), 7)
        self.assertEqual(r['best']['mean_tonnes'], max(x['mean_tonnes'] for x in r['candidates'] if x['feasible']))

    def test_bad_data(self):
        self.c['routes'][0]['load_min'] = -1
        with self.assertRaises(ValueError): validate(self.c)

    # --- auditoría v2 ---
    def test_v1_reproduces_historical_release(self):
        r = optimize(load('scenario_v1_historico.json'))
        self.assertEqual(r['best']['allocation'], [4, 2])
        self.assertAlmostEqual(r['best']['mean_tonnes'], 1890.0)
        self.assertAlmostEqual(r['baseline']['mean_tonnes'], 1793.3333333, places=5)
        self.assertAlmostEqual(r['improvement_pct'], 5.3903345724, places=6)
        slow = optimize(load('scenario_v1_historico_rampa_lenta.json'))
        self.assertEqual(slow['best']['allocation'], [3, 3])
        self.assertAlmostEqual(slow['best']['mean_tonnes'], 1722.5)

    def test_ramp_position_is_consistent(self):
        """Cargado y vacío cruzan la rampa en el mismo extremo del recorrido."""
        for side, before, after in (('dump', 'travel_loaded', 'dump'), ('load', 'load', 'travel_loaded')):
            c = copy.deepcopy(self.c); c['ramp_side'] = side
            stages = {}
            for ev in simulate(c, [3, 3], keep_events=True)['events']:
                stages.setdefault(ev['truck'], []).append(ev['stage'])
            for seq in stages.values():
                for i, st in enumerate(seq[:-1]):
                    if st == 'ramp_loaded':
                        self.assertEqual(seq[i - 1], before)
                        self.assertEqual(seq[i + 1], after)
                    if st == 'ramp_empty':
                        expected_prev = 'dump' if side == 'dump' else 'travel_empty'
                        self.assertEqual(seq[i - 1], expected_prev)

    def test_time_breakdown_covers_every_truck_minute(self):
        for version in (1, 2):
            c = copy.deepcopy(self.c); c['model_version'] = version
            r = simulate(c, [4, 2], 77)
            self.assertAlmostEqual(sum(r['time_breakdown_min'].values()), c['fleet'] * c['shift_min'], places=6)
            self.assertAlmostEqual(r['time_breakdown_min']['wait'], r['wait_min'], places=6)
            for u in r['utilization'].values():
                self.assertTrue(0 <= u <= 1)

    def test_common_random_numbers_by_position(self):
        """En v2, el primer volquete de A recibe los mismos números en 3/3 y en 4/2."""
        c = copy.deepcopy(self.c); c['variability'] = 0.3
        first = [e for e in simulate(c, [3, 3], 5, True)['events'] if e['truck'] == 1 and e['stage'] == 'load'][0]
        other = [e for e in simulate(c, [4, 2], 5, True)['events'] if e['truck'] == 1 and e['stage'] == 'load'][0]
        self.assertEqual(first['end'] - first['start'], other['end'] - other['start'])

    def test_input_validation_messages(self):
        bad_cases = [
            lambda c: c.pop('fleet'),
            lambda c: c.update(fleet=True),
            lambda c: c.update(payload_t='25'),
            lambda c: c.update(shift_min=float('nan')),
            lambda c: c.update(cost_per_truck_hour=float('inf')),
            lambda c: c.update(variability=1.0),
            lambda c: c.update(variability=-0.1),
            lambda c: c.update(model_version=3),
            lambda c: c.update(ramp_side='middle'),
            lambda c: c.update(ramp_crossing_min=10),
            lambda c: c['routes'][0].update(enabled='yes'),
            lambda c: c['routes'][1].update(name='A'),
            lambda c: c['routes'][0].pop('dump_min'),
            lambda c: c.update(minimum_tonnes=[500]),
            lambda c: c.update(baseline=[3, 2]),
            lambda c: [r.update(enabled=False) for r in c['routes']],
        ]
        for mutate in bad_cases:
            c = copy.deepcopy(self.c)
            mutate(c)
            with self.assertRaises(ValueError, msg=str(c)[:80]):
                validate(c)

    def test_closed_route_and_single_replication(self):
        c = copy.deepcopy(self.c)
        c['routes'][1]['enabled'] = False
        c.update(baseline=[6, 0], minimum_tonnes=[0, 0], replications=1)
        r = optimize(c)
        self.assertEqual([x['allocation'] for x in r['candidates']], [[6, 0]])
        self.assertIsNone(r['best']['mean_ci95'])

    def test_zero_production_exports_without_crashing(self):
        c = copy.deepcopy(self.c)
        c.update(shift_min=5, replications=2, minimum_tonnes=[0, 0])
        r = optimize(c)
        self.assertEqual(r['best']['mean_tonnes'], 0)
        self.assertIsNone(r['best']['cost_per_t'])
        with tempfile.TemporaryDirectory() as tmp:
            export(c, r, Path(tmp), [])
            text = (Path(tmp) / 'dashboard.html').read_text(encoding='utf-8')
            self.assertIn('—', text)
            self.assertTrue((Path(tmp) / 'events.csv').read_text(encoding='utf-8').startswith('truck,'))

    def test_route_names_are_escaped_in_html(self):
        c = copy.deepcopy(self.c)
        c['routes'][0]['name'] = '<script>x</script>'
        c['replications'] = 2
        r = optimize(c)
        with tempfile.TemporaryDirectory() as tmp:
            export(c, r, Path(tmp), [])
            text = (Path(tmp) / 'dashboard.html').read_text(encoding='utf-8')
        self.assertNotIn('<script>x', text)
        self.assertIn('&lt;script&gt;', text)

    def test_cost_is_ratio_of_means(self):
        r = optimize(self.c)
        b = r['baseline']
        self.assertTrue(math.isclose(b['cost_per_t'], 6 * 7.5 * 150 / b['mean_tonnes']))


if __name__ == '__main__':
    unittest.main()
