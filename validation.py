"""Validación fuera de muestra de las selecciones de policy.py.

1. Lee el lote de SELECCIÓN (results_reliability/summary.json) y aplica los tres criterios.
2. Simula un lote de VALIDACIÓN con semillas nuevas que no se solapan con las de selección.
3. Reporta, por separado, las métricas de selección y las de validación de cada asignación elegida,
   si seguiría siendo elegible y si la elección cambiaría al repetirla con el lote nuevo.
4. Describe qué ocurre cerca de las metas: distribución de toneladas por frente.
"""
import argparse
import json
from pathlib import Path
from minefleet import ROOT, csv_text, e, fmt, fmt_ci, model_label, page, write_files
from policy import CRITERIA, CRITERIA_TEXT, alloc_text, apply, check_threshold, eligible, load_json
from reliability import analyze

DEFAULT_VALIDATION_SEED = 1_000_000


def check_disjoint(selection_range, start, count):
    lo, hi = selection_range
    if not (start + count - 1 < lo or start > hi):
        raise ValueError(f'Las semillas de validación {start}–{start + count - 1} se solapan con las de selección {lo}–{hi}')


def near_target(candidate, targets, payload):
    """Para cada frente cuya media está a menos de una carga de la meta, resume las guardias
    por debajo, exactamente en, y por encima de la meta."""
    out = []
    for i, (m, goal) in enumerate(zip(candidate['route_mean_tonnes'], targets)):
        if abs(m - goal) <= payload:
            dist = {float(k): v for k, v in candidate['route_tonnes_distribution'][i].items()}
            n = sum(dist.values())
            out.append({'front': i, 'target': goal, 'mean': m,
                        'below': sum(v for k, v in dist.items() if k < goal) / n,
                        'at': sum(v for k, v in dist.items() if k == goal) / n,
                        'above': sum(v for k, v in dist.items() if k > goal) / n,
                        'distribution': candidate['route_tonnes_distribution'][i]})
    return out


def compare(selection, validation_batch, threshold):
    """Une resultados de selección y validación sin mezclarlos."""
    sel_policy = apply(selection, threshold)
    val_policy = apply(validation_batch, threshold)
    config = selection['scenario']
    results = []
    for s_entry, v_entry, sel_raw, val_raw in zip(sel_policy['scenarios'], val_policy['scenarios'],
                                                  selection['scenarios'], validation_batch['scenarios']):
        if s_entry['ramp_min'] != v_entry['ramp_min']:
            raise ValueError('Los lotes de selección y validación no tienen los mismos escenarios')
        val_by_alloc = {tuple(c['allocation']): c for c in val_raw['candidates']}
        criteria = {}
        for crit in CRITERIA:
            chosen = s_entry['selections'][crit]
            redo = v_entry['selections'][crit]
            item = {'selected': chosen, 'reselected_on_validation': redo,
                    'stable': (chosen and chosen['allocation']) == (redo and redo['allocation'])}
            if chosen:
                v = val_by_alloc[tuple(chosen['allocation'])]
                item['validation'] = {'mean_tonnes': v['mean_tonnes'], 'mean_ci95': v['mean_ci95'],
                                      'route_mean_tonnes': v['route_mean_tonnes'],
                                      'route_mean_ci95': v['route_mean_ci95'],
                                      'mean_targets_met': v['mean_targets_met'],
                                      'joint_success_count': v['joint_success_count'],
                                      'replications': v['replications'], 'joint_wilson_95': v['joint_wilson_95'],
                                      'still_eligible': eligible(v, crit, threshold)}
            criteria[crit] = item
        near = []
        for phase, raw in (('selection', sel_raw), ('validation', val_raw)):
            for c in raw['candidates']:
                for info in near_target(c, config['minimum_tonnes'], config['payload_t']):
                    near.append(dict(info, phase=phase, allocation=c['allocation']))
        results.append({'ramp_min': s_entry['ramp_min'], 'criteria': criteria, 'near_target': near})
    return results


