"""Run the original pipeline on one development image per dataset in a new demo directory."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
sys.path.insert(0,str(ROOT/'tools'))
from runtime_bundle import ASSETS, INDEX, FOODS, NUTRIENTS, restore_index, verify_assets


class DemoStop(BaseException):
    """Escapes the original pipeline's broad retry handlers without submitting more requests."""


class Budget:
    def __init__(self, usd, requests=80):self.limit=usd;self.max_requests=requests;self.spent=0.;self.requests=0
    def before_request(self):
        if self.requests>=self.max_requests or self.spent>=self.limit:
            raise DemoStop('Demo request/spend threshold reached; no further request submitted.')
        self.requests+=1


def request_transport(budget):
    import httpx
    import api_log
    import run_experiment
    class Transport(httpx.BaseTransport):
        def __init__(self):self.inner=httpx.HTTPTransport(retries=0)
        def handle_request(self,request):
            if request.url.scheme!='https' or request.url.host!='api.openai.com':
                raise DemoStop('Demo only supports the official HTTPS API endpoint.')
            budget.before_request()
            response=self.inner.handle_request(request)
            response.request=request
            response.read()
            api_log.log_response(response)
            try:body=response.json()
            except ValueError:body={}
            requested=json.loads(request.content)
            record={'status':response.status_code,'model_served':body.get('model'),
                    'model_requested':requested.get('model'),'usage':body.get('usage')}
            try:budget.spent+=run_experiment.cost([record])['usd']
            except (ValueError,KeyError):raise DemoStop('Unrecognized model/pricing; stopped after recording this response.')
            return response
        def close(self):self.inner.close()
    return Transport()


def inputs():
    import pandas as pd
    verify_assets()
    collection=restore_index()
    selected=[]
    for name in ['df_results_dev.csv','dish_metadata_dev.csv']:
        table=pd.read_csv(ASSETS/name).head(1).copy()
        if len(table)!=1:raise ValueError('Demo needs one development row per dataset')
        original=(ROOT/'code'/str(table.iloc[0]['Link'])).resolve().relative_to(ROOT)
        image=ASSETS/original
        if not image.is_file():raise ValueError('Bundled development image missing')
        table['Link']=str(image)
        selected.append(table)
    if collection.count()!=5624:raise ValueError('Saved FNDDS index is incomplete; no paid rebuild is allowed')
    return selected


def run(model, threshold):
    import httpx
    import api_log
    import config
    import chagApp_openai
    import rag_food_code
    import run_experiment
    config.load_api_key()  # .env only; fail before creating a run or making any request.
    samples=inputs()
    config.select_model(model)
    name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    output=ROOT/'demo-runs'/name;output.mkdir(parents=True)
    paths=[]
    for table,filename in zip(samples,['asa24.csv','nutrition5k.csv']):
        path=output/filename;table.to_csv(path,index=False);paths.append(str(path))
    config.API_LOG_PATH=str(output/'api-ledger.jsonl')
    run_experiment.SPLITS['demo']=tuple(paths)
    run_experiment.IMAGE_LINK_CSV=str(ASSETS/'df_image_link.csv')
    run_experiment.FOOD_WEIGHTS_CSV=str(ASSETS/'FoodWeights.csv')
    run_experiment.NUTRITION_XLSX=str(ASSETS/NUTRIENTS)
    budget=Budget(threshold)
    def client(transport=None):
        return api_log.RedactedOpenAI(api_key=config.load_api_key(),base_url=config.OPENAI_API_BASE,
            max_retries=1,timeout=45,
            http_client=httpx.Client(transport=transport or request_transport(budget),timeout=45,follow_redirects=False))
    api_log.openai_client=client
    rag_food_code.openai_client=client
    chagApp_openai.openai_client=client
    settings={'kind':'new_development_demo','formal_test':False,'development_rows_per_dataset':1,
              'model':model,'spend_stop_threshold_usd':threshold,
              'threshold_scope':'Estimated returned usage; a single in-flight request can exceed the threshold.',
              'sdk_retries':1,'timeout_seconds_per_request':45,'maximum_http_requests':80,
              'index':'Rebuilt locally from the original saved embeddings; native ANN layout can differ.'}
    (output/'demo-config.json').write_text(json.dumps(settings,indent=2)+'\n')
    print('Running two development images; outputs: '+str(output),flush=True)
    original_cwd=Path.cwd()
    try:
        os.chdir(ROOT/'code')
        run_experiment.run('demo',str(output/'results'),workers=1,
                           foods_csv=str(ASSETS/FOODS),index_dir=str(INDEX))
    finally:
        os.chdir(original_cwd)
        (output/'demo-usage.json').write_text(json.dumps({'http_requests':budget.requests,'estimated_usd':budget.spent},indent=2)+'\n')
    print('Demo completed. Inspect results/metrics.md and results/config.json; outputs may contain genuine failures.')
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run',action='store_true',help='Validate imports, runtime and index without key or API requests')
    parser.add_argument('--allow-paid',action='store_true',help='Explicitly authorize the small paid demonstration')
    parser.add_argument('--model',choices=['gpt-4o-2024-08-06','gpt-6.1-sol'],default='gpt-4o-2024-08-06')
    parser.add_argument('--max-usd',type=float,default=.5,help='Stop between requests at this estimated spend; not an invoice hard cap')
    args=parser.parse_args()
    if args.dry_run and args.allow_paid:parser.error('Choose --dry-run or --allow-paid')
    if not args.dry_run and not args.allow_paid:parser.error('Start with --dry-run; real inference requires --allow-paid')
    if not math.isfinite(args.max_usd) or not 0<args.max_usd<=1:parser.error('--max-usd must be positive and at most 1')
    if args.dry_run:
        import run_experiment  # Actual inference dependencies must import successfully.
        selected=inputs()
        print(json.dumps({'status':'PASS','kind':'readiness_check','api_calls':0,'key_required':False,
                          'development_rows':[len(x) for x in selected],'index_vectors':5624}))
        return
    try:run(args.model,args.max_usd)
    except DemoStop as error:raise SystemExit(str(error))

if __name__=='__main__':main()
