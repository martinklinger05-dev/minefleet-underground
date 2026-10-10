"""Discrete-event underground haulage demonstration. Python standard library only."""
import argparse
import csv
import heapq
import json
import math
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def validate(c):
    for key in ('fleet', 'replications', 'seed'):
        if type(c[key]) is not int or (key != 'seed' and c[key] < 1):
            raise ValueError(f'{key}: expected integer')
    for key in ('payload_t', 'shift_min', 'cost_per_truck_hour', 'ramp_crossing_min'):
        if not math.isfinite(c[key]) or c[key] <= 0:
            raise ValueError(f'{key}: expected positive finite number')
    if not 0 <= c['variability'] < 1:
        raise ValueError('variability must be in [0,1)')
    if len(c['routes']) != 2 or len(c['minimum_tonnes']) != 2:
        raise ValueError('Version 1 supports exactly two routes')
    if any(not math.isfinite(x) or x < 0 for x in c['minimum_tonnes']):
        raise ValueError('Invalid production targets')
    for r in c['routes']:
        for k in ('load_min', 'loaded_min', 'dump_min', 'empty_min'):
            if not math.isfinite(r[k]) or r[k] <= 0:
                raise ValueError('Invalid route duration')
        if min(r['loaded_min'], r['empty_min']) < c['ramp_crossing_min']:
            raise ValueError('Ramp duration cannot exceed travel duration')
    validate_allocation(c, c['baseline'])

def validate_allocation(c, allocation):
    if len(allocation) != 2 or any(type(x) is not int or x < 0 for x in allocation) or sum(allocation) != c['fleet']:
        raise ValueError('Allocation must use every truck exactly once')
    if any(n and not r['enabled'] for n, r in zip(allocation, c['routes'])):
        raise ValueError('Cannot assign trucks to a closed route')

def simulate(c, allocation, seed=2026, keep_events=False):
    validate_allocation(c, allocation)
    # Each truck has a separate random stream; seed and truck IDs remain stable.
    rng = [random.Random(seed * 100003 + i) for i in range(c['fleet'])]
    available = {'load0':0.0, 'load1':0.0, 'dump':0.0, 'ramp':0.0}
    queue, serial = [], 0
    tonnes, trips, waits, events = [0.0,0.0], [0,0], 0.0, []
    truck_routes = [i for i,n in enumerate(allocation) for _ in range(n)]
    def push(t, truck, stage):
        nonlocal serial
        serial += 1
        heapq.heappush(queue, (t, serial, truck, stage))
    for truck in range(c['fleet']):
        push(0.0, truck, 'load')
    while queue:
        t, _, truck, stage = heapq.heappop(queue)
        if t > c['shift_min']:
            break
        route = truck_routes[truck]
        r = c['routes'][route]
        resource = None
        if stage == 'load':
            duration, resource, nxt = r['load_min'], f'load{route}', 'ramp_loaded'
        elif stage == 'ramp_loaded':
            duration, resource, nxt = c['ramp_crossing_min'], 'ramp', 'travel_loaded'
        elif stage == 'travel_loaded':
            duration, nxt = r['loaded_min']-c['ramp_crossing_min'], 'dump'
        elif stage == 'dump':
            duration, resource, nxt = r['dump_min'], 'dump', 'delivered'
        elif stage == 'delivered':
            tonnes[route] += c['payload_t']
            trips[route] += 1
            push(t, truck, 'ramp_empty')
            continue
        elif stage == 'ramp_empty':
            duration, resource, nxt = c['ramp_crossing_min'], 'ramp', 'travel_empty'
        else:
            duration, nxt = r['empty_min']-c['ramp_crossing_min'], 'load'
        # Fixed crossing duration models occupancy; other durations are triangular.
        if stage not in ('ramp_loaded', 'ramp_empty'):
            v = c['variability']
            duration = rng[truck].triangular(duration*(1-v), duration*(1+v), duration)
        start = max(t, available[resource]) if resource else t
        end = start + duration
        waits += max(0.0, min(start,c['shift_min'])-t)
        if resource:
            available[resource] = end
        if keep_events:
            events.append({'truck':truck+1,'route':r['name'],'stage':stage,'arrival':round(t,4),'start':round(start,4),'end':round(end,4),'resource':resource or ''})
        push(end, truck, nxt)
    total = sum(tonnes)
    cost = c['fleet'] * c['shift_min']/60 * c['cost_per_truck_hour']
    return {'tonnes':total,'route_tonnes':tonnes,'trips':sum(trips),'wait_min':waits,'cost':cost,'cost_per_t':cost/total if total else None,'events':events}

