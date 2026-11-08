"""Sensibilidad a la ocupación de la rampa compartida. Solo biblioteca estándar.

Al cambiar ramp_crossing_min se mantienen fijos loaded_min y empty_min (que ya incluyen la rampa):
aumenta la ocupación del recurso compartido y disminuye el viaje fuera de rampa. El tiempo nominal
total sin colas no cambia, pero sí las esperas y la variabilidad (la rampa es fija y el resto aleatorio).
"""
import argparse
import copy
import json
from pathlib import Path
from minefleet import (ROOT, csv_text, e, fmt, fmt_ci, load_scenario, model_label, optimize, page,
                       validate_allocation, write_files)

INTERPRETATION = ('Los tiempos totales de viaje (loaded_min, empty_min) se mantienen fijos; cambia la ocupación '
                  'del recurso rampa y, en sentido contrario, el viaje fuera de rampa.')


def compare(config, times):
    if not times or len(set(times)) != len(times):
        raise ValueError('Indique tiempos de rampa distintos')
    reports = []
    for time in sorted(times):
        scenario = copy.deepcopy(config)
        scenario['ramp_crossing_min'] = time
        reports.append({'ramp_min': time, 'report': optimize(scenario)})
    return reports


def _series(reports, allocation):
    return [(entry['ramp_min'], next((x for x in entry['report']['candidates'] if x['allocation'] == allocation), None))
            for entry in reports]


def svg_chart(config, reports, highlight):
    xmin, xmax = reports[0]['ramp_min'], reports[-1]['ramp_min']
    ymax = max(x['mean_tonnes'] for entry in reports for x in entry['report']['candidates']) * 1.1 or 1

    def x(t): return 80 + (t - xmin) / (xmax - xmin or 1) * 640

    def y(v): return 330 - v / ymax * 270
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400" role="img" '
             'aria-label="Producción media frente a la ocupación de rampa"><rect width="800" height="400" fill="#fff"/>']
    for tick in range(5):
        value = ymax * tick / 4
        parts.append(f'<path d="M80 {y(value):.1f}H720" stroke="#ddd"/>'
                     f'<text x="15" y="{y(value) + 5:.1f}" font-size="13">{value:.0f}</text>')
    for entry in reports:
        parts.append(f'<text x="{x(entry["ramp_min"]):.1f}" y="355" text-anchor="middle">{entry["ramp_min"]:g}</text>')
    lines = [(config['baseline'], '#2563eb')]
    if highlight and highlight != config['baseline']:
        lines.append((highlight, '#d97706'))
    for allocation, color in lines:
        pts = [(t, c) for t, c in _series(reports, allocation) if c]
        parts.append('<polyline points="' + ' '.join(f'{x(t):.1f},{y(c["mean_tonnes"]):.1f}' for t, c in pts)
                     + f'" fill="none" stroke="{color}" stroke-width="3"/>')
        for t, c in pts:  # barras = IC 95 % de la media (incertidumbre de estimación)
            if c['mean_ci95']:
                lo, hi = c['mean_ci95']
                parts.append(f'<path d="M{x(t):.1f} {y(lo):.1f}V{y(hi):.1f}" stroke="{color}" stroke-width="2"/>')
    for entry in reports:
        best = entry['report']['best']
        if best:
            parts.append(f'<circle cx="{x(entry["ramp_min"]):.1f}" cy="{y(best["mean_tonnes"]):.1f}" r="6" fill="#059669"/>')
    parts.append('<text x="80" y="25">Producción media (t/guardia)</text>'
                 '<text x="250" y="390">Ocupación de rampa por cruce (min)</text></svg>')
    return ''.join(parts)


