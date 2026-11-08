"""MineFleet: simulación de eventos discretos de acarreo subterráneo.

Solo usa la biblioteca estándar de Python. Todos los datos incluidos son simulados.

Modelo v2 (predeterminado):
  - La rampa compartida ocupa la misma posición física en ambos sentidos
    (``ramp_side``: "dump" = tramo común junto a la descarga; "load" = junto a los frentes).
  - Cada puesto (ruta, posición dentro de la ruta) tiene su propio flujo aleatorio,
    para que las asignaciones comparadas compartan números aleatorios por ruta.
Modelo v1 (``"model_version": 1``): reproduce exactamente los resultados de la release v1.0.0.
"""
import argparse
import csv
import heapq
import html
import io
import json
import math
import os
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Secuencias de etapas. 'delivered' es instantánea: suma toneladas al terminar la descarga.
STAGE_SEQUENCES = {
    'v1': ['load', 'ramp_loaded', 'travel_loaded', 'dump', 'delivered', 'ramp_empty', 'travel_empty'],
    'dump': ['load', 'travel_loaded', 'ramp_loaded', 'dump', 'delivered', 'ramp_empty', 'travel_empty'],
    'load': ['load', 'ramp_loaded', 'travel_loaded', 'dump', 'delivered', 'travel_empty', 'ramp_empty'],
}
REQUIRED_KEYS = ('fleet', 'payload_t', 'shift_min', 'cost_per_truck_hour', 'replications', 'seed',
                 'variability', 'baseline', 'minimum_tonnes', 'ramp_crossing_min', 'routes')
ROUTE_KEYS = ('name', 'load_min', 'loaded_min', 'dump_min', 'empty_min', 'enabled')
BREAKDOWN_KEYS = ('load', 'ramp', 'travel', 'dump', 'wait')

# Cuantiles t de Student bilaterales al 95 % (gl 1–30). Para gl mayores se usa el valor
# tabulado inmediatamente inferior (conservador) y 1.96 a partir de gl = 1000.
_T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160,
        2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056,
        2.052, 2.048, 2.045, 2.042]
_T95_LARGE = [(1000, 1.962), (120, 1.980), (60, 2.000), (40, 2.021), (30, 2.042)]


def t95(df):
    """Cuantil t bilateral del 95 % (tabla conservadora)."""
    if df < 1:
        raise ValueError('Se necesitan al menos 2 réplicas para un intervalo')
    if df <= 30:
        return _T95[df - 1]
    for limit, value in _T95_LARGE:
        if df >= limit:
            return value
    return _T95[-1]


def mean_ci(values):
    """Media, error estándar e intervalo t del 95 % de la media (incertidumbre de estimación)."""
    n = len(values)
    m = statistics.mean(values)
    if n < 2:
        return {'mean': m, 'se': None, 'ci95': None}
    se = statistics.stdev(values) / math.sqrt(n)
    h = t95(n - 1) * se
    return {'mean': m, 'se': se, 'ci95': [m - h, m + h]}


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _positive(value, name):
    if not _is_number(value) or value <= 0:
        raise ValueError(f'{name}: se esperaba un número positivo y finito (recibido {value!r})')


