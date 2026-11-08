"""Formato e ingreso de tiempos medidos reales (preparado; el repositorio no contiene datos reales).

Uso:
  python measured.py --input data/tiempos_medidos.csv
  python measured.py --input data/tiempos_medidos.csv --write-scenario data/scenario_calibrado.json

Formato de cada fila (ver data/tiempos_medidos_plantilla.csv, que está vacía a propósito):
  fecha          AAAA-MM-DD
  guardia        identificador de la guardia (texto)
  equipo         identificador del volquete (texto)
  ruta           nombre de la ruta tal como figura en el escenario (A, B, ...); vacío para ramp_crossing
  etapa          load | travel_loaded_total | dump | travel_empty_total | ramp_crossing
                 travel_*_total INCLUYE el cruce de rampa, igual que loaded_min/empty_min del escenario
  duracion_min   minutos, número positivo (excluir esperas en cola: se miden aparte por el modelo)
  fuente         origen del dato (p. ej. cronometraje, despacho, registro autorizado)
  observaciones  texto libre

--write-scenario solo reemplaza los tiempos nominales por las medias medidas si cada tiempo
necesario tiene al menos --min-n observaciones. No modifica 'variability' ni la forma de la
distribución (triangular simétrica): revise el ajuste antes de usar el escenario.
"""
import argparse
import copy
import csv
import datetime
import json
import math
import statistics
from pathlib import Path
from minefleet import ROOT, load_scenario, validate

FIELDS = ['fecha', 'guardia', 'equipo', 'ruta', 'etapa', 'duracion_min', 'fuente', 'observaciones']
ROUTE_STAGES = {'load': 'load_min', 'travel_loaded_total': 'loaded_min', 'dump': 'dump_min',
                'travel_empty_total': 'empty_min'}
STAGES = set(ROUTE_STAGES) | {'ramp_crossing'}


def read_measurements(path, route_names):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or [h.strip() for h in reader.fieldnames] != FIELDS:
            raise ValueError(f'Encabezados esperados: {",".join(FIELDS)}')
        rows, errors = [], []
        for line, raw in enumerate(reader, start=2):
            row = {k: (raw.get(k) or '').strip() for k in FIELDS}
            try:
                datetime.date.fromisoformat(row['fecha'])
            except ValueError:
                errors.append(f'fila {line}: fecha inválida {row["fecha"]!r} (use AAAA-MM-DD)')
            if row['etapa'] not in STAGES:
                errors.append(f'fila {line}: etapa desconocida {row["etapa"]!r}')
            elif row['etapa'] != 'ramp_crossing' and row['ruta'] not in route_names:
                errors.append(f'fila {line}: ruta {row["ruta"]!r} no existe en el escenario')
            try:
                value = float(row['duracion_min'].replace(',', '.'))
                if not math.isfinite(value) or value <= 0:
                    raise ValueError
                row['duracion_min'] = value
            except ValueError:
                errors.append(f'fila {line}: duracion_min debe ser un número positivo')
            if not row['equipo'] or not row['fuente']:
                errors.append(f'fila {line}: equipo y fuente son obligatorios')
            rows.append(row)
    if errors:
        raise ValueError('Datos medidos inválidos:\n  ' + '\n  '.join(errors[:30]))
    if not rows:
        raise ValueError('El archivo no contiene tiempos medidos. No se calculó nada ni se generó ningún escenario.')
    return rows


def quantile(sorted_values, q):
    """Cuantil con interpolación lineal (método 7, el habitual en hojas de cálculo)."""
    pos = (len(sorted_values) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def summarize(rows):
    groups = {}
    for r in rows:
        key = ('', 'ramp_crossing') if r['etapa'] == 'ramp_crossing' else (r['ruta'], r['etapa'])
        groups.setdefault(key, []).append(r)
    out = []
    for (route, stage), group in sorted(groups.items()):
        s = sorted(r['duracion_min'] for r in group)
        m = statistics.mean(s)
        sd = statistics.stdev(s) if len(s) > 1 else None
        out.append({'ruta': route, 'etapa': stage, 'n': len(s), 'media': m, 'desv_est': sd,
                    'cv': sd / m if sd is not None else None, 'min': s[0], 'p10': quantile(s, .1),
                    'p50': quantile(s, .5), 'p90': quantile(s, .9), 'max': s[-1],
                    'equipos': len({r['equipo'] for r in group})})
    return out


def calibrated_scenario(config, summary, min_n, source):
    stats = {(s['ruta'], s['etapa']): s for s in summary}
    missing = []
    for r in config['routes']:
        if r['enabled']:
            missing += [f'{r["name"]}/{st}' for st in ROUTE_STAGES if stats.get((r['name'], st), {}).get('n', 0) < min_n]
    if stats.get(('', 'ramp_crossing'), {}).get('n', 0) < min_n:
        missing.append('ramp_crossing')
    if missing:
        raise ValueError(f'No hay al menos {min_n} observaciones para: {", ".join(missing)}. No se generó el escenario.')
    c = copy.deepcopy(config)
    used = {}
    for r in c['routes']:
        if r['enabled']:
            for st, key in ROUTE_STAGES.items():
                r[key] = round(stats[(r['name'], st)]['media'], 4)
                used[f'{r["name"]}/{st}'] = stats[(r['name'], st)]['n']
    c['ramp_crossing_min'] = round(stats[('', 'ramp_crossing')]['media'], 4)
    used['ramp_crossing'] = stats[('', 'ramp_crossing')]['n']
    c['calibration'] = {'source_file': str(source), 'observations': used,
                        'note': 'Tiempos nominales = medias medidas. variability y la forma triangular simétrica '
                                'no se ajustaron a los datos; revise antes de interpretar resultados.'}
    validate(c)
    return c


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--input', type=Path, default=ROOT / 'data/tiempos_medidos_plantilla.csv')
    p.add_argument('--scenario', type=Path, default=ROOT / 'data/scenario.json')
    p.add_argument('--min-n', type=int, default=30)
    p.add_argument('--write-scenario', type=Path)
    args = p.parse_args()
    config = load_scenario(args.scenario)
    try:
        rows = read_measurements(args.input, {r['name'] for r in config['routes']})
        summary = summarize(rows)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc))
    nominal = {(r['name'], st): r[key] for r in config['routes'] for st, key in ROUTE_STAGES.items()}
    nominal[('', 'ramp_crossing')] = config['ramp_crossing_min']
    print('ruta  etapa                 n   media  p10   p50   p90   nominal_escenario')
    for s in summary:
        print(f"{s['ruta']:<5} {s['etapa']:<20} {s['n']:>4} {s['media']:6.2f} {s['p10']:5.2f} {s['p50']:5.2f} "
              f"{s['p90']:5.2f} {nominal.get((s['ruta'], s['etapa']), float('nan')):6.2f}")
    if args.write_scenario:
        try:
            c = calibrated_scenario(config, summary, args.min_n, args.input)
        except ValueError as exc:
            raise SystemExit(str(exc))
        args.write_scenario.write_text(json.dumps(c, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print('Escenario calibrado escrito en', args.write_scenario)


if __name__ == '__main__':
    main()