def export(config, reports, out, highlight=None):
    rows = []
    for entry in reports:
        report = entry['report']
        for c in report['candidates']:
            lo, hi = c['mean_ci95'] or (None, None)
            rows.append({'ramp_min': entry['ramp_min'], 'trucks_A': c['allocation'][0], 'trucks_B': c['allocation'][1],
                         'mean_tonnes': c['mean_tonnes'], 'mean_ci95_low': lo, 'mean_ci95_high': hi,
                         'sd_tonnes': c['sd_tonnes'], 'front_A_t': c['route_mean_tonnes'][0],
                         'front_B_t': c['route_mean_tonnes'][1], 'feasible': c['feasible'],
                         'selected': bool(report['best']) and c['allocation'] == report['best']['allocation']})
    graphic = svg_chart(config, reports, highlight)
    names = [r['name'] for r in config['routes']]
    table = ''
    for entry in reports:
        r, b = entry['report'], entry['report']['best']
        chosen = f'{b["allocation"][0]}/{b["allocation"][1]}' if b else 'Ninguna cumple ambas metas medias'
        table += (f'<tr><td>{entry["ramp_min"]:g}</td><td>{fmt(r["baseline"]["mean_tonnes"])}</td>'
                  f'<td>{chosen}</td>'
                  f'<td>{fmt(b["mean_tonnes"]) if b else "—"}</td><td>{fmt_ci(b["mean_ci95"]) if b else "—"}</td></tr>')
    legend = f'Azul: base fija {config["baseline"][0]}/{config["baseline"][1]}'
    if highlight and highlight != config['baseline']:
        legend += f' · Naranja: fija {highlight[0]}/{highlight[1]}'
    model = model_label(reports[0]['report'])
    body = (f'<h1>MineFleet · Sensibilidad de rampa</h1><p class="muted">{e(model)} · {config["replications"]} réplicas '
            f'por asignación · semilla inicial {config["seed"]} · flota de {config["fleet"]}</p>'
            f'<div class="card">{graphic}<p>{e(legend)} · Verde: selección factible por metas medias '
            '(puede ser una asignación distinta en cada punto). Las barras verticales son el IC 95 % de la media.</p></div>'
            f'<div class="card scroll"><table><tr><th>Cruce (min)</th><th>Base (t/guardia)</th>'
            f'<th>Selección {e(names[0])}/{e(names[1])}</th><th>Selección (t/guardia)</th><th>IC 95 % de la media</th></tr>'
            f'{table}</table></div><p>{e(INTERPRETATION)} Las metas se evalúan sobre medias; no garantizan cumplimiento '
            'en cada guardia. Los escenarios reutilizan las mismas semillas: no son muestras independientes entre sí.</p>'
            '<p><a href="comparison.csv">Tabla CSV</a> · <a href="summary.json">Resultados JSON</a></p>')
    payload = {'data_type': 'SIMULATED', 'scenario': config, 'interpretation': INTERPRETATION, 'scenarios': reports}
    write_files(out, {'summary.json': json.dumps(payload, indent=2, ensure_ascii=False),
                      'comparison.csv': csv_text(rows), 'production.svg': graphic,
                      'dashboard.html': page('MineFleet | Sensibilidad', body)})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--scenario', type=Path, default=ROOT / 'data/scenario.json')
    parser.add_argument('--times', type=float, nargs='+', default=[1, 2, 3, 4, 5])
    parser.add_argument('--highlight', type=int, nargs=2, metavar=('A', 'B'), default=[4, 2],
                        help='Asignación fija adicional para el gráfico (se omite si no es válida)')
    parser.add_argument('--out', type=Path, default=ROOT / 'results_sensitivity')
    args = parser.parse_args()
    config = load_scenario(args.scenario)
    highlight = args.highlight
    try:
        validate_allocation(config, highlight)
    except (ValueError, KeyError):
        highlight = None
    try:
        reports = compare(config, args.times)
    except ValueError as exc:
        raise SystemExit(f'Escenario inválido: {exc}')
    export(config, reports, args.out, highlight)
    for entry in reports:
        best = entry['report']['best']
        print(f'Rampa {entry["ramp_min"]:g} min |', best['allocation'] if best else 'ninguna cumple las metas medias',
              '|', fmt(best['mean_tonnes']) if best else '')
    print('Panel:', args.out / 'dashboard.html')


if __name__ == '__main__':
    main()