def validate(c):
    """Valida un escenario completo. Lanza ValueError con un mensaje comprensible."""
    if not isinstance(c, dict):
        raise ValueError('El escenario debe ser un objeto JSON')
    missing = [k for k in REQUIRED_KEYS if k not in c]
    if missing:
        raise ValueError(f'Faltan claves en el escenario: {", ".join(missing)}')
    for key in ('fleet', 'replications'):
        if type(c[key]) is not int or c[key] < 1:
            raise ValueError(f'{key}: se esperaba un entero mayor o igual a 1 (recibido {c[key]!r})')
    if type(c['seed']) is not int:
        raise ValueError(f'seed: se esperaba un entero (recibido {c["seed"]!r})')
    for key in ('payload_t', 'shift_min', 'cost_per_truck_hour', 'ramp_crossing_min'):
        _positive(c[key], key)
    if not _is_number(c['variability']) or not 0 <= c['variability'] < 1:
        raise ValueError('variability: debe ser un número en [0, 1)')
    version = c.get('model_version', 2)
    if version not in (1, 2):
        raise ValueError('model_version: debe ser 1 (histórico) o 2')
    if c.get('ramp_side', 'dump') not in ('dump', 'load'):
        raise ValueError('ramp_side: debe ser "dump" o "load"')
    if not isinstance(c['routes'], list) or len(c['routes']) != 2:
        raise ValueError('routes: esta versión admite exactamente dos rutas')
    if not isinstance(c['minimum_tonnes'], list) or len(c['minimum_tonnes']) != 2:
        raise ValueError('minimum_tonnes: se esperan dos metas, una por ruta')
    if any(not _is_number(x) or x < 0 for x in c['minimum_tonnes']):
        raise ValueError('minimum_tonnes: las metas deben ser números finitos no negativos')
    names = []
    for i, r in enumerate(c['routes']):
        if not isinstance(r, dict):
            raise ValueError(f'routes[{i}]: debe ser un objeto')
        missing = [k for k in ROUTE_KEYS if k not in r]
        if missing:
            raise ValueError(f'routes[{i}]: faltan claves {", ".join(missing)}')
        if not isinstance(r['name'], str) or not r['name'].strip():
            raise ValueError(f'routes[{i}].name: debe ser un texto no vacío')
        if type(r['enabled']) is not bool:
            raise ValueError(f'routes[{i}].enabled: debe ser true o false')
        for k in ('load_min', 'loaded_min', 'dump_min', 'empty_min'):
            _positive(r[k], f'routes[{i}].{k}')
        if min(r['loaded_min'], r['empty_min']) < c['ramp_crossing_min']:
            raise ValueError(f'Ruta {r["name"]}: el cruce de rampa ({c["ramp_crossing_min"]} min) no puede '
                             'superar el tiempo total de viaje cargado o vacío, que ya lo incluye')
        names.append(r['name'])
    if len(set(names)) != len(names):
        raise ValueError('routes: los nombres de ruta deben ser distintos')
    if not any(r['enabled'] for r in c['routes']):
        raise ValueError('routes: al menos una ruta debe estar habilitada')
    validate_allocation(c, c['baseline'])


def validate_allocation(c, allocation):
    if (not isinstance(allocation, (list, tuple)) or len(allocation) != 2
            or any(type(x) is not int or x < 0 for x in allocation) or sum(allocation) != c['fleet']):
        raise ValueError(f'Asignación {allocation!r}: debe usar cada uno de los {c["fleet"]} volquetes exactamente una vez')
    if any(n and not r['enabled'] for n, r in zip(allocation, c['routes'])):
        raise ValueError(f'Asignación {allocation!r}: no se pueden asignar volquetes a una ruta cerrada')


def candidate_allocations(c):
    return [[a, c['fleet'] - a] for a in range(c['fleet'] + 1)
            if all(n == 0 or r['enabled'] for n, r in zip([a, c['fleet'] - a], c['routes']))]


def _streams(c, allocation, seed):
    if c.get('model_version', 2) == 1:
        return [random.Random(seed * 100003 + i) for i in range(c['fleet'])]
    # Flujo por puesto (ruta, posición): el volquete k de la ruta A usa el mismo flujo
    # en 3/3 y en 4/2. Las semillas de texto se derivan con SHA-512 (estables entre plataformas).
    return [random.Random(f'minefleet-v2|{seed}|{route}|{slot}')
            for route, n in enumerate(allocation) for slot in range(n)]


