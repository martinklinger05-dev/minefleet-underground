"""Cumplimiento de metas por guardia bajo el modelo MineFleet. Solo biblioteca estándar.

Cuenta directamente las guardias simuladas que cumplen ambas metas a la vez (no multiplica
frecuencias marginales: los frentes comparten rampa y descarga, sus resultados dependen entre sí).
"""
import argparse
import collections
import copy
import json
import math
import statistics
from pathlib import Path
from minefleet import (ROOT, candidate_allocations, csv_text, e, fmt, load_scenario, mean_ci, model_label,
                       page, simulate, validate, write_files)

Z95 = 1.959963984540054


def wilson(successes, trials):
    """Intervalo de Wilson bilateral del 95 % para una proporción binomial."""
    if type(trials) is not int or trials < 1 or type(successes) is not int or not 0 <= successes <= trials:
        raise ValueError('Conteo de éxitos o tamaño de muestra inválido')
    z = Z95
    p = successes / trials
    d = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / d
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / d
    return [max(0.0, center - half), min(1.0, center + half)]


def summarize(runs, targets, allocation):
    counts = [sum(r['route_tonnes'][i] >= targets[i] for r in runs) for i in range(2)]
    joint = sum(all(t >= goal for t, goal in zip(r['route_tonnes'], targets)) for r in runs)
    route_values = [[r['route_tonnes'][i] for r in runs] for i in range(2)]
    means = [statistics.mean(v) for v in route_values]
    n = len(runs)
    return {'allocation': list(allocation), 'replications': n,
            'mean_tonnes': statistics.mean(r['tonnes'] for r in runs),
            'mean_ci95': mean_ci([r['tonnes'] for r in runs])['ci95'],
            'route_mean_tonnes': means,
            'route_mean_ci95': [mean_ci(v)['ci95'] for v in route_values],
            'mean_targets_met': all(t >= goal for t, goal in zip(means, targets)),
            'front_success_counts': counts, 'front_success_rates': [k / n for k in counts],
            'joint_success_count': joint, 'joint_success_rate': joint / n,
            'joint_wilson_95': wilson(joint, n),
            # Distribución de toneladas por frente: muestra cuántas guardias quedan justo en la meta.
            'route_tonnes_distribution': [{f'{k:g}': v for k, v in sorted(collections.Counter(vals).items())}
                                          for vals in route_values]}


def analyze(config, times, replications=1000, seed_start=None):
    if type(replications) is not int or replications < 1:
        raise ValueError('El número de réplicas debe ser un entero positivo')
    if not times or len(set(times)) != len(times):
        raise ValueError('Indique tiempos de rampa distintos')
    seed_start = config['seed'] if seed_start is None else seed_start
    if type(seed_start) is not int:
        raise ValueError('La semilla inicial debe ser un entero')
    seeds = list(range(seed_start, seed_start + replications))
    scenarios, records = [], []
    for time in sorted(times):
        c = copy.deepcopy(config)
        c['ramp_crossing_min'] = time
        validate(c)
        candidates = []
        for allocation in candidate_allocations(c):
            runs = []
            for i, seed in enumerate(seeds):
                run = simulate(c, allocation, seed)
                runs.append(run)
                records.append({'ramp_min': time, 'trucks_A': allocation[0], 'trucks_B': allocation[1],
                                'replication': i + 1, 'seed': seed, 'tonnes': run['tonnes'],
                                'front_A_t': run['route_tonnes'][0], 'front_B_t': run['route_tonnes'][1],
                                'both_targets_met': all(t >= g for t, g in zip(run['route_tonnes'], c['minimum_tonnes']))})
            candidates.append(summarize(runs, c['minimum_tonnes'], allocation))
        scenarios.append({'ramp_min': time, 'candidates': candidates})
    return {'data_type': 'SIMULATED', 'model_version': config.get('model_version', 2),
            'ramp_side': None if config.get('model_version', 2) == 1 else config.get('ramp_side', 'dump'),
            'scenario': copy.deepcopy(config), 'analysis_replications': replications,
            'seed_range': [seeds[0], seeds[-1]], 'scenarios': scenarios}, records


