import copy
import json
import unittest
from pathlib import Path
from minefleet import simulate, optimize, validate

class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.c=json.loads(Path('data/scenario.json').read_text())
    def test_repeatable(self):
        self.assertEqual(simulate(self.c,[3,3],9),simulate(self.c,[3,3],9))
    def test_resource_exclusion(self):
        result=simulate(self.c,[3,3],keep_events=True)
        for resource in ('load0','load1','dump','ramp'):
            events=sorted((e for e in result['events'] if e['resource']==resource),key=lambda e:e['start'])
            for a,b in zip(events,events[1:]):
                self.assertLessEqual(a['end'],b['start']+0.0001)
        delivered=sum(e['stage']=='dump' and e['end']<=self.c['shift_min'] for e in result['events'])
        self.assertEqual(result['tonnes'],delivered*self.c['payload_t'])
    def test_single_truck_manual(self):
        c=copy.deepcopy(self.c);c.update(fleet=1,variability=0,shift_min=450)
        # First delivery at minute 21, then every 30 minutes: 15 deliveries.
        self.assertEqual(simulate(c,[1,0])['tonnes'],375)
    def test_shift_cutoff(self):
        c=copy.deepcopy(self.c);c.update(fleet=1,variability=0,shift_min=20)
        self.assertEqual(simulate(c,[1,0])['tonnes'],0)
        c['shift_min']=21
        self.assertEqual(simulate(c,[1,0])['tonnes'],25)
    def test_invalid_allocation(self):
        with self.assertRaises(ValueError):simulate(self.c,[4,4])
        self.c['routes'][0]['enabled']=False
        with self.assertRaises(ValueError):simulate(self.c,[3,3])
    def test_no_feasible_solution(self):
        self.c['minimum_tonnes']=[100000,100000]
        self.c['replications']=2
        self.assertIsNone(optimize(self.c)['best'])
    def test_exhaustive_optimum(self):
        r=optimize(self.c)
        self.assertEqual(len(r['candidates']),7)
        self.assertEqual(r['best']['mean_tonnes'],max(x['mean_tonnes'] for x in r['candidates'] if x['feasible']))
    def test_bad_data(self):
        self.c['routes'][0]['load_min']=-1
        with self.assertRaises(ValueError):validate(self.c)

if __name__=='__main__':unittest.main()