def simulate(c, allocation, seed=2026, keep_events=False):
    """Simula una guardia. Devuelve toneladas, viajes, esperas, desglose de tiempos y eventos."""
    validate_allocation(c, allocation)
    shift = c['shift_min']
    v1 = c.get('model_version', 2) == 1
    sequence = STAGE_SEQUENCES['v1' if v1 else c.get('ramp_side', 'dump')]
    following = {s: sequence[(i + 1) % len(sequence)] for i, s in enumerate(sequence)}
    rng = _streams(c, allocation, seed)
    available = {'load0': 0.0, 'load1': 0.0, 'dump': 0.0, 'ramp': 0.0}
    busy = dict.fromkeys(available, 0.0)
    breakdown = dict.fromkeys(BREAKDOWN_KEYS, 0.0)
    queue, serial = [], 0
    tonnes, trips, waits, events = [0.0, 0.0], [0, 0], 0.0, []
    truck_routes = [i for i, n in enumerate(allocation) for _ in range(n)]

    def push(t, truck, stage):
        nonlocal serial
        serial += 1
        heapq.heappush(queue, (t, serial, truck, stage))

    def clipped(a, b):
        return max(0.0, min(b, shift) - min(a, shift))

    for truck in range(c['fleet']):
        push(0.0, truck, 'load')
    while queue:
        t, _, truck, stage = heapq.heappop(queue)
        if t > shift:
            break
        route = truck_routes[truck]
        r = c['routes'][route]
        resource = None
        if stage == 'delivered':
            if t <= shift:
                tonnes[route] += c['payload_t']
                trips[route] += 1
            push(t, truck, following[stage])
            continue
        if stage == 'load':
            duration, resource, kind = r['load_min'], f'load{route}', 'load'
        elif stage in ('ramp_loaded', 'ramp_empty'):
            duration, resource, kind = c['ramp_crossing_min'], 'ramp', 'ramp'
        elif stage == 'travel_loaded':
            duration, kind = r['loaded_min'] - c['ramp_crossing_min'], 'travel'
        elif stage == 'travel_empty':
            duration, kind = r['empty_min'] - c['ramp_crossing_min'], 'travel'
        else:
            duration, resource, kind = r['dump_min'], 'dump', 'dump'
        # La ocupación de rampa es fija; carguío, descarga y viaje fuera de rampa son triangulares.
        if kind != 'ramp':
            v = c['variability']
            duration = rng[truck].triangular(duration * (1 - v), duration * (1 + v), duration)
        start = max(t, available[resource]) if resource else t
        end = start + duration
        waits += max(0.0, min(start, shift) - t)
        breakdown['wait'] += clipped(t, start)
        breakdown[kind] += clipped(start, end)
        if resource:
            available[resource] = end
            busy[resource] += clipped(start, end)
        if keep_events:
            events.append({'truck': truck + 1, 'route': r['name'], 'stage': stage, 'arrival': round(t, 4),
                           'start': round(start, 4), 'end': round(end, 4), 'resource': resource or '',
                           'counts_in_shift': end <= shift})
        push(end, truck, following[stage])
    total = sum(tonnes)
    cost = c['fleet'] * shift / 60 * c['cost_per_truck_hour']
    return {'tonnes': total, 'route_tonnes': tonnes, 'trips': sum(trips), 'route_trips': trips,
            'wait_min': waits, 'time_breakdown_min': breakdown,
            'utilization': {k: v / shift for k, v in busy.items()},
            'cost': cost, 'cost_per_t': cost / total if total else None, 'events': events}


def replication_seeds(c, start=None, count=None):
    start = c['seed'] if start is None else start
    count = c['replications'] if count is None else count
    return list(range(start, start + count))


def evaluate(c, allocation, seeds=None):
    """Evalúa una asignación con varias réplicas (guardias simuladas)."""
    seeds = replication_seeds(c) if seeds is None else seeds
    runs = [simulate(c, allocation, s) for s in seeds]
    values = [r['tonnes'] for r in runs]
    route_values = [[r['route_tonnes'][i] for r in runs] for i in range(2)]
    means = [statistics.mean(v) for v in route_values]
    mean_total = statistics.mean(values)
    cost = runs[0]['cost']
    return {
        'allocation': list(allocation), 'replications': len(runs),
        'mean_tonnes': mean_total,
        'sd_tonnes': statistics.stdev(values) if len(values) > 1 else 0,
        'mean_ci95': mean_ci(values)['ci95'],
        'min_tonnes': min(values), 'max_tonnes': max(values),
        'route_mean_tonnes': means,
        'route_sd_tonnes': [statistics.stdev(v) if len(v) > 1 else 0 for v in route_values],
        'route_min_tonnes': [min(v) for v in route_values],
        'mean_wait_min': statistics.mean(r['wait_min'] for r in runs),
        'mean_time_breakdown_min': {k: statistics.mean(r['time_breakdown_min'][k] for r in runs)
                                    for k in BREAKDOWN_KEYS},
        'mean_utilization': {k: statistics.mean(r['utilization'][k] for r in runs) for k in runs[0]['utilization']},
        # Razón de medias: costo fijo de guardia / producción media (no promedio de costos unitarios).
        'cost_per_t': cost / mean_total if mean_total else None,
        'feasible': all(m >= target for m, target in zip(means, c['minimum_tonnes'])),
        '_values': values,
    }


def paired_difference(candidate, baseline):
    """Diferencia pareada por réplica (mismas semillas). Las réplicas no son independientes entre alternativas."""
    diffs = [a - b for a, b in zip(candidate['_values'], baseline['_values'])]
    return mean_ci(diffs)


