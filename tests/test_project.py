"""Test with: python -m unittest discover -s tests -v"""
import json
import math
import threading
import unittest
from heapq import heappop, heappush
from urllib.request import Request, urlopen

from backend.agent import EmergencyAgent
from backend.campus import Campus, PLACES, ALL_PLACES, EXIT_GATES, GATE_FOR_TYPE, road_id
from backend.server import Handler, HTTPServer


def dijkstra(campus, start, goal, mode):
    q, costs = [(0, start)], {start: 0}
    while q:
        cost, node = heappop(q)
        if cost > costs[node] + 1e-8:
            continue
        if node == goal:
            return cost
        for neighbor in campus.neighbors[node]:
            road = campus.roads[road_id(node, neighbor)]
            if road['blocked']:
                continue
            next_cost = cost + campus.weight(road, mode)
            if next_cost < costs.get(neighbor, math.inf):
                costs[neighbor] = next_cost
                heappush(q, (next_cost, neighbor))
    return None


class CampusTests(unittest.TestCase):
    def setUp(self):
        self.campus = Campus()

    def test_small_campus(self):
        self.assertEqual(len(PLACES), 9)
        self.assertIn('Store', PLACES)
        self.assertEqual(len(self.campus.roads), 18)
        self.assertEqual(len(EXIT_GATES), 3)
        self.assertEqual(set(GATE_FOR_TYPE), {'Medical','Accident','Fire'})
        self.assertTrue(all(name in ALL_PLACES for name in PLACES))

    def test_distance_is_shown_explicitly(self):
        road = self.campus.roads[road_id('Gate', 'Clinic')]
        self.assertEqual(road['distance'], 1.15)
        self.assertEqual(road['speed'], 30)
        self.assertAlmostEqual(self.campus.minutes(road), 2.3)
        self.assertAlmostEqual(self.campus.weight(road, 'balanced'), 3.45)

    def test_astar_optimal_for_all_modes_and_pairs(self):
        for mode in ('distance', 'time', 'balanced'):
            for origin in PLACES:
                for dest in PLACES:
                    self.assertAlmostEqual(self.campus.search(origin, dest, mode)['cost'],
                                           dijkstra(self.campus, origin, dest, mode), places=2)

    def test_trace_f_equals_g_plus_h(self):
        route = self.campus.search('Gate', 'Lab', 'balanced')
        for step in route['steps']:
            for node in [step['selected'], *step['open']]:
                self.assertAlmostEqual(node['f'], node['g'] + node['h'], delta=.002)

    def test_routes_start_and_end_correctly(self):
        route = self.campus.search('Gate', 'Lab')
        self.assertEqual(route['path'][0], 'Gate')
        self.assertEqual(route['path'][-1], 'Lab')

    def test_origin_is_destination(self):
        self.assertEqual(self.campus.search('Clinic', 'Clinic')['cost'], 0)

    def test_blocked_road_is_avoided(self):
        key = road_id('Gate', 'Clinic')
        self.campus.change_road(key, 'block')
        route = self.campus.search('Gate', 'Hostel')
        self.assertNotIn(key, [road_id(a,b) for a,b in zip(route['path'], route['path'][1:])])

    def test_disconnected_graph_reports_no_path(self):
        for neighbor in list(self.campus.neighbors['Gate']):
            self.campus.change_road(road_id('Gate', neighbor), 'block')
        self.assertEqual(self.campus.search('Gate', 'Hostel')['path'], [])

    def test_traffic_and_road_use_change_time_not_distance(self):
        road = self.campus.roads[road_id('Gate', 'Clinic')]
        initial = self.campus.minutes(road)
        self.campus.change_road(road_id('Gate', 'Clinic'), 'traffic')
        self.assertAlmostEqual(self.campus.minutes(road), initial*2)
        road['use'] = 1
        self.assertAlmostEqual(self.campus.minutes(road), initial*2*1.4)
        self.assertEqual(road['distance'], 1.15)

    def test_astar_optimal_under_mixed_congestion(self):
        for road in self.campus.roads.values():
            if road['a'] in ('Clinic','Library'):
                road['traffic'] = 2
                road['use'] = 1
        for mode in ('time', 'balanced'):
            for a in PLACES:
                for b in PLACES:
                    self.assertAlmostEqual(self.campus.search(a, b, mode)['cost'],
                                           dijkstra(self.campus, a, b, mode), places=2)

    def test_astar_optimal_including_all_three_gates(self):
        for mode in ('distance', 'time', 'balanced'):
            for start in ALL_PLACES:
                for goal in ALL_PLACES:
                    route = self.campus.search(start, goal, mode)
                    self.assertAlmostEqual(route['cost'], dijkstra(self.campus, start, goal, mode), places=2)

    def test_full_node_heuristics_and_direction_explanations(self):
        for mode in ('distance', 'time', 'balanced'):
            route = self.campus.search('Hostel', 'Fire Exit', mode)
            self.assertEqual(len(route['heuristics']), len(ALL_PLACES))
            self.assertEqual(route['heuristics'][-1]['node'], 'Fire Exit')
            self.assertEqual(route['heuristics'][-1]['h'], 0)
            for step in route['steps']:
                self.assertIn('smallest', step['reason'] if not step['found'] else 'smallest')
                self.assertEqual(step['frontier_before'][0]['node'], step['current'])
                for candidate in step['choices']:
                    if not candidate['blocked']:
                        self.assertAlmostEqual(candidate['f'], candidate['tentative_g'] + candidate['h'], delta=.002)
                        self.assertAlmostEqual(candidate['tentative_g'], step['selected']['g'] + candidate['road_cost'], delta=.002)
                        self.assertTrue(candidate['direction'])
            self.assertEqual(route['legs'][-1]['to_node'], 'Fire Exit')
            self.assertAlmostEqual(sum(x['road_cost'] for x in route['legs']), route['cost'], delta=.002 * len(route['legs']))

    def test_gate_road_block_reports_unreachable_exit(self):
        key=road_id('Lab','Fire Exit')
        second=road_id('Store','Fire Exit')
        self.campus.change_road(key,'block')
        self.campus.change_road(second,'block')
        route=self.campus.search('Hostel','Fire Exit')
        self.assertEqual(route['path'],[])
        self.assertIsNone(route['cost'])
        self.campus.change_road(key,'block')
        self.assertEqual(self.campus.search('Hostel','Fire Exit')['path'][-1], 'Fire Exit')

    def test_every_node_displays_consistent_g_and_h_reference(self):
        for mode in ('distance', 'time', 'balanced'):
            for start in ALL_PLACES:
                for goal in ALL_PLACES:
                    result = self.campus.search(start, goal, mode)
                    references = {r['node']: r for r in result['heuristics']}
                    self.assertEqual(set(references), set(ALL_PLACES))
                    for point, values in references.items():
                        self.assertAlmostEqual(values['g_reference'], dijkstra(self.campus,start,point,mode),delta=.002)
                        self.assertAlmostEqual(values['f_reference'],values['g_reference']+values['h'],delta=.002)
                    for step in result['steps']:
                        for seen in step['known']:
                            self.assertEqual(references[seen['node']]['h'], round(self.campus.heuristic(seen['node'],goal,mode),3))

    def test_store_does_not_move_old_locations_and_has_connected_routes(self):
        self.assertEqual(PLACES['Hostel'], (780,105))
        self.assertEqual(PLACES['Gate'], (90,105))
        self.assertEqual(PLACES['Store'], (780,585))
        self.assertEqual(len(EXIT_GATES),3)
        for target in EXIT_GATES:
            self.assertTrue(self.campus.search('Store',target)['path'])

    def test_reset_preserves_availability_count(self):
        road = self.campus.roads[road_id('Gate','Clinic')]
        self.campus.change_road(road_id('Gate','Clinic'),'block')
        self.campus.change_road(road_id('Gate','Clinic'),'traffic')
        road['use'] = 2
        self.campus.reset()
        self.assertFalse(road['blocked'])
        self.assertEqual(road['traffic'], 1)
        self.assertEqual(road['use'], 2)  # Reset doesn't erase active reservations.


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.agent = EmergencyAgent()

    def test_register_assigns_and_finds_three_routes_immediately(self):
        item = self.agent.register('Hostel', 'Medical')
        self.assertEqual(item['status'], 'En route')
        self.assertEqual(item['vehicle'], 'AMB-1')
        self.assertEqual(item['route']['path'][-1], 'Hostel')
        self.assertTrue(item['shortest']['path'])
        self.assertTrue(item['fastest']['path'])

    def test_each_incident_type_gets_its_own_gate_and_second_route(self):
        for event, gate in GATE_FOR_TYPE.items():
            agent = EmergencyAgent()
            item = agent.register('Hostel', event)
            self.assertEqual(item['exit_gate'], gate)
            self.assertEqual(item['evacuation']['path'][0], 'Hostel')
            self.assertEqual(item['evacuation']['path'][-1], gate)
            self.assertTrue(item['evacuation']['legs'])
            self.assertEqual(item['exit_shortest']['path'][-1],gate)
            self.assertEqual(item['exit_fastest']['path'][-1],gate)
            self.assertEqual(agent.explain(item['id'])['path'],item['evacuation']['path'])

    def test_exit_route_recomputed_after_road_closure(self):
        item = self.agent.register('Hostel','Fire')
        self.assertTrue(item['evacuation']['path'])
        self.agent.campus.change_road(road_id('Lab','Fire Exit'),'block')
        self.agent.campus.change_road(road_id('Store','Fire Exit'),'block')
        self.agent.rebalance()
        self.assertEqual(item['evacuation']['path'],[])
        self.assertTrue(item['route']['path'])
        self.agent.campus.change_road(road_id('Lab','Fire Exit'),'block')
        self.agent.rebalance()
        self.assertTrue(item['evacuation']['path'])

    def test_equipment_required(self):
        item = self.agent.register('Lab','Medical')
        self.assertIn('first-aid',self.agent.get_vehicle(item['vehicle'])['equipment'])

    def test_fire_uses_response_team(self):
        item=self.agent.register('Sports','Fire')
        self.assertEqual(item['vehicle'],'TEAM-1')

    def test_auto_priority_on_release(self):
        self.agent.register('Hostel','Medical') # AMB-1 busy
        self.agent.register('Lab','Accident')  # AMB-2 busy
        waiting_low=self.agent.register('Sports','Accident')
        waiting_high=self.agent.register('Gate','Medical','Critical')
        self.assertEqual(waiting_low['status'],'Waiting')
        self.assertEqual(waiting_high['status'],'Waiting')
        self.agent.finish(1)
        self.assertEqual(waiting_high['vehicle'],'AMB-1')
        self.assertEqual(waiting_low['status'],'Waiting')

    def test_distinct_colours_for_requests(self):
        a=self.agent.register('Hostel','Medical')
        b=self.agent.register('Lab','Accident')
        self.assertNotEqual(a['color'],b['color'])

    def test_occupied_road_is_released_on_completion(self):
        request=self.agent.register('Hostel','Medical')
        roads=[road_id(a,b) for a,b in zip(request['route']['path'], request['route']['path'][1:])]
        self.assertTrue(roads)
        self.assertTrue(all(self.agent.campus.roads[r]['use']==1 for r in roads))
        self.agent.finish(request['id'])
        self.assertTrue(all(self.agent.campus.roads[r]['use']==0 for r in roads))
        self.assertEqual(self.agent.get_vehicle('AMB-1')['status'],'Available')
        self.assertEqual(self.agent.get_vehicle('AMB-1')['location'],'Hostel')

    def test_road_block_triggers_dynamic_replan(self):
        request=self.agent.register('Hostel','Medical')
        old=request['route']['path'][:]
        self.agent.campus.change_road(road_id(old[0],old[1]),'block')
        changed=self.agent.rebalance()
        self.assertGreaterEqual(changed,1)
        self.assertNotEqual(request['route']['path'],old)

    def test_explain_trace_matches_incident_combined_cost(self):
        self.agent.register('Hostel','Medical')
        incident=self.agent.register('Lab','Accident')
        result=self.agent.explain(incident['id'], 'dispatch')
        self.assertEqual(result['path'],incident['route']['path'])
        self.assertAlmostEqual(result['cost'],incident['route']['cost'],places=2)

    def test_waiting_shows_preview_route(self):
        self.agent.register('Hostel','Accident')
        waiting=self.agent.register('Lab','Accident')
        self.assertEqual(waiting['status'],'Waiting')
        self.assertIsNone(waiting['vehicle'])
        self.assertEqual(waiting['preview_vehicle'],'AMB-2')
        self.assertTrue(waiting['shortest']['path'])
        self.assertTrue(waiting['route']['path'])

    def test_waiting_cannot_be_completed(self):
        self.agent.register('Hostel','Accident')
        waiting=self.agent.register('Lab','Accident')
        with self.assertRaises(ValueError):
            self.agent.finish(waiting['id'])

    def test_cardiac_removed_but_medical_works(self):
        with self.assertRaises(ValueError):
            self.agent.register('Hostel','Cardiac')
        self.assertEqual(self.agent.register('Hostel','Medical')['exit_gate'],'Medical Exit')

    def test_reject_invalid_inputs(self):
        for location,event,level in [('Unknown','Medical','Auto'),('Hostel','Unknown','Auto'),('Hostel','Medical','Wrong')]:
            with self.assertRaises(ValueError):
                self.agent.register(location,event,level)

    def test_no_route_does_not_teleport(self):
        incident=self.agent.register('Hostel','Medical')
        vehicle=self.agent.get_vehicle(incident['vehicle'])
        old=vehicle['location']
        for neighbor in self.agent.campus.neighbors[old]:
            self.agent.campus.change_road(road_id(old,neighbor),'block')
        self.agent.rebalance()
        self.assertEqual(incident['status'],'No route')
        self.agent.move()
        self.assertEqual(vehicle['location'],old)

    def test_move_can_reach_scene(self):
        incident=self.agent.register('Hostel','Medical')
        for _ in range(8):
            self.agent.move()
        self.assertEqual(incident['status'],'On scene')


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=HTTPServer(('127.0.0.1',0),Handler)
        cls.server.agent=EmergencyAgent()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self,endpoint,data):
        req=Request(self.url+'/api/'+endpoint,data=json.dumps(data).encode(),
                    headers={'Content-Type':'application/json'},method='POST')
        with urlopen(req) as response:
            return json.load(response)

    def test_state_has_18_labeled_roads_and_three_exits(self):
        with urlopen(self.url+'/api/state') as response:
            state=json.load(response)
        self.assertEqual(len(state['roads']),18)
        self.assertEqual(len(state['campus_locations']),9)
        self.assertEqual(len(state['exit_gates']),3)
        self.assertEqual(state['types'], ['Medical','Accident','Fire'])
        self.assertNotIn('Cardiac Exit', state['places'])
        self.assertTrue(all('distance' in r and 'speed' in r for r in state['roads']))

    def test_register_search_finish(self):
        result=self.request('register',{'location':'Hostel','event':'Medical'})
        incident_id=result['incident_id']
        incident=result['state']['incidents'][incident_id-1]
        self.assertIsNotNone(incident['route'])
        trace=self.request('incident-search',{'id':incident_id})['search']
        self.assertTrue(trace['steps'])
        self.assertEqual(trace['goal'], 'Medical Exit')
        done=self.request('finish',{'id':incident_id})
        self.assertEqual(done['state']['incidents'][incident_id-1]['status'],'Completed')

    def test_search_api_supplies_all_node_heuristics_and_directions(self):
        result=self.request('search',{'start':'Hostel','goal':'Fire Exit','mode':'balanced'})
        route=result['search']
        self.assertEqual(route['goal'],'Fire Exit')
        self.assertEqual(len(route['heuristics']),12)
        self.assertTrue(route['legs'])
        self.assertIn('reason',route['steps'][0])
        self.assertIn('choices',route['steps'][0])
        self.assertTrue(all('g_reference' in r and 'h' in r and 'f_reference' in r for r in route['heuristics']))

    def test_change_road(self):
        key=road_id('Clinic','Library')
        result=self.request('road',{'key':key,'change':'traffic'})
        target=next(r for r in result['state']['roads'] if road_id(r['a'],r['b'])==key)
        self.assertEqual(target['traffic'],2)

    def test_frontend_has_route_labels_and_completion(self):
        with urlopen(self.url+'/') as response:
            html=response.read().decode()
        self.assertIn('Campus map & road costs',html)
        self.assertIn('Complete',html)
        self.assertIn('Watch A* search',html)
        self.assertIn('exit-target',html)
        self.assertIn('All-node G / H / F values',html)


if __name__=='__main__':
    unittest.main()
