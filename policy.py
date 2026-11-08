"""Criterios de selección sobre resultados de cumplimiento (no vuelve a simular).

Versión integrada en 2.0; reproduce los resultados de criterios obtenidos con el modelo v1.

Criterios (cada uno es un filtro alternativo; frequency y wilson SUSTITUYEN el filtro de metas
medias, no lo añaden):
  mean      ambos frentes alcanzan sus metas medias
  frequency frecuencia conjunta observada de guardias con ambas metas >= umbral
  wilson    límite inferior del intervalo de Wilson bilateral 95 % de esa frecuencia >= umbral
Entre las elegibles se elige la mayor producción media; en empate, la asignación
lexicográficamente menor.
"""
import argparse
import json
import math
from pathlib import Path
from minefleet import ROOT, csv_text, e, fmt, page, write_files

CRITERIA = ('mean', 'frequency', 'wilson')
CRITERIA_TEXT = {
    'mean': 'Metas medias: la media de cada frente alcanza su meta',
    'frequency': 'Frecuencia: proporción observada de guardias con ambas metas ≥ umbral',
    'wilson': 'Wilson: límite inferior del IC 95 % de esa proporción ≥ umbral',
}


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_reliability(data):
    """Comprueba la estructura del summary.json de reliability.py antes de usarlo."""
    if not isinstance(data, dict) or not isinstance(data.get('scenarios'), list) or not data['scenarios']:
        raise ValueError('El archivo no contiene una lista "scenarios" de reliability.py')
    for i, entry in enumerate(data['scenarios']):
        where = f'scenarios[{i}]'
        if not isinstance(entry, dict) or not _num(entry.get('ramp_min')):
            raise ValueError(f'{where}: falta ramp_min numérico')
        cands = entry.get('candidates')
        if not isinstance(cands, list) or not cands:
            raise ValueError(f'{where}: falta la lista de candidatos')
        seen = set()
        for j, c in enumerate(cands):
            w = f'{where}.candidates[{j}]'
            if not isinstance(c, dict):
                raise ValueError(f'{w}: debe ser un objeto')
            a = c.get('allocation')
            if not isinstance(a, list) or len(a) != 2 or any(type(n) is not int or n < 0 for n in a):
                raise ValueError(f'{w}: allocation inválida')
            if tuple(a) in seen:
                raise ValueError(f'{w}: asignación repetida {a}')
            seen.add(tuple(a))
            n, k = c.get('replications'), c.get('joint_success_count')
            if type(n) is not int or n < 1 or type(k) is not int or not 0 <= k <= n:
                raise ValueError(f'{w}: conteos de réplicas o de éxitos inválidos')
            if not _num(c.get('mean_tonnes')) or type(c.get('mean_targets_met')) is not bool:
                raise ValueError(f'{w}: faltan mean_tonnes o mean_targets_met')
            ci = c.get('joint_wilson_95')
            if not isinstance(ci, list) or len(ci) != 2 or not all(_num(x) and 0 <= x <= 1 for x in ci) or ci[0] > ci[1]:
                raise ValueError(f'{w}: joint_wilson_95 inválido')
    return data


def eligible(candidate, criterion, threshold):
    if criterion == 'mean':
        return candidate['mean_targets_met']
    if criterion == 'frequency':
        return candidate['joint_success_count'] / candidate['replications'] >= threshold
    if criterion == 'wilson':
        return candidate['joint_wilson_95'][0] >= threshold
    raise ValueError(f'Criterio desconocido: {criterion}')


def select(candidates, criterion, threshold):
    """Mayor producción media entre elegibles; empate → asignación lexicográficamente menor."""
    pool = [c for c in candidates if eligible(c, criterion, threshold)]
    if not pool:
        return None
    return min(pool, key=lambda c: (-c['mean_tonnes'], c['allocation']))


def check_threshold(threshold):
    if not _num(threshold) or not 0 <= threshold <= 1:
        raise ValueError('El umbral debe ser un número entre 0 y 1')


def apply(data, threshold=0.95):
    check_threshold(threshold)
    validate_reliability(data)
    scenarios = []
    for entry in data['scenarios']:
        cands = entry['candidates']
        selections = {}
        for crit in CRITERIA:
            best = select(cands, crit, threshold)
            selections[crit] = None if best is None else {
                'allocation': best['allocation'], 'mean_tonnes': best['mean_tonnes'],
                'route_mean_tonnes': best.get('route_mean_tonnes'), 'mean_targets_met': best['mean_targets_met'],
                'joint_success_count': best['joint_success_count'], 'replications': best['replications'],
                'joint_wilson_95': best['joint_wilson_95']}
        rows = [{'allocation': c['allocation'], 'mean_tonnes': c['mean_tonnes'],
                 'route_mean_tonnes': c.get('route_mean_tonnes'), 'mean_targets_met': c['mean_targets_met'],
                 'joint_success_count': c['joint_success_count'], 'replications': c['replications'],
                 'joint_wilson_95': c['joint_wilson_95'],
                 'eligible': {crit: eligible(c, crit, threshold) for crit in CRITERIA}} for c in cands]
        scenarios.append({'ramp_min': entry['ramp_min'], 'selections': selections, 'candidates': rows})
    return {'data_type': 'SIMULATED', 'threshold': threshold, 'criteria': CRITERIA_TEXT,
            'note': 'frequency y wilson sustituyen el filtro de metas medias; no lo añaden.',
            'source': {'model_version': data.get('model_version'), 'ramp_side': data.get('ramp_side'),
                       'replications': data.get('analysis_replications'), 'seed_range': data.get('seed_range')},
            'scenarios': scenarios}


