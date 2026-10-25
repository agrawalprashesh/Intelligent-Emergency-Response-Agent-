"""Tiny local HTTP API: keeps the HTML frontend separate from Python AI."""
import json
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from .agent import EmergencyAgent, LEVELS, TYPES
from .campus import ALL_PLACES, EXIT_GATES, GATE_FOR_TYPE, PLACES

FRONTEND = Path(__file__).resolve().parent.parent / 'frontend'


def snapshot(agent):
    return dict(places=ALL_PLACES, campus_locations=list(PLACES),
                exit_gates=EXIT_GATES, gates_by_type=GATE_FOR_TYPE,
                roads=list(agent.campus.roads.values()),
                vehicles=agent.vehicles, incidents=agent.incidents,
                types=list(TYPES), levels=list(LEVELS), logs=agent.logs)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND), **kwargs)

    def send_json(self, data, status=200):
        content = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/state':
            return self.send_json(snapshot(self.server.agent))
        if path not in ('/', '/index.html', '/style.css', '/app.js'):
            return self.send_error(404)
        self.path = '/index.html' if path == '/' else path
        super().do_GET()

    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size < 5000:
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object')
            result = self.action(urlparse(self.path).path, data)
            self.send_json({'state': snapshot(self.server.agent), **result})
        except (ValueError, KeyError, TypeError) as error:
            self.send_json({'error': str(error)}, 400)

    def action(self, path, data):
        agent = self.server.agent
        if path == '/api/search':
            return {'search': agent.campus.search(data['start'], data['goal'], data.get('mode', 'balanced'))}
        if path == '/api/incident-search':
            return {'search': agent.explain(int(data['id']), data.get('phase', 'exit'))}
        if path == '/api/register':
            item = agent.register(data['location'], data['event'], data.get('level', 'Auto'))
            return {'message': f'#{item["id"]} registered — route calculated automatically', 'incident_id': item['id']}
        if path == '/api/demo':
            ids = []
            for where, event in [('Hostel', 'Medical'), ('Lab', 'Accident'), ('Sports', 'Fire')]:
                ids.append(agent.register(where, event)['id'])
            return {'message': '3 emergencies registered and routed automatically', 'incident_id': ids[-1]}
        if path == '/api/finish':
            agent.finish(int(data['id']))
            return {'message': 'Request completed; roads and vehicle released, waiting calls rechecked'}
        if path == '/api/road':
            road = agent.campus.change_road(data['key'], data['change'])
            changed = agent.rebalance()
            return {'message': f'{road["a"]} ↔ {road["b"]} updated · {changed} route(s) changed'}
        if path == '/api/reset':
            agent.campus.reset()
            agent.rebalance()
            return {'message': 'Road traffic cleared and all active routes recalculated'}
        if path == '/api/move':
            return {'message': f'{agent.move()} team(s) advanced one road'}
        raise ValueError('Unknown action')


def run(host='127.0.0.1', port=8000, open_browser=True):
    server = HTTPServer((host, port), Handler)
    server.agent = EmergencyAgent()
    address = f'http://{host}:{server.server_port}'
    print(f'P-15 Campus Rescue AI: {address}  (Ctrl+C to stop)')
    if open_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('Server stopped.')
    finally:
        server.server_close()