def optimize(c):
    """Enumera todas las asignaciones estáticas y elige la de mayor producción media
    entre las que cumplen las metas medias de ambos frentes."""
    validate(c)
    candidates = [evaluate(c, a) for a in candidate_allocations(c)]
    feasible = [x for x in candidates if x['feasible']]
    best = max(feasible, key=lambda x: (x['mean_tonnes'], [-n for n in x['allocation']])) if feasible else None
    baseline = next(x for x in candidates if x['allocation'] == c['baseline'])
    for x in candidates:
        x['paired_diff_vs_baseline'] = paired_difference(x, baseline)
    for x in candidates:
        del x['_values']
    seeds = replication_seeds(c)
    return {'data_type': 'SIMULATED', 'model_version': c.get('model_version', 2),
            'ramp_side': None if c.get('model_version', 2) == 1 else c.get('ramp_side', 'dump'),
            'selection_rule': 'Mayor producción media entre asignaciones cuyas medias por frente alcanzan las metas',
            'replications': c['replications'], 'seed': c['seed'], 'seed_range': [seeds[0], seeds[-1]],
            'baseline': baseline, 'best': best, 'candidates': candidates,
            'improvement_pct': 100 * (best['mean_tonnes'] / baseline['mean_tonnes'] - 1)
            if best and baseline['mean_tonnes'] else None}


# ---------------------------------------------------------------- exportación