def alloc_text(sel):
    return '—' if sel is None else f"{sel['allocation'][0]}/{sel['allocation'][1]}"


def export(report, out):
    rows = []
    for entry in report['scenarios']:
        for c in entry['candidates']:
            lo, hi = c['joint_wilson_95']
            row = {'ramp_min': entry['ramp_min'], 'trucks_A': c['allocation'][0], 'trucks_B': c['allocation'][1],
                   'mean_tonnes': c['mean_tonnes'], 'mean_targets_met': c['mean_targets_met'],
                   'joint_success_count': c['joint_success_count'], 'replications': c['replications'],
                   'wilson_95_low': lo, 'wilson_95_high': hi}
            for crit in CRITERIA:
                row[f'eligible_{crit}'] = c['eligible'][crit]
                sel = entry['selections'][crit]
                row[f'selected_{crit}'] = bool(sel) and sel['allocation'] == c['allocation']
            rows.append(row)
    src = report['source']
    seeds = f"{src['seed_range'][0]}–{src['seed_range'][1]}" if src.get('seed_range') else '—'
    sel_rows = ''.join(
        f"<tr><td>{entry['ramp_min']:g}</td>" + ''.join(
            f"<td>{alloc_text(entry['selections'][crit])}<br><span class='muted'>"
            f"{fmt(entry['selections'][crit]['mean_tonnes']) + ' t' if entry['selections'][crit] else 'sin elegibles'}"
            "</span></td>" for crit in CRITERIA) + '</tr>' for entry in report['scenarios'])
    detail = ''.join(
        f"<tr><td>{r['ramp_min']:g}</td><td>{r['trucks_A']}/{r['trucks_B']}</td><td>{fmt(r['mean_tonnes'])}</td>"
        f"<td>{r['joint_success_count']}/{r['replications']}</td>"
        f"<td>{100 * r['wilson_95_low']:.1f} – {100 * r['wilson_95_high']:.1f} %</td>"
        + ''.join(f"<td>{'✔' if r[f'eligible_{c}'] else '·'}{' ★' if r[f'selected_{c}'] else ''}</td>" for c in CRITERIA)
        + '</tr>' for r in rows)
    crit_list = ''.join(f'<li>{e(t)}</li>' for t in CRITERIA_TEXT.values())
    body = (f"<h1>MineFleet · Criterios de selección</h1><p class='muted'>Umbral {report['threshold']:g} · "
            f"fuente: {src['replications']} réplicas por asignación, semillas {seeds} · modelo v{e(src['model_version'])}</p>"
            f"<div class='card'><ul>{crit_list}</ul><p><b>Frecuencia y Wilson sustituyen el filtro de metas medias; no lo añaden.</b> "
            "Entre las elegibles se elige la mayor producción media.</p></div>"
            "<div class='card scroll'><table><tr><th>Rampa (min)</th><th>Metas medias</th><th>Frecuencia</th><th>Wilson</th></tr>"
            f"{sel_rows}</table></div><div class='card scroll'><table><tr><th>Rampa</th><th>A/B</th><th>Media t</th>"
            "<th>Ambas metas</th><th>Wilson 95 %</th><th>Elegible: medias</th><th>frecuencia</th><th>Wilson</th></tr>"
            f"{detail}</table><p class='muted'>✔ elegible · ★ seleccionada</p></div>"
            "<p>Limitaciones: el 95 % del umbral y el 95 % del intervalo son conceptos distintos; los intervalos son "
            "individuales, sin corrección por comparar varias alternativas; aquí se elige y se evalúa con las mismas réplicas, "
            "por lo que no es una garantía de cumplimiento tras seleccionar. La validación con semillas nuevas está en "
            "<a href='../results_validation/dashboard.html'>results_validation</a>.</p>"
            "<p><a href='comparison.csv'>Tabla CSV</a> · <a href='summary.json'>Resultados JSON</a></p>")
    write_files(out, {'summary.json': json.dumps(report, indent=2, ensure_ascii=False),
                      'comparison.csv': csv_text(rows), 'dashboard.html': page('MineFleet | Criterios', body)})


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise SystemExit(f'No se encontró {path}. Ejecute primero: python reliability.py')
    except json.JSONDecodeError as exc:
        raise SystemExit(f'{path} no es JSON válido: {exc}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--input', type=Path, default=ROOT / 'results_reliability/summary.json')
    p.add_argument('--threshold', type=float, default=0.95)
    p.add_argument('--out', type=Path, default=ROOT / 'results_policy')
    args = p.parse_args()
    try:
        report = apply(load_json(args.input), args.threshold)
    except ValueError as exc:
        raise SystemExit(f'Entrada inválida: {exc}')
    export(report, args.out)
    for entry in report['scenarios']:
        print(f"Rampa {entry['ramp_min']:g} min | " + ' | '.join(
            f"{crit}: {alloc_text(entry['selections'][crit])}" for crit in CRITERIA))
    print('Panel:', args.out / 'dashboard.html')


if __name__ == '__main__':
    main()
