"""Original campus layout, a connected Store and three dedicated exits with auditable A*."""
from math import hypot, inf
from heapq import heappush, heappop

# Keep the original eight locations at their original map coordinates.
PLACES = {
    'Gate': (90, 105), 'Clinic': (320, 105),
    'Library': (550, 105), 'Hostel': (780, 105),
    'Canteen': (90, 345), 'Academic': (320, 345),
    'Sports': (550, 345), 'Lab': (780, 345),
    'Store': (780, 585),  # Added as requested; the previous eight positions are unchanged.
}

# Additional, fictional evacuation destinations. These are NOT replacements for Gate.
EXIT_GATES = {
    'Medical Exit': (320, 585),
    'Accident Exit': (90, 585),
    'Fire Exit': (1010, 345),
}
GATE_FOR_TYPE = {
    'Medical': 'Medical Exit', 'Accident': 'Accident Exit',
    'Fire': 'Fire Exit',
}
ALL_PLACES = {**PLACES, **EXIT_GATES}

# a, b, demo km, assumed km/h. Original 12 roads stay untouched.
ROADS = [
    ('Gate', 'Clinic', 1.15, 30), ('Clinic', 'Library', 1.15, 30),
    ('Library', 'Hostel', 1.15, 30), ('Canteen', 'Academic', 1.15, 30),
    ('Academic', 'Sports', 1.15, 30), ('Sports', 'Lab', 1.15, 30),
    ('Gate', 'Canteen', 1.20, 25), ('Clinic', 'Academic', 1.20, 25),
    ('Library', 'Sports', 1.20, 25), ('Hostel', 'Lab', 1.20, 25),
    ('Clinic', 'Sports', 1.662, 24), ('Academic', 'Library', 1.662, 24),
    ('Academic', 'Medical Exit', 1.200, 25),
    ('Canteen', 'Accident Exit', 1.200, 25),
    ('Lab', 'Fire Exit', 1.150, 25),
    ('Lab', 'Store', 1.200, 25),
    ('Sports', 'Store', 1.662, 24),
    ('Store', 'Fire Exit', 1.662, 24),
]
MAX_SPEED = max(r[3] for r in ROADS)


def road_id(a, b):
    return '|'.join(sorted((a, b)))


def direction(a, b):
    """Human-friendly cardinal/diagonal direction in the drawn map coordinates."""
    x1, y1 = ALL_PLACES[a]
    x2, y2 = ALL_PLACES[b]
    horizontal = 'east' if x2 > x1 else ('west' if x2 < x1 else '')
    vertical = 'south' if y2 > y1 else ('north' if y2 < y1 else '')
    if vertical and horizontal:
        return f'{vertical}-{horizontal}'
    return horizontal or vertical or 'here'