def run(selection, threshold=0.95, replications=None, seed_start=DEFAULT_VALIDATION_SEED):
    check_threshold(threshold)
    config = selection['scenario']
    replications = replications or selection['analysis_replications']
    check_disjoint(selection['seed_range'], seed_start, replications)
    times = [entry['ramp_min'] for entry in selection['scenarios']]
    validation_batch, _ = analyze(config, times, replications, seed_start)
    return {'data_type': 'SIMULATED', 'threshold': threshold, 'model_version': selection.get('model_version'),
            'ramp_side': selection.get('ramp_side'), 'criteria': CRITERIA_TEXT,
            'selection_batch': {'replications': selection['analysis_replications'], 'seed_range': selection['seed_range'],
                                'use': 'Solo para elegir la asignación'},
            'validation_batch': {'replications': replications, 'seed_range': validation_batch['seed_range'],
                                 'use': 'Solo para evaluar la asignación ya elegida'},
            'scenario': config, 'scenarios': compare(selection, validation_batch, threshold)}


def rows_for_csv(report):
    rows = []
    for entry in report['scenarios']:
        for crit in CRITERIA:
            item = entry['criteria'][crit]
            s, v, r = item['selected'], item.get('validation'), item['reselected_on_validation']
            rows.append({
                'ramp_min': entry['ramp_min'], 'criterion': crit, 'selected': alloc_text(s),
                'selection_mean_t': s and s['mean_tonnes'],
                'selection_joint': s and f"{s['joint_success_count']}/{s['replications']}",
                'validation_mean_t': v and v['mean_tonnes'],
                'validation_mean_ci95_low': v and v['mean_ci95'][0], 'validation_mean_ci95_high': v and v['mean_ci95'][1],
                'validation_front_A_t': v and v['route_mean_tonnes'][0], 'validation_front_B_t': v and v['route_mean_tonnes'][1],
                'validation_joint': v and f"{v['joint_success_count']}/{v['replications']}",
                'validation_wilson_low': v and v['joint_wilson_95'][0], 'validation_wilson_high': v and v['joint_wilson_95'][1],
                'still_eligible': v and v['still_eligible'], 'reselected_on_validation': alloc_text(r),
                'stable': item['stable']})
    return rows


