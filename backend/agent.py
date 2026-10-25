"""Automatic registration, equipment-aware dispatch and priority-based replanning."""
from .campus import Campus, PLACES, GATE_FOR_TYPE, road_id

TYPES = {
    'Medical': ('Ambulance', 'first-aid', 'Medium'),
    'Accident': ('Ambulance', 'trauma', 'High'),
    'Fire': ('Response', 'fire-kit', 'High'),
}
LEVELS = {'Low': 1, 'Medium': 2, 'High': 3, 'Critical': 4}
COLORS = ['#3869ed', '#e36b38', '#a45bd5', '#0e9a8e', '#d24985', '#be9730', '#5677a2', '#d14b53']


def compact(route):
    return {k: route[k] for k in ('path', 'distance', 'minutes', 'cost', 'legs', 'mode', 'unit')}


class EmergencyAgent:
    def __init__(self):
        self.campus = Campus()
        self.vehicles = [
            dict(id='AMB-1', kind='Ambulance', location='Clinic', equipment=['first-aid', 'oxygen'],
                 status='Available', incident=None, path=[]),
            dict(id='AMB-2', kind='Ambulance', location='Gate', equipment=['first-aid', 'oxygen', 'trauma', 'aed'],
                 status='Available', incident=None, path=[]),
            dict(id='TEAM-1', kind='Response', location='Academic', equipment=['fire-kit'],
                 status='Available', incident=None, path=[]),
        ]
        self.incidents = []
        self.logs = []

    def log(self, message):
        self.logs.insert(0, message)
        self.logs = self.logs[:8]

    def register(self, location, event, level='Auto'):
        if location not in PLACES or event not in TYPES or level not in ('Auto', *LEVELS):
            raise ValueError('Choose a valid location, type and priority')
        level = TYPES[event][2] if level == 'Auto' else level
        incident = dict(id=len(self.incidents)+1, location=location, event=event,
                        level=level, color=COLORS[len(self.incidents) % len(COLORS)],
                        status='Waiting', vehicle=None, preview_vehicle=None,
                        exit_gate=GATE_FOR_TYPE[event], evacuation=None,
                        exit_shortest=None, exit_fastest=None,
                        route=None, shortest=None, fastest=None)
        self.incidents.append(incident)
        self.log(f'#{incident["id"]} {level} {event} at {location} registered.')
        self.rebalance()
        return incident

    def get_vehicle(self, vehicle_id):
        return next(v for v in self.vehicles if v['id'] == vehicle_id)

    def candidates(self, incident, available_only=True):
        kind, needed, _ = TYPES[incident['event']]
        options = []
        for vehicle in self.vehicles:
            if vehicle['kind'] != kind or needed not in vehicle['equipment']:
                continue
            if available_only and vehicle['status'] != 'Available':
                continue
            route = self.campus.search(vehicle['location'], incident['location'], 'balanced')
            if route['path']:
                # Lower combined cost wins; extra equipment is a small tie-break bonus.
                score = route['cost'] - 0.05 * len(vehicle['equipment'])
                options.append((score, vehicle['id'], vehicle, route))
        return sorted(options)

    def write_routes(self, incident, vehicle, route):
        """Show shortest, fastest and recommended routes from the SAME origin."""
        origin = vehicle['location']
        incident['preview_vehicle'] = vehicle['id']
        incident['route'] = compact(route)
        incident['shortest'] = compact(self.campus.search(origin, incident['location'], 'distance'))
        incident['fastest'] = compact(self.campus.search(origin, incident['location'], 'time'))

    def write_exit_routes(self, incident):
        """Plan the second leg: scene to event-specific safety exit.

        Evacuation plans are advisory, and are NOT automatically driven or
        counted as dispatch-road reservations.
        """
        source, target = incident['location'], incident['exit_gate']
        incident['evacuation'] = compact(self.campus.search(source, target, 'balanced'))
        incident['exit_shortest'] = compact(self.campus.search(source, target, 'distance'))
        incident['exit_fastest'] = compact(self.campus.search(source, target, 'time'))

    def reserve(self, path):
        for a, b in zip(path, path[1:]):
            self.campus.roads[road_id(a, b)]['use'] += 1

    def rebalance(self):
        """High-priority requests plan first; lower-priority ones avoid occupied roads."""
        old_paths = {i['id']: (i['route'] or {}).get('path', []) for i in self.incidents}
        for road in self.campus.roads.values():
            road['use'] = 0

        active = sorted((i for i in self.incidents if i['status'] != 'Completed'),
                        key=lambda i: (-LEVELS[i['level']], i['id']))
        for incident in active:
            self.write_exit_routes(incident)
            if incident['vehicle']:
                vehicle = self.get_vehicle(incident['vehicle'])
                if incident['status'] == 'On scene':
                    route = self.campus.search(vehicle['location'], incident['location'])
                else:
                    route = self.campus.search(vehicle['location'], incident['location'], 'balanced')
                if route['path']:
                    incident['status'] = 'On scene' if len(route['path']) == 1 else 'En route'
                    vehicle['path'] = route['path']
                    vehicle['status'] = incident['status']
                    self.write_routes(incident, vehicle, route)
                    self.reserve(route['path'])
                else:
                    incident['status'] = vehicle['status'] = 'No route'
                    incident['route'] = incident['shortest'] = incident['fastest'] = None
                    vehicle['path'] = []
            else:
                choices = self.candidates(incident)
                if choices:
                    _, _, vehicle, route = choices[0]
                    vehicle['incident'] = incident['id']
                    incident['vehicle'] = vehicle['id']
                    incident['status'] = 'On scene' if len(route['path']) == 1 else 'En route'
                    vehicle['status'] = incident['status']
                    vehicle['path'] = route['path']
                    self.write_routes(incident, vehicle, route)
                    self.reserve(route['path'])
                    self.log(f'#{incident["id"]} auto-assigned to {vehicle["id"]}.')
                else:
                    incident['status'] = 'Waiting'
                    # Display a provisional route even if the qualified vehicle is busy.
                    options = self.candidates(incident, available_only=False)
                    if options:
                        _, _, vehicle, route = options[0]
                        self.write_routes(incident, vehicle, route)
                    else:
                        incident['route'] = incident['shortest'] = incident['fastest'] = None
                        incident['preview_vehicle'] = None

        changes = sum(bool(old_paths[i['id']]) and old_paths[i['id']] != (i['route'] or {}).get('path', [])
                      for i in active if i['vehicle'])
        if changes:
            self.log(f'{changes} response route(s) dynamically replanned.')
        return changes

    def explain(self, number, phase='exit'):
        """Trace dispatch OR incident-to-exit A*, excluding own reserved roads."""
        if not isinstance(number, int) or not 1 <= number <= len(self.incidents):
            raise ValueError('Invalid emergency number')
        if phase not in ('exit', 'dispatch'):
            raise ValueError('Choose exit or dispatch A* trace')
        target = self.incidents[number - 1]
        source = target['vehicle'] or target['preview_vehicle']
        if phase == 'dispatch' and not source:
            return None
        saved = {key: road['use'] for key, road in self.campus.roads.items()}
        try:
            for road in self.campus.roads.values():
                road['use'] = 0
            for other in sorted((i for i in self.incidents if i['status'] != 'Completed'),
                                key=lambda i: (-LEVELS[i['level']], i['id'])):
                if other['id'] == number:
                    break
                if other['vehicle'] and other['route']:
                    self.reserve(other['route']['path'])
            if phase == 'exit':
                return self.campus.search(target['location'], target['exit_gate'], 'balanced')
            return self.campus.search(self.get_vehicle(source)['location'], target['location'], 'balanced')
        finally:
            for key, road in self.campus.roads.items():
                road['use'] = saved[key]

    def finish(self, number):
        if not isinstance(number, int) or not 1 <= number <= len(self.incidents):
            raise ValueError('Invalid emergency number')
        incident = self.incidents[number-1]
        if incident['status'] == 'Completed':
            raise ValueError('Already completed')
        if not incident['vehicle']:
            raise ValueError('No team assigned yet; waiting for a suitable vehicle')
        vehicle = self.get_vehicle(incident['vehicle'])
        # College demo: checking Complete means the mission has finished.
        # Arrival is assumed; vehicle becomes available at the incident location.
        vehicle.update(status='Available', location=incident['location'], incident=None, path=[])
        incident['status'] = 'Completed'
        self.log(f'#{number} completed; {vehicle["id"]} and reserved roads released.')
        self.rebalance()  # Available vehicle immediately takes highest-priority waiting request.
        return incident

    def move(self):
        """Optional simulation helper: move assigned teams one road at a time."""
        moved = 0
        for vehicle in self.vehicles:
            if vehicle['status'] != 'En route' or len(vehicle['path']) < 2:
                continue
            a, b = vehicle['path'][:2]
            if not self.campus.roads[road_id(a, b)]['blocked']:
                vehicle['location'] = b
                moved += 1
                if b == self.incidents[vehicle['incident']-1]['location']:
                    vehicle['status'] = 'On scene'
                    self.incidents[vehicle['incident']-1]['status'] = 'On scene'
        self.rebalance()
        return moved
