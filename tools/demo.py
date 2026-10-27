"""Offline presentation of archived measurements. Standard library only; no API client."""
import argparse
import csv
import hashlib
import json
import math
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ['runs/test', 'runs/test-gpt-6.1-sol']


def read_json(path):
    return json.loads((ROOT / path).read_text())


def frame(path):
    with (ROOT / path).open(newline='') as stream:
        return list(csv.DictReader(stream))


def num(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return math.nan


def complete(row):
    return (num(row['IngredientNum']) > 0 and num(row['WeightError']) == 0
            and num(row['FoodCodeError']) == 0)


def payload():
    comp = read_json('runs/comparison-gpt-4o-vs-sol/comparison.json')
    result = {'mode': 'archived_results', 'api_calls': 0,
            'comparison': comp,
            'metrics': [read_json(run + '/metrics.json') for run in RUNS],
            'examples': read_json('demo/examples.json'),
            'health_warning': 'Sol formal run retains one retried HTTP 500 and response_health=needs review.'}
    def clean(value):
        if isinstance(value,float) and not math.isfinite(value):return None
        if isinstance(value,list):return [clean(v) for v in value]
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
        return value
    return clean(result)


def check():
    saved = read_json('demo/manifest.json')
    for name, expected in saved['files'].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('Archived demo file changed: ' + name)
    data = payload()
    comp = data['comparison']
    n5k = []
    for i, run in enumerate(RUNS):
        asa = frame(run + '/asa24_nutrition.csv')
        n5 = frame(run + '/nutrition5k_nutrition.csv')
        valid_asa = [r for r in asa if math.isfinite(num(r['TotalWeight']))]
        valid_n5 = [r for r in n5 if complete(r)]
        assert len(asa) == len(n5) == 150
        assert len(valid_asa) == comp['asa24']['exact_n'][i]
        assert len(valid_n5) == comp['nutrition5k']['complete_n'][i]
        for rows, prediction, reference, expected in [
            (valid_asa, 'TotalWeight', 'Weight', comp['asa24']['own_subset_mae']['Weight (g)'][['baseline','comparison'][i]]),
            (valid_n5, 'GPTWeight', 'total_mass', comp['nutrition5k']['own_subset_mae']['Weight (g)'][['baseline','comparison'][i]])]:
            observed = sum(abs(num(r[prediction])-num(r[reference])) for r in rows)/len(rows)
            assert math.isclose(observed, expected, rel_tol=1e-10)
        n5k.append({r['dish_id']:r for r in valid_n5})
    shared = set(n5k[0]) & set(n5k[1])
    assert len(shared) == comp['nutrition5k']['common_complete_n'] == 79
    for i in range(2):
        mae = sum(abs(num(n5k[i][k]['GPTWeight'])-num(n5k[i][k]['total_mass'])) for k in shared)/len(shared)
        assert math.isclose(mae,comp['nutrition5k']['common_subset_mae']['Weight (g)'][['baseline','comparison'][i]],rel_tol=1e-10)
    print(json.dumps({'status':'PASS','mode':'archived_results','api_calls':0,
                      'files_verified':len(saved['files']),'asa24_exact':comp['asa24']['exact_n'],
                      'nutrition5k_complete':comp['nutrition5k']['complete_n'],'shared_dishes':79}))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split('?',1)[0]
        if route == '/api/results':
            return self.reply(json.dumps(payload()).encode(), 'application/json')
        if route == '/api/health':
            return self.reply(b'{"mode":"archived_results","api_calls":0}', 'application/json')
        static = {'/':('demo/index.html','text/html; charset=utf-8')}
        for example in read_json('demo/examples.json'):
            static['/'+example['image']] = (example['image'],'image/png')
        for ext, kind in [('md','text/plain; charset=utf-8'),('pdf','application/pdf'),
                          ('docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document')]:
            static['/reports/REPORT.'+ext] = ('output/report/REPORT.'+ext,kind)
        if route not in static:
            self.send_error(404); return
        file, kind = static[route]
        try:
            content = (ROOT / file).read_bytes()
        except FileNotFoundError:
            self.send_error(404); return
        self.reply(content,kind)

    def reply(self, content, kind):
        self.send_response(200)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(content)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store')
        self.end_headers(); self.wfile.write(content)

    def log_message(self, *args):
        pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--open',action='store_true')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    check()
    if args.check:return
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    url='http://127.0.0.1:'+str(server.server_port)
    print('Archived results only; no new inference. Open '+url,flush=True)
    if args.open: threading.Timer(.5,lambda:webbrowser.open(url)).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