def export(report, out):
    names = [r['name'] for r in report['scenario']['routes']]
    sb, vb = report['selection_batch'], report['validation_batch']
    crit_name = {'mean': 'Metas medias', 'frequency': 'Frecuencia', 'wilson': 'Wilson'}
    main_rows, near_rows = '', ''
    for entry in report['scenarios']:
        for crit in CRITERIA:
            item = entry['criteria'][crit]
            s, v = item['selected'], item.get('validation')
            sel = (f"{alloc_text(s)}<br><span class='muted'>{fmt(s['mean_tonnes'])} t · "
                   f"{s['joint_success_count']}/{s['replications']}</span>") if s else 'Sin elegibles'
            if v:
                val = (f"{fmt(v['mean_tonnes'])} t <span class='muted'>(IC {fmt_ci(v['mean_ci95'])})</span><br>"
                       f"{e(names[0])}/{e(names[1])}: {fmt(v['route_mean_tonnes'][0], 2)} / {fmt(v['route_mean_tonnes'][1], 2)}<br>"
                       f"Ambas metas {v['joint_success_count']}/{v['replications']} "
                       f"<span class='muted'>(Wilson {100 * v['joint_wilson_95'][0]:.1f}–{100 * v['joint_wilson_95'][1]:.1f} %)</span>")
                still = 'Sí' if v['still_eligible'] else '<b>No</b>'
            else:
                val, still = '—', '—'
            stable = 'Sí' if item['stable'] else f"<b>No</b> → {alloc_text(item['reselected_on_validation'])}"
            main_rows += (f"<tr><td>{entry['ramp_min']:g}</td><td>{crit_name[crit]}</td><td>{sel}</td><td>{val}</td>"
                          f"<td>{still}</td><td>{stable}</td></tr>")
        for n in entry['near_target']:
            phase = 'Selección' if n['phase'] == 'selection' else 'Validación'
            near_rows += (f"<tr><td>{entry['ramp_min']:g}</td><td>{n['allocation'][0]}/{n['allocation'][1]}</td>"
                          f"<td>{e(names[n['front']])}</td><td>{phase}</td><td>{fmt(n['mean'], 2)}</td>"
                          f"<td>{100 * n['below']:.1f} %</td><td>{100 * n['at']:.1f} %</td><td>{100 * n['above']:.1f} %</td></tr>")
    body = (f"<h1>MineFleet · Validación fuera de muestra</h1><p class='muted'>{e(model_label(report))} · "
            f"umbral {report['threshold']:g}</p>"
            f"<div class='card'><p><b>Lote de selección</b>: {sb['replications']} guardias por asignación, semillas "
            f"{sb['seed_range'][0]}–{sb['seed_range'][1]}. Solo se usa para elegir.</p>"
            f"<p><b>Lote de validación</b>: {vb['replications']} guardias por asignación, semillas "
            f"{vb['seed_range'][0]}–{vb['seed_range'][1]}, sin solapamiento. Solo se usa para evaluar la elección.</p>"
            "<p>Frecuencia y Wilson sustituyen el filtro de metas medias; no lo añaden.</p></div>"
            "<div class='card scroll'><table><tr><th>Rampa (min)</th><th>Criterio</th><th>Elegida en selección</th>"
            "<th>Resultado en validación</th><th>¿Sigue siendo elegible?</th><th>¿Misma elección con el lote nuevo?</th></tr>"
            f"{main_rows}</table></div>"
            "<h2>Cerca de la meta</h2><p>Frentes cuya media queda a menos de una carga de la meta. Como la producción "
            "es un múltiplo de la carga útil, una meta igual a un número entero de viajes concentra muchas guardias "
            "<i>exactamente</i> en la meta: la media puede quedar justo debajo aunque casi todas las guardias cumplan.</p>"
            "<div class='card scroll'><table><tr><th>Rampa</th><th>A/B</th><th>Frente</th><th>Lote</th><th>Media t</th>"
            f"<th>Bajo la meta</th><th>Justo en la meta</th><th>Sobre la meta</th></tr>{near_rows}</table></div>"
            "<p>Limitaciones: es una validación dentro del mismo modelo simulado, no contra datos operacionales. "
            "Los intervalos son individuales, sin corrección por comparaciones múltiples. Las frecuencias son "
            "estimaciones bajo los supuestos del modelo, no probabilidades reales validadas.</p>"
            "<p><a href='comparison.csv'>Tabla CSV</a> · <a href='summary.json'>Resultados JSON</a> · "
            "<a href='../results_policy/dashboard.html'>Criterios (lote de selección)</a></p>")
    write_files(out, {'summary.json': json.dumps(report, indent=2, ensure_ascii=False),
                      'comparison.csv': csv_text(rows_for_csv(report)),
                      'dashboard.html': page('MineFleet | Validación', body)})


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--selection', type=Path, default=ROOT / 'results_reliability/summary.json')
    p.add_argument('--threshold', type=float, default=0.95)
    p.add_argument('--replications', type=int, default=None, help='Predeterminado: igual al lote de selección')
    p.add_argument('--seed-start', type=int, default=DEFAULT_VALIDATION_SEED)
    p.add_argument('--out', type=Path, default=ROOT / 'results_validation')
    args = p.parse_args()
    try:
        report = run(load_json(args.selection), args.threshold, args.replications, args.seed_start)
    except ValueError as exc:
        raise SystemExit(f'Entrada inválida: {exc}')
    export(report, args.out)
    for entry in report['scenarios']:
        for crit in CRITERIA:
            item = entry['criteria'][crit]
            v = item.get('validation')
            print(f"Rampa {entry['ramp_min']:g} | {crit:9} | elegida {alloc_text(item['selected'])} | "
                  f"validación: {fmt(v['mean_tonnes']) + ' t, ambas metas ' + str(v['joint_success_count']) + '/' + str(v['replications']) + (', sigue elegible' if v['still_eligible'] else ', YA NO elegible') if v else '—'} | "
                  f"estable: {'sí' if item['stable'] else 'no'}")
    print('Panel:', args.out / 'dashboard.html')


if __name__ == '__main__':
    main()
