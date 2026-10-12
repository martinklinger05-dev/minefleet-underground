"""Sensitivity of shared ramp occupancy; Python standard library only."""
import argparse
import copy
import csv
import json
from pathlib import Path
from minefleet import optimize

ROOT = Path(__file__).resolve().parent


def compare(config, times):
    if not times or len(set(times)) != len(times):
        raise ValueError('Provide distinct ramp times')
    reports = []
    for time in sorted(times):
        scenario = copy.deepcopy(config)
        scenario['ramp_crossing_min'] = time
        reports.append({'ramp_min': time, 'report': optimize(scenario)})
    return reports


def export(config, reports, out):
    out.mkdir(parents=True, exist_ok=True)
    payload = {'data_type': 'SIMULATED', 'scenario': config,
               'interpretation': 'Total travel durations stay fixed; ramp occupancy changes.',
               'scenarios': reports}
    (out / 'summary.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
    rows = []
    for entry in reports:
        report = entry['report']
        for c in report['candidates']:
            rows.append({'ramp_min': entry['ramp_min'], 'trucks_A': c['allocation'][0],
                         'trucks_B': c['allocation'][1], 'mean_tonnes': c['mean_tonnes'],
                         'sd_tonnes': c['sd_tonnes'], 'front_A_t': c['route_mean_tonnes'][0],
                         'front_B_t': c['route_mean_tonnes'][1], 'feasible': c['feasible'],
                         'selected': c == report['best']})
    with (out / 'comparison.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    xmin, xmax = reports[0]['ramp_min'], reports[-1]['ramp_min']
    ymax = max(c['mean_tonnes'] for e in reports for c in e['report']['candidates']) * 1.1
    def x(t): return 80 + (t-xmin) / (xmax-xmin or 1) * 640
    def y(v): return 330 - v/ymax * 270
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400" role="img" aria-label="Producción frente al tiempo de ocupación de rampa"><rect width="800" height="400" fill="#fff"/>']
    for tick in range(5):
        value = ymax * tick/4
        svg.append(f'<path d="M80 {y(value)}H720" stroke="#ddd"/><text x="15" y="{y(value)+5}" font-size="13">{value:.0f}</text>')
    for e in reports:
        svg.append(f'<text x="{x(e["ramp_min"])}" y="355" text-anchor="middle">{e["ramp_min"]:g}</text>')
    for allocation, color, label in [(config['baseline'], '#2563eb', 'Base fija'), ([4,config['fleet']-4], '#d97706', 'Distribución fija 4/2')]:
        points = []
        for e in reports:
            c = next((c for c in e['report']['candidates'] if c['allocation']==allocation), None)
            if c:
                points.append(f'{x(e["ramp_min"])},{y(c["mean_tonnes"])}')
        svg.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="3"/>')
    for e in reports:
        best = e['report']['best']
        if best:
            svg.append(f'<circle cx="{x(e["ramp_min"])}" cy="{y(best["mean_tonnes"])}" r="6" fill="#059669"/>')
    svg.append('<text x="80" y="25">Producción media (t/guardia)</text><text x="230" y="390">Ocupación de rampa por cruce (min)</text></svg>')
    graphic = ''.join(svg)
    (out/'production.svg').write_text(graphic, encoding='utf-8')
    table = ''
    for e in reports:
        r = e['report']; b = r['best']
        table += f'<tr><td>{e["ramp_min"]:g}</td><td>{r["baseline"]["mean_tonnes"]:.2f}</td><td>{str(b["allocation"]) if b else "Sin asignación factible"}</td><td>{format(b["mean_tonnes"], ".2f") if b else "—"}</td></tr>'
    (out/'dashboard.html').write_text(f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MineFleet | Sensibilidad</title><style>body{{font:16px system-ui;max-width:1000px;margin:auto;padding:30px;background:#101d2c;color:#eef4fb}}svg{{width:100%;border-radius:12px}}table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #567}}</style><h1>MineFleet · Sensibilidad de rampa</h1><p>Datos simulados · {config['replications']} réplicas por distribución · semilla {config['seed']}</p>{graphic}<p>Azul: base fija {config['baseline']} · Naranja: fija 4/2 · Verde: selección factible por metas medias.</p><table><tr><th>Cruce (min)</th><th>Base (t/guardia)</th><th>Selección A/B</th><th>Selección (t/guardia)</th></tr>{table}</table><p>Se mantiene fijo el tiempo total de viaje. Cambia la ocupación del recurso compartido y, por tanto, las esperas. Las metas se evalúan sobre medias; no garantizan cumplimiento en cada guardia. Los puntos verdes pueden representar asignaciones diferentes.</p><p>La dispersión de las réplicas está en comparison.csv; este gráfico presenta medias, sin intervalos de incertidumbre. Prototipo pendiente de validación operacional.</p></html>''', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', type=Path, default=ROOT/'data/scenario.json')
    parser.add_argument('--times', type=float, nargs='+', default=[1,2,3,4,5])
    parser.add_argument('--out', type=Path, default=ROOT/'results_sensitivity')
    args = parser.parse_args()
    config = json.loads(args.scenario.read_text(encoding='utf-8'))
    if config['fleet'] != 6:
        parser.error('This presentation supports the six-truck portfolio scenario')
    reports = compare(config, args.times)
    export(config, reports, args.out)
    for e in reports:
        best = e['report']['best']
        print(e['ramp_min'], best['allocation'] if best else 'No feasible allocation',
              round(best['mean_tonnes'],2) if best else '')


if __name__ == '__main__':
    main()