class Campus:
    def __init__(self):
        self.roads = {}
        self.neighbors = {name: [] for name in ALL_PLACES}
        for a, b, distance, speed in ROADS:
            self.roads[road_id(a, b)] = dict(
                a=a, b=b, distance=distance, speed=speed,
                traffic=1, blocked=False, use=0,
            )
            self.neighbors[a].append(b)
            self.neighbors[b].append(a)

    @staticmethod
    def straight(a, b):
        x1, y1 = ALL_PLACES[a]
        x2, y2 = ALL_PLACES[b]
        return hypot(x2 - x1, y2 - y1) / 200

    def minutes(self, road):
        """40% extra time for each higher-priority response using the road."""
        return road['distance'] * 60 / road['speed'] * road['traffic'] * (1 + 0.4 * road['use'])

    def weight(self, road, mode):
        distance = road['distance']
        if mode == 'distance':
            return distance
        if mode == 'time':
            return self.minutes(road)
        return distance + self.minutes(road)  # score points = km + min

    def heuristic(self, node, goal, mode):
        """Admissible lower bound for every node, including new exits.

        The .999 safety factor compensates for three-decimal road distances.
        Traffic >= 1 and the fastest demo road is MAX_SPEED km/h.
        """
        km = self.straight(node, goal) * .999
        if mode == 'distance':
            return km
        if mode == 'time':
            return km * 60 / MAX_SPEED
        return km * (1 + 60 / MAX_SPEED)

    def reference_costs(self, start, mode):
        """Exact cost-to-reach EVERY node from start, for the sidebar reference.

        This is a separate Dijkstra reference computation, NOT the live A* frontier:
        live A* can still display 'unseen' and provisional tentative g values.
        Both algorithms use the identical edge weights and road restrictions.
        """
        best = {start: 0.0}
        queue = [(0.0, start)]
        while queue:
            cost, node = heappop(queue)
            if cost > best[node] + 1e-9:
                continue
            for nxt in self.neighbors[node]:
                road = self.roads[road_id(node, nxt)]
                if road['blocked']:
                    continue
                proposed = cost + self.weight(road, mode)
                if proposed < best.get(nxt, inf) - 1e-9:
                    best[nxt] = proposed
                    heappush(queue, (proposed, nxt))
        return best

    def search(self, start, goal, mode='balanced'):
        """Optimal A* with explicit heuristic, alternatives, and turn-by-turn legs.

        g is the accumulated ACTUAL road cost; h is a lower-bound estimate;
        f = g+h ranks the next node. h is not added to g on each edge.
        """
        if start not in ALL_PLACES or goal not in ALL_PLACES or mode not in ('distance', 'time', 'balanced'):
            raise ValueError('Choose valid locations and a search mode')

        h = {node: self.heuristic(node, goal, mode) for node in ALL_PLACES}
        reference = self.reference_costs(start, mode)
        heuristics = [dict(node=node, h=round(h[node], 3),
                           g_reference=round(reference[node], 3) if node in reference else None,
                           f_reference=round(reference[node] + h[node], 3) if node in reference else None,
                           straight_km=round(self.straight(node, goal), 3))
                      for node in ALL_PLACES]
        unit = {'distance': 'km', 'time': 'min', 'balanced': 'points'}[mode]

        def entry(n):
            return dict(node=n, g=round(g[n], 3), h=round(h[n], 3),
                        f=round(g[n] + h[n], 3))

        g, parent = {start: 0.0}, {}
        opened, closed, steps = {start}, set(), []
        while opened:
            ranked = sorted(opened, key=lambda n: (g[n] + h[n], h[n], n))
            current = ranked[0]
            before = [entry(n) for n in ranked]
            opened.remove(current)
            closed.add(current)
            updates, choices = [], []
            if current != goal:
                for other in sorted(self.neighbors[current]):
                    road = self.roads[road_id(current, other)]
                    if road['blocked']:
                        updates.append({'node': other, 'message': 'Road blocked'})
                        choices.append(dict(node=other, direction=direction(current, other),
                                            blocked=True, decision='Blocked road', road_cost=None,
                                            tentative_g=None, h=round(h[other], 3), f=None))
                        continue
                    edge_cost = self.weight(road, mode)
                    tentative = g[current] + edge_cost
                    improved = tentative < g.get(other, float('inf')) - 1e-9
                    if improved:
                        g[other], parent[other] = tentative, current
                        opened.add(other)
                        closed.discard(other)
                        updates.append({'node': other, 'message': f'g = {tentative:.2f}'})
                    else:
                        updates.append({'node': other, 'message': 'Existing route is cheaper'})
                    choices.append(dict(
                        node=other, direction=direction(current, other), blocked=False,
                        road_cost=round(edge_cost, 3), tentative_g=round(tentative, 3),
                        h=round(h[other], 3), f=round(tentative + h[other], 3),
                        decision='Improved; add/update OPEN' if improved else 'Keep better existing g',
                    ))
            winner = 'Goal reached; minimum estimated cost is finalized.' if current == goal else (
                f'{current} was chosen from OPEN because f={g[current] + h[current]:.3f} {unit} '
                'was smallest (ties: lower h, then name).'
            )
            steps.append(dict(
                current=current, selected=entry(current), frontier_before=before,
                reason=winner, choices=choices,
                open=[entry(n) for n in sorted(opened, key=lambda n: (g[n]+h[n], h[n], n))],
                closed=sorted(closed), updates=updates, found=current == goal,
                known=[dict(node=n, g=round(g[n], 3), f=round(g[n] + h[n], 3))
                       for n in ALL_PLACES if n in g],
            ))
            if current == goal:
                path = [goal]
                while path[-1] != start:
                    path.append(parent[path[-1]])
                path.reverse()
                accumulated, legs = 0.0, []
                for a, b in zip(path, path[1:]):
                    road = self.roads[road_id(a, b)]
                    edge = self.weight(road, mode)
                    accumulated += edge
                    legs.append(dict(
                        from_node=a, to_node=b, direction=direction(a, b),
                        distance=road['distance'], minutes=round(self.minutes(road), 3),
                        road_cost=round(edge, 3), g=round(accumulated, 3),
                        h=round(h[b], 3), f=round(accumulated + h[b], 3),
                    ))
                return dict(
                    start=start, goal=goal, path=path,
                    distance=round(sum(l['distance'] for l in legs), 3),
                    minutes=round(sum(l['minutes'] for l in legs), 3),
                    cost=round(g[goal], 3), mode=mode, unit=unit,
                    heuristics=heuristics, legs=legs, steps=steps,
                )
        return dict(
            start=start, goal=goal, path=[], distance=None, minutes=None, cost=None,
            mode=mode, unit=unit, heuristics=heuristics, legs=[], steps=steps,
        )

    def change_road(self, key, action):
        if key not in self.roads:
            raise ValueError('Unknown road')
        road = self.roads[key]
        if action == 'block':
            road['blocked'] = not road['blocked']
        elif action == 'traffic':
            road['traffic'] = 2 if road['traffic'] == 1 else 1
        else:
            raise ValueError('Invalid road action')
        return road

    def reset(self):
        for road in self.roads.values():
            road['blocked'], road['traffic'] = False, 1