def write_files(out, files):
    """Escribe todos los archivos de un resultado. Primero los genera en temporales y luego
    los reemplaza, para no dejar una mezcla de archivos nuevos y viejos si algo falla."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    temps = []
    try:
        for name, content in files.items():
            tmp = out / f'.{name}.tmp'
            tmp.write_text(content, encoding='utf-8', newline='')
            temps.append((tmp, out / name))
        for tmp, final in temps:
            os.replace(tmp, final)
    finally:
        for tmp, _ in temps:
            if tmp.exists():
                tmp.unlink()


def csv_text(rows, fieldnames=None):
    buffer = io.StringIO()
    fieldnames = fieldnames or (list(rows[0]) if rows else [])
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def fmt(value, digits=2, suffix=''):
    # Espacio no separable como separador de miles: el número no se parte en pantallas angostas.
    return '—' if value is None else f'{value:,.{digits}f}{suffix}'.replace(',', '\u00a0')


def fmt_ci(ci, digits=1):
    return '—' if not ci else f'{ci[0]:.{digits}f} – {ci[1]:.{digits}f}'


def e(text):
    return html.escape(str(text), quote=True)


PAGE_CSS = ("body{font:16px/1.5 system-ui,sans-serif;background:#101d2c;color:#eef4fb;max-width:1150px;"
            "margin:auto;padding:24px 16px}h1{font-size:clamp(28px,6vw,44px);margin:8px 0}"
            ".card{background:#1c3046;padding:20px;border-radius:14px;margin:18px 0}"
            ".scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:15px}"
            "th,td{text-align:left;padding:10px;border-bottom:1px solid #456;vertical-align:top}"
            ".tag{color:#56deb8;letter-spacing:.04em;font-size:14px}a{color:#56deb8}.muted{color:#b5c4d6}"
            ".sel{background:#22445f}")


def page(title, body):
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>'
            f'<style>{PAGE_CSS}</style></head><body>'
            '<span class="tag">MINERÍA SUBTERRÁNEA · DATOS SIMULADOS · NO VALIDADO OPERACIONALMENTE</span>'
            f'{body}</body></html>')


def model_label(report):
    if report.get('model_version') == 1:
        return 'Modelo v1 (histórico, release v1.0.0)'
    side = 'junto a la descarga' if report.get('ramp_side') == 'dump' else 'junto a los frentes'
    return f'Modelo v2 · rampa compartida {side}'


def dashboard_html(c, report):
    names = [r['name'] for r in c['routes']]
    selected = report['best']['allocation'] if report['best'] else None
    sel_attr = ' class="sel"'
    rows = ''.join(
        f"<tr{sel_attr if x['allocation'] == selected else ''}>"
        f"<td>{x['allocation'][0]} / {x['allocation'][1]}</td><td>{fmt(x['mean_tonnes'])}</td>"
        f"<td>{fmt_ci(x['mean_ci95'])}</td><td>{fmt(x['sd_tonnes'])}</td>"
        f"<td>{fmt(x['route_mean_tonnes'][0], 1)} / {fmt(x['route_mean_tonnes'][1], 1)}</td>"
        f"<td>{fmt(x['mean_wait_min'], 1)}</td><td>{fmt(x['cost_per_t'], 3)}</td>"
        f"<td>{'Sí' if x['feasible'] else 'No'}</td></tr>" for x in report['candidates'])
    best = report['best']
    if best and best['allocation'] == c['baseline']:
        headline = (f"Asignación seleccionada: {best['allocation'][0]} en {e(names[0])} y {best['allocation'][1]} "
                    f"en {e(names[1])} · coincide con la base")
        diff = ''
    elif best:
        headline = (f"Asignación seleccionada: {best['allocation'][0]} en {e(names[0])} y {best['allocation'][1]} "
                    f"en {e(names[1])} · {fmt(report['improvement_pct'])} % frente a la base "
                    f"{c['baseline'][0]}/{c['baseline'][1]}")
        d = next(x for x in report['candidates'] if x['allocation'] == best['allocation'])['paired_diff_vs_baseline']
        diff = (f"<p>Diferencia pareada frente a la base: {fmt(d['mean'], 1)} t/guardia "
                f"(IC 95 % de la media: {fmt_ci(d['ci95'])}).</p>")
    else:
        headline, diff = 'Ninguna asignación cumple las metas medias de ambos frentes', ''
    body = (
        f"<h1>MineFleet · Asignación de volquetes</h1><p class='muted'>{e(model_label(report))}</p>"
        f"<div class='card'><h2>{headline}</h2>{diff}<p>{report['replications']} réplicas por asignación "
        f"(semillas {report['seed_range'][0]}–{report['seed_range'][1]}) · flota de {c['fleet']} volquetes · "
        f"metas medias {e(names[0])}/{e(names[1])}: {c['minimum_tonnes'][0]:g}/{c['minimum_tonnes'][1]:g} t · "
        f"guardia simulada de {c['shift_min']:g} min.</p></div>"
        f"<div class='card scroll'><table><thead><tr><th>Volquetes {e(names[0])} / {e(names[1])}</th>"
        "<th>t/guardia media</th><th>IC 95 % de la media</th><th>Desv. estándar entre guardias</th>"
        f"<th>Media por frente {e(names[0])} / {e(names[1])}</th><th>Espera total (min)</th>"
        "<th>S/ por t (costo fijo / media)</th><th>Cumple metas medias</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        "<p>La desviación estándar describe la variación entre guardias; el IC 95 % describe la incertidumbre "
        "de estimar la media con este número de réplicas. Cumplir la meta media no garantiza cumplirla en cada guardia.</p>"
        "<p>Costo supuesto = flota × horas de guardia × costo por hora de volquete; no es un presupuesto real. "
        "Selección exhaustiva entre asignaciones estáticas; no es despacho dinámico ni aprendizaje automático. "
        "<a href='summary.json'>Resultados JSON</a> · <a href='events.csv'>Eventos CSV</a></p>")
    return page('MineFleet | Resultados', body)


EVENT_FIELDS = ['truck', 'route', 'stage', 'arrival', 'start', 'end', 'resource', 'counts_in_shift']


def export(c, report, out, events):
    write_files(out, {
        'summary.json': json.dumps(report, indent=2, ensure_ascii=False),
        'events.csv': csv_text(events, EVENT_FIELDS),
        'dashboard.html': dashboard_html(c, report),
    })


def load_scenario(path):
    try:
        c = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise SystemExit(f'No se encontró el escenario: {path}')
    except json.JSONDecodeError as exc:
        raise SystemExit(f'El escenario {path} no es JSON válido: {exc}')
    return c


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--scenario', type=Path, default=ROOT / 'data/scenario.json')
    parser.add_argument('--out', type=Path, default=ROOT / 'results')
    args = parser.parse_args()
    c = load_scenario(args.scenario)
    try:
        report = optimize(c)
    except ValueError as exc:
        raise SystemExit(f'Escenario inválido: {exc}')
    allocation = report['best']['allocation'] if report['best'] else c['baseline']
    events = simulate(c, allocation, c['seed'], True)['events']
    export(c, report, args.out, events)
    best = report['best']
    print(model_label(report))
    print('Seleccionada:', best['allocation'] if best else 'ninguna cumple las metas medias',
          '|', fmt(best['mean_tonnes']) if best else '', 't/guardia |',
          'mejora vs base:', fmt(report['improvement_pct']), '%')
    print('Panel:', args.out / 'dashboard.html')


if __name__ == '__main__':
    main()