def comparison_rows(report):
    rows = []
    for entry in report['scenarios']:
        for c in entry['candidates']:
            lo, hi = c['joint_wilson_95']
            rows.append({'ramp_min': entry['ramp_min'], 'trucks_A': c['allocation'][0], 'trucks_B': c['allocation'][1],
                         'mean_tonnes': c['mean_tonnes'], 'front_A_mean_t': c['route_mean_tonnes'][0],
                         'front_B_mean_t': c['route_mean_tonnes'][1], 'mean_targets_met': c['mean_targets_met'],
                         'joint_success_count': c['joint_success_count'], 'replications': c['replications'],
                         'joint_success_rate': c['joint_success_rate'], 'wilson_95_low': lo, 'wilson_95_high': hi})
    return rows


def export(report, records, out):
    rows = comparison_rows(report)
    config = report['scenario']
    names = [r['name'] for r in config['routes']]
    table = ''.join(
        f"<tr><td>{r['ramp_min']:g}</td><td>{r['trucks_A']}/{r['trucks_B']}</td><td>{fmt(r['mean_tonnes'])}</td>"
        f"<td>{fmt(r['front_A_mean_t'], 2)} / {fmt(r['front_B_mean_t'], 2)}</td>"
        f"<td>{'Sí' if r['mean_targets_met'] else 'No'}</td><td>{r['joint_success_count']}/{r['replications']}</td>"
        f"<td>{100 * r['joint_success_rate']:.1f} %</td>"
        f"<td>{100 * r['wilson_95_low']:.1f} – {100 * r['wilson_95_high']:.1f} %</td></tr>" for r in rows)
    body = (f"<h1>MineFleet · Cumplimiento por guardia</h1><p class='muted'>{e(model_label(report))}</p>"
            f"<div class='card'>{report['analysis_replications']} guardias simuladas por asignación "
            f"(semillas {report['seed_range'][0]}–{report['seed_range'][1]}) · metas {e(names[0])}/{e(names[1])}: "
            f"{config['minimum_tonnes'][0]:g}/{config['minimum_tonnes'][1]:g} t.</div>"
            f"<div class='card scroll'><table><tr><th>Rampa (min)</th><th>{e(names[0])}/{e(names[1])}</th>"
            f"<th>Media t/guardia</th><th>Media por frente {e(names[0])} / {e(names[1])}</th><th>Metas medias</th>"
            "<th>Guardias con ambas metas</th><th>Frecuencia conjunta</th><th>Wilson 95 %</th></tr>"
            f"{table}</table></div>"
            "<p>La frecuencia conjunta cuenta guardias que alcanzan ambas metas a la vez. Una frecuencia alta puede "
            "coexistir con una media ligeramente inferior a la meta: unas pocas guardias con déficit bajan el promedio. "
            "El intervalo de Wilson cuantifica la incertidumbre de muestreo bajo este modelo; no es una probabilidad "
            "validada en una mina real y un 100 % observado no garantiza cumplimiento futuro.</p>"
            "<p>Todas las asignaciones y escenarios reutilizan las mismas semillas: no son muestras independientes entre sí. "
            "Este análisis no selecciona asignaciones; para eso ver policy.py y validation.py.</p>"
            "<p><a href='comparison.csv'>Tabla CSV</a> · <a href='replications.csv'>Guardias simuladas CSV</a> · "
            "<a href='summary.json'>Resultados JSON</a></p>")
    write_files(out, {'summary.json': json.dumps(report, indent=2, ensure_ascii=False),
                      'replications.csv': csv_text(records), 'comparison.csv': csv_text(rows),
                      'dashboard.html': page('MineFleet | Cumplimiento por guardia', body)})


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--scenario', type=Path, default=ROOT / 'data/scenario.json')
    p.add_argument('--times', type=float, nargs='+', default=[2, 3])
    p.add_argument('--replications', type=int, default=1000)
    p.add_argument('--seed-start', type=int, default=None, help='Semilla inicial (predeterminada: la del escenario)')
    p.add_argument('--out', type=Path, default=ROOT / 'results_reliability')
    args = p.parse_args()
    config = load_scenario(args.scenario)
    try:
        report, records = analyze(config, args.times, args.replications, args.seed_start)
    except ValueError as exc:
        raise SystemExit(f'Escenario inválido: {exc}')
    export(report, records, args.out)
    for entry in report['scenarios']:
        for c in entry['candidates']:
            print(f"Rampa {entry['ramp_min']:g} min | {c['allocation']} | {c['mean_tonnes']:.2f} t | "
                  f"metas medias: {'sí' if c['mean_targets_met'] else 'no'} | ambas metas: "
                  f"{c['joint_success_count']}/{c['replications']}")
    print('Panel:', args.out / 'dashboard.html')


if __name__ == '__main__':
    main()
