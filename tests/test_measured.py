import csv
import json
import random
import tempfile
import unittest
from pathlib import Path
from minefleet import ROOT
from measured import FIELDS, calibrated_scenario, read_measurements, summarize

ROUTES = {'A', 'B'}


def write(path, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def synthetic_rows(n):
    """Filas SINTÉTICAS solo para probar el formato; no son mediciones."""
    rng = random.Random(0)
    nominal = {'load': 6, 'travel_loaded_total': 12, 'dump': 3, 'travel_empty_total': 9}
    rows = []
    for route, factor in (('A', 1.0), ('B', 1.4)):
        for stage, value in nominal.items():
            for i in range(n):
                rows.append({'fecha': '2026-01-15', 'guardia': 'G1', 'equipo': f'V{i % 3}', 'ruta': route,
                             'etapa': stage, 'duracion_min': round(value * factor * rng.uniform(.9, 1.1), 3),
                             'fuente': 'sintético de prueba', 'observaciones': ''})
    for i in range(n):
        rows.append({'fecha': '2026-01-15', 'guardia': 'G1', 'equipo': 'V1', 'ruta': '', 'etapa': 'ramp_crossing',
                     'duracion_min': 2.0 + i % 3 * 0.1, 'fuente': 'sintético de prueba', 'observaciones': ''})
    return rows


class MeasuredTests(unittest.TestCase):
    def test_template_is_empty_and_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            read_measurements(ROOT / 'data/tiempos_medidos_plantilla.csv', ROUTES)
        self.assertIn('no contiene tiempos medidos', str(ctx.exception))

    def test_invalid_rows_report_line_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 't.csv'
            row = synthetic_rows(1)[0]
            write(path, [dict(row, etapa='espera'), dict(row, duracion_min='-3'), dict(row, ruta='Z'),
                         dict(row, fecha='15/01/2026')])
            with self.assertRaises(ValueError) as ctx:
                read_measurements(path, ROUTES)
            message = str(ctx.exception)
            for line in ('fila 2', 'fila 3', 'fila 4', 'fila 5'):
                self.assertIn(line, message)

    def test_summary_and_calibrated_scenario(self):
        config = json.loads((ROOT / 'data/scenario.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 't.csv'
            write(path, synthetic_rows(5))
            summary = summarize(read_measurements(path, ROUTES))
            self.assertEqual(len(summary), 9)
            self.assertTrue(all(s['n'] == 5 and s['p10'] <= s['p50'] <= s['p90'] for s in summary))
            with self.assertRaises(ValueError):
                calibrated_scenario(config, summary, 30, path)
            c = calibrated_scenario(config, summary, 5, path)
        self.assertNotEqual(c['routes'][0]['load_min'], config['routes'][0]['load_min'])
        self.assertEqual(c['variability'], config['variability'])
        self.assertIn('calibration', c)


if __name__ == '__main__':
    unittest.main()