def evaluate(c, allocation):
    runs = [simulate(c, allocation, c['seed']+i) for i in range(c['replications'])]
    values = [r['tonnes'] for r in runs]
    means = [statistics.mean(r['route_tonnes'][i] for r in runs) for i in range(2)]
    sd = statistics.stdev(values) if len(values)>1 else 0
    return {'allocation':list(allocation),'mean_tonnes':statistics.mean(values),'sd_tonnes':sd,'min_tonnes':min(values),'max_tonnes':max(values),'route_mean_tonnes':means,'mean_wait_min':statistics.mean(r['wait_min'] for r in runs),'cost_per_t':runs[0]['cost']/statistics.mean(values) if sum(values) else None,'feasible':all(m>=target for m,target in zip(means,c['minimum_tonnes']))}

def optimize(c):
    validate(c)
    candidates = [evaluate(c,[a,c['fleet']-a]) for a in range(c['fleet']+1) if all(n==0 or r['enabled'] for n,r in zip([a,c['fleet']-a],c['routes']))]
    feasible = [x for x in candidates if x['feasible']]
    best = max(feasible,key=lambda x:x['mean_tonnes']) if feasible else None
    baseline = next(x for x in candidates if x['allocation']==c['baseline'])
    return {'baseline':baseline,'best':best,'candidates':candidates,'replications':c['replications'],'seed':c['seed'],'data_type':'SIMULATED', 'improvement_pct':100*(best['mean_tonnes']/baseline['mean_tonnes']-1) if best and baseline['mean_tonnes'] else None}

def write_dashboard(report, path):
    rows = ''.join(f"<tr><td>{x['allocation'][0]} / {x['allocation'][1]}</td><td>{x['mean_tonnes']:.1f}</td><td>{x['sd_tonnes']:.1f}</td><td>{x['mean_wait_min']:.1f}</td><td>{x['cost_per_t']:.2f}</td><td>{'Sí' if x['feasible'] else 'No'}</td></tr>" for x in report['candidates'])
    best = report['best']
    headline = f"Asignación seleccionada: {best['allocation'][0]} en A y {best['allocation'][1]} en B · {report['improvement_pct']:.2f}% frente a la base" if best else 'Ninguna asignación cumple las metas medias'
    path.write_text(f"""<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MineFleet | Resultados</title><style>body{{font:16px system-ui;background:#101d2c;color:#eef4fb;max-width:1100px;margin:40px auto;padding:24px}}h1{{font-size:44px}}.card{{background:#1c3046;padding:24px;border-radius:16px;margin:20px 0}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:12px;border-bottom:1px solid #456}}.tag{{color:#56deb8}}a{{color:#56deb8}}</style><span class="tag">MINERÍA SUBTERRÁNEA · DATOS SIMULADOS</span><h1>MineFleet</h1><p>Optimización de asignación estática con simulación de eventos discretos.</p><div class="card"><h2>{headline}</h2><p>{report['replications']} réplicas por asignación · semilla {report['seed']} · flota de 6 equipos en el escenario incluido.</p></div><div class="card"><table><thead><tr><th>Volquetes A / B</th><th>t/guardia media</th><th>Desv. estándar t</th><th>Espera total min</th><th>S/ por t</th><th>Cumple metas medias</th></tr></thead><tbody>{rows}</tbody></table></div><p>Una rampa compartida de capacidad 1, un cargador por frente y una descarga común. Selección exhaustiva dentro de las asignaciones probadas. El cumplimiento medio no garantiza cumplimiento en cada guardia.</p><p>Costo supuesto por hora de equipo; no representa un presupuesto real. Resultados exploratorios, pendientes de validación operacional.</p></html>""",encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario',type=Path,default=ROOT/'data/scenario.json')
    parser.add_argument('--out',type=Path,default=ROOT/'results')
    args = parser.parse_args()
    c = json.loads(args.scenario.read_text())
    report = optimize(c)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    write_dashboard(report,args.out/'dashboard.html')
    allocation = report['best']['allocation'] if report['best'] else c['baseline']
    events = simulate(c,allocation,c['seed'],True)['events']
    with (args.out/'events.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(events[0]))
        w.writeheader();w.writerows(events)
    print(json.dumps({'best':report['best'],'improvement_pct':report['improvement_pct']},indent=2))

if __name__ == '__main__':
    main()
