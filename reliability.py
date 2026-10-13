"""Estimate joint target attainment under the MineFleet simulation model."""
import argparse
import copy
import csv
import json
import math
import statistics
from pathlib import Path
from minefleet import simulate, validate

ROOT = Path(__file__).resolve().parent


def wilson(successes, trials):
    """Two-sided 95% Wilson score interval for a binomial proportion."""
    if type(trials) is not int or trials < 1 or not 0 <= successes <= trials:
        raise ValueError('Invalid success count or sample size')
    z = 1.959963984540054
    p = successes / trials
    d = 1 + z*z/trials
    center = (p + z*z/(2*trials))/d
    half = z*math.sqrt(p*(1-p)/trials + z*z/(4*trials*trials))/d
    return [max(0, center-half), min(1, center+half)]


def summarize(runs, targets, allocation):
    counts = [sum(r['route_tonnes'][i] >= targets[i] for r in runs) for i in range(2)]
    joint = sum(all(t >= goal for t, goal in zip(r['route_tonnes'], targets)) for r in runs)
    means = [statistics.mean(r['route_tonnes'][i] for r in runs) for i in range(2)]
    n = len(runs)
    return {'allocation': list(allocation), 'replications': n,
            'mean_tonnes': statistics.mean(r['tonnes'] for r in runs),
            'route_mean_tonnes': means,
            'mean_targets_met': all(t >= goal for t, goal in zip(means, targets)),
            'front_success_counts': counts, 'front_success_rates': [k/n for k in counts],
            'joint_success_count': joint, 'joint_success_rate': joint/n,
            'joint_wilson_95': wilson(joint,n)}


def analyze(config, times, replications=1000):
    if type(replications) is not int or replications < 1:
        raise ValueError('Replications must be a positive integer')
    if not times or len(set(times)) != len(times):
        raise ValueError('Provide distinct ramp times')
    scenarios, records = [], []
    for time in sorted(times):
        c = copy.deepcopy(config)
        c['ramp_crossing_min'] = time
        validate(c)
        candidates = []
        for a in range(c['fleet']+1):
            allocation = [a,c['fleet']-a]
            if any(n and not r['enabled'] for n,r in zip(allocation,c['routes'])):
                continue
            runs = []
            for i in range(replications):
                seed = c['seed']+i
                run = simulate(c,allocation,seed)
                runs.append(run)
                records.append({'ramp_min': time, 'trucks_A': a, 'trucks_B': c['fleet']-a,
                                'replication': i+1, 'seed': seed, 'tonnes': run['tonnes'],
                                'front_A_t':run['route_tonnes'][0], 'front_B_t':run['route_tonnes'][1],
                                'both_targets_met': all(t>=goal for t,goal in zip(run['route_tonnes'],c['minimum_tonnes']))})
            candidates.append(summarize(runs,c['minimum_tonnes'],allocation))
        scenarios.append({'ramp_min':time, 'candidates':candidates})
    return {'data_type':'SIMULATED', 'scenario':copy.deepcopy(config),
            'analysis_replications':replications, 'scenarios':scenarios}, records


def export(report, records, out):
    out.mkdir(parents=True,exist_ok=True)
    (out/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    with (out/'replications.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    rows=[]
    for e in report['scenarios']:
        for c in e['candidates']:
            lo,hi=c['joint_wilson_95']
            rows.append({'ramp_min':e['ramp_min'], 'trucks_A':c['allocation'][0],
                         'trucks_B':c['allocation'][1], 'mean_tonnes':c['mean_tonnes'],
                         'mean_targets_met':c['mean_targets_met'],
                         'joint_success_count':c['joint_success_count'],
                         'replications':c['replications'], 'joint_success_rate':c['joint_success_rate'],
                         'wilson_95_low':lo,'wilson_95_high':hi})
    with (out/'comparison.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    table=''
    for row in rows:
        table+=f'''<tr><td>{row['ramp_min']:g}</td><td>{row['trucks_A']}/{row['trucks_B']}</td><td>{row['mean_tonnes']:.2f}</td><td>{'Sí' if row['mean_targets_met'] else 'No'}</td><td>{row['joint_success_count']}/{row['replications']}</td><td>{100*row['joint_success_rate']:.1f}%</td><td>{100*row['wilson_95_low']:.1f}–{100*row['wilson_95_high']:.1f}%</td></tr>'''
    config=report['scenario']
    (out/'dashboard.html').write_text(f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MineFleet | Cumplimiento por guardia</title><style>body{{font:16px system-ui;background:#101d2c;color:#eef4fb;max-width:1200px;margin:auto;padding:30px}}.card{{padding:22px;background:#1c3046;border-radius:16px;margin:20px 0}}.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #456}}a{{color:#56deb8}}</style><h1>MineFleet · Cumplimiento por guardia</h1><div class="card">Datos simulados · {report['analysis_replications']} réplicas por distribución · semilla inicial {config['seed']}<p>Metas A/B: {config['minimum_tonnes']} t. Cada réplica representa una guardia simulada.</p></div><div class="card scroll"><table><tr><th>Rampa (min)</th><th>A/B</th><th>Media t/guardia</th><th>Metas medias</th><th>Guardias con ambas metas</th><th>Frecuencia conjunta</th><th>Intervalo Wilson 95%</th></tr>{table}</table></div><p>La frecuencia conjunta cuenta guardias que alcanzan ambas metas a la vez; no se obtiene multiplicando los porcentajes de los frentes. El intervalo Wilson cuantifica incertidumbre de muestreo bajo este modelo. Un 100% observado no garantiza 100% futuro.</p><p>Se mantiene fijo el tiempo total de viaje y se modifica la ocupación de rampa. Las mismas semillas se reutilizan para comparar escenarios; sus resultados no son muestras independientes entre sí. Este análisis usa más réplicas que la versión anterior, por lo que las medias pueden cambiar.</p><p>El resultado es una estimación bajo supuestos simulados, no una probabilidad validada en una mina real. No selecciona una nueva distribución ni modifica el criterio de optimización anterior.</p><p><a href="comparison.csv">Tabla CSV</a> · <a href="replications.csv">Guardias simuladas CSV</a> · <a href="summary.json">Resultados JSON</a></p></html>''',encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scenario',type=Path,default=ROOT/'data/scenario.json')
    p.add_argument('--times',type=float,nargs='+',default=[2,3])
    p.add_argument('--replications',type=int,default=1000)
    p.add_argument('--out',type=Path,default=ROOT/'results_reliability')
    args=p.parse_args()
    config=json.loads(args.scenario.read_text(encoding='utf-8'))
    report,records=analyze(config,args.times,args.replications)
    export(report,records,args.out)
    for e in report['scenarios']:
        for c in e['candidates']:
            if c['allocation'] in (config['baseline'],[4,2]):
                print(f"Rampa {e['ramp_min']:g} min | {c['allocation']} | {c['mean_tonnes']:.2f} t | ambas metas: {c['joint_success_count']}/{c['replications']}")
    print('Panel:',args.out/'dashboard.html')

if __name__=='__main__':
    main()
