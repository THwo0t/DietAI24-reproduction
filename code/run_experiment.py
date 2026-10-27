"""Run the pipeline of the original scripts on one split (CHECKLIST.md E1, E2).

Each step is the script's own main() with the paths of this run: food codes (rag_food_code.py)
for both datasets, the ASA24 portion step of the paper protocol and the end-to-end one
(rag_portion_size.py), the Nutrition5k grams (rag_portion_size.py --dataset nutrition5k),
weights and nutrients (nutrient_estimate.py, nutrient_estimate_mix.py) and the metrics
(evaluate.py). The tables of the run stay in runs/<split>/; a step that is rerun skips what is
done. Every API response is a line of config.API_LOG_PATH; the lines a step added are its
usage, kept in the run directory with the cost of each step. A directory holds one run under
one configuration; a different one needs a new directory (R-E1-1).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from argparse import Namespace
from datetime import datetime, timezone

import pandas as pd

import chagApp_openai
import config
import evaluate
import nutrient_estimate
import nutrient_estimate_mix
import rag_food_code
import rag_portion_size

SPLITS = {'dev': ('../df_results_dev.csv', '../dish_metadata_dev.csv'),
          'test': ('../df_results.csv', '../dish_metadata.csv')}
FOODS_CSV = '../FNDDS/2019-2020 FNDDS - Foods and Beverages.csv'
IMAGE_LINK_CSV = '../df_image_link.csv'
FOOD_WEIGHTS_CSV = '../FoodWeights.csv'
NUTRITION_XLSX = '../FNDDS/2019-2020 FNDDS At A Glance - FNDDS Nutrient Values.xlsx'
# USD per million tokens: standard processing, short context; input, cached input, output.
# Sol checked 2026-10-27: https://developers.openai.com/api/docs/models/gpt-6.1-sol
# and https://developers.openai.com/api/docs/pricing . Reasoning is already included in
# completion_tokens, so it must not be charged a second time (F2).
PRICE_SOURCE = {'url': 'https://developers.openai.com/api/docs/pricing', 'checked': '2026-10-27',
                'tier': 'standard', 'sol_max_input_tokens_at_this_rate': 272000}
PRICES = {'gpt-4o-2024-08-06': (2.50, 1.25, 10.00), 'gpt-6.1-sol': (2.00, 0.10, 10.00),
          'text-embedding-3-large': (0.13, 0.13, 0.0)}
# The code that builds the requests (prompts, options, images, models, retries)
INFERENCE_CODE = ('rag_food_code.py', 'rag_portion_size.py', 'chagApp_openai.py', 'config.py', 'api_log.py')


def api_lines():
    if not os.path.exists(config.API_LOG_PATH):
        return []
    with open(config.API_LOG_PATH) as f:
        return [json.loads(line) for line in f]


def cost(records):
    """Tokens and USD of logged responses; a model without a price stops the count."""
    total = {'requests': len(records), 'errors': 0, 'prompt_tokens': 0, 'cached_tokens': 0, 'completion_tokens': 0,
             'reasoning_tokens': 0, 'usd': 0.0,
             'models_served': sorted({r['model_served'] for r in records if r['model_served']})}
    for record in records:
        if record['status'] != 200:
            total['errors'] += 1
        usage = record['usage'] or {}
        if not usage:
            continue
        model = record['model_served'] or record['model_requested']
        if model not in PRICES:
            raise KeyError(f'no price for {model}')
        price_in, price_cached, price_out = PRICES[model]
        prompt = usage.get('prompt_tokens', 0)
        cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens') or 0
        completion = usage.get('completion_tokens', 0)
        if model == config.COMPARISON_MODEL and prompt > 272000:
            raise ValueError('Sol long-context pricing is not configured')
        total['prompt_tokens'] += prompt
        total['cached_tokens'] += cached
        total['completion_tokens'] += completion
        total['reasoning_tokens'] += (usage.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0
        total['usd'] += ((prompt - cached) * price_in + cached * price_cached + completion * price_out) / 1e6
    return total


def csv_rows(csv_path):
    """Rows of a table as CSV records, not lines: a description or an answer may span lines (R-E1-2)."""
    return len(pd.read_csv(csv_path))


def images_of(split, path):
    """Images (dishes) of each dataset in the run; the sample, the food code and the nutrient
    tables must have as many."""
    images = {}
    for dataset, source in zip(('asa24', 'nutrition5k'), SPLITS[split]):
        counts = {csv_rows(source), csv_rows(path(f'{dataset}_food_codes.csv')), csv_rows(path(f'{dataset}_nutrition.csv'))}
        if len(counts) > 1:
            raise RuntimeError(f'{dataset}: the sample, the food code and the nutrient tables differ in rows {sorted(counts)}')
        images[dataset] = counts.pop()
    return images


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def inference_config(split, foods_csv):
    """What the answers of a run depend on: the split, the models, the temperature, the image
    size, the code that builds the requests and the tables it reads (R-E1-1)."""
    code_dir = os.path.dirname(os.path.abspath(__file__))
    return {'split': split, 'models': dict(config.MODELS),
            'temperature': config.temperature_for(config.MODELS['llm']),
            'token_limits': {'description': config.completion_limit(config.MODELS['llm_vision'],
                                                                  config.description_limit(config.MODELS['llm_vision'])),
                             'portion': config.completion_limit(config.MODELS['llm_vision'], 600)},
            'image_size': list(chagApp_openai.IMAGE_SIZE),
            'code_sha256': {name: sha256(os.path.join(code_dir, name)) for name in INFERENCE_CODE},
            'inputs_sha256': {source: sha256(source) for source in
                              (*SPLITS[split], IMAGE_LINK_CSV, FOOD_WEIGHTS_CSV, NUTRITION_XLSX, foods_csv)}}


def run_records(run_dir):
    path = os.path.join(run_dir, 'openai_api.jsonl')
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f]


def run(split, run_dir, workers=1, foods_csv=FOODS_CSV, index_dir=rag_food_code.INDEX_DIR):
    """One invocation of the run in run_dir; a later invocation resumes it (R-E1-1).

    config.json holds the configuration the answers depend on, and a directory started under
    another one, or by the old driver, is not resumed. It records each invocation as it goes:
    its start, code, workers and steps, each step with its lines of config.API_LOG_PATH, and
    its end or failure. After each step, failed ones included, the step's responses are added
    to the run's openai_api.jsonl with the step and the invocation; cost.json is over all of
    them, so a resumed run keeps the cost and the served models of the earlier invocations.
    """
    os.makedirs(run_dir, exist_ok=True)
    path = lambda name: os.path.join(run_dir, name)
    inference = inference_config(split, foods_csv)
    if os.path.exists(path('config.json')):
        with open(path('config.json')) as f:
            run_config = json.load(f)
        if {key: run_config.get(key) for key in inference} != json.loads(json.dumps(inference)):
            raise RuntimeError(f'{run_dir} holds a run of another configuration (or of the old driver); use a new run directory')
    elif os.listdir(run_dir):
        raise RuntimeError(f'{run_dir} has files but no config.json; use a new run directory')
    else:
        run_config = {**inference, 'invocations': [], 'prices_usd_per_million_tokens': PRICES,
                      'price_source': PRICE_SOURCE}
    for source, name in zip(SPLITS[split], ('asa24_food_codes.csv', 'nutrition5k_food_codes.csv')):
        if not os.path.exists(path(name)):
            shutil.copyfile(source, path(name))
    invocation = {
        'started': now(), 'status': 'running', 'workers': workers,
        # the code the invocation starts from (edits made while it runs do not change it)
        'commit': subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
        'uncommitted_changes': bool(subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'],
                                                   capture_output=True, text=True).stdout),
        'steps': []}
    run_config['invocations'].append(invocation)
    number = len(run_config['invocations'])

    def save():
        """config.json and cost.json from the run's responses so far."""
        records = run_records(run_dir)
        steps = list(dict.fromkeys(s['name'] for i in run_config['invocations'] for s in i['steps']))
        usage = {name: cost([r for r in records if r['step'] == name]) for name in steps}
        usage['run'] = cost(records)
        for dataset in ('asa24', 'nutrition5k'):
            if 'images' in run_config:
                usage[f'{dataset} per image'] = (sum(usage[n]['usd'] for n in steps if n.startswith(dataset))
                                                 / run_config['images'][dataset])
        mine = cost([r for r in records if r['invocation'] == number])
        invocation.update(requests=mine['requests'], usd=mine['usd'], models_served=mine['models_served'])
        run_config['models_served'] = usage['run']['models_served']
        with open(path('cost.json'), 'w') as f:
            json.dump(usage, f, indent=1)
        with open(path('config.json'), 'w') as f:
            json.dump(run_config, f, indent=1)
        return usage

    def step(name, function, args):
        start = len(api_lines())
        lines = [start, None]
        invocation['steps'].append({'name': name, 'api_log_lines': lines})
        save()
        print(f'{name} ...', flush=True)
        try:
            function(args)
        finally:
            records = api_lines()[start:]
            lines[1] = start + len(records)
            with open(path('openai_api.jsonl'), 'a') as f:
                for record in records:
                    f.write(json.dumps({**record, 'invocation': number, 'step': name}) + '\n')
            save()

    try:
        for dataset in ('asa24', 'nutrition5k'):
            step(f'{dataset} food codes', rag_food_code.main, Namespace(
                csv_file=foods_csv, checkpoint_file=path(f'{dataset}_checkpoint.txt'),
                results_file=path(f'{dataset}_food_codes.csv'), log_path=path('process_images.log'),
                index_dir=index_dir, workers=workers, dataset=dataset))
        step('asa24 portions (protocol)', rag_portion_size.main, rag_portion_size.parse_args([
            '--results_path', path('asa24_food_codes.csv'), '--image_link_path', IMAGE_LINK_CSV,
            '--output_path', path('asa24_output.csv'), '--portion_path', path('asa24_portion.csv'), '--workers', str(workers)]))
        step('asa24 portions (end to end)', rag_portion_size.main_end_to_end, rag_portion_size.parse_args([
            '--portion_path', path('asa24_portion.csv'), '--end_to_end', '--food_weights_path', FOOD_WEIGHTS_CSV,
            '--nutrition_path', NUTRITION_XLSX, '--workers', str(workers)]))
        step('nutrition5k grams', rag_portion_size.main_nutrition5k, rag_portion_size.parse_args([
            '--results_path', path('nutrition5k_food_codes.csv'), '--portion_path', path('nutrition5k_portion.csv'),
            '--dataset', 'nutrition5k', '--workers', str(workers)]))
        nutrient_estimate.main(nutrient_estimate.parse_args([
            '--results_path', path('asa24_portion.csv'), '--image_link_path', IMAGE_LINK_CSV,
            '--portion_code_path', FOOD_WEIGHTS_CSV, '--nutrition_path', NUTRITION_XLSX, '--output_path', path('asa24_nutrition.csv')]))
        nutrient_estimate_mix.main(nutrient_estimate_mix.parse_args([
            '--results_path', path('nutrition5k_portion.csv'), '--nutrition_path', NUTRITION_XLSX,
            '--output_path', path('nutrition5k_nutrition.csv')]))
        evaluate.main(evaluate.parse_args([
            '--asa24', path('asa24_nutrition.csv'), '--nutrition5k', path('nutrition5k_nutrition.csv'),
            '--nutrition_path', NUTRITION_XLSX, '--output_json', path('metrics.json'), '--output_md', path('metrics.md')]))
        run_config['images'] = images_of(split, path)
        invocation['status'] = 'completed'
    except BaseException as e:  # Ctrl-C included: the invocation is recorded as failed
        invocation['status'] = f'failed: {type(e).__name__}'
        raise
    finally:
        invocation['finished'] = now()
        usage = save()
    return usage


def main(args):
    config.select_model(args.model)
    usage = run(args.split, args.run_dir or os.path.join('..', 'runs', args.split), args.workers)
    print(json.dumps({k: v if isinstance(v, float) else {'usd': v['usd'], 'requests': v['requests']}
                      for k, v in usage.items()}, indent=1))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run the whole pipeline on the development or the test set.")
    parser.add_argument("--split", choices=sorted(SPLITS), required=True)
    parser.add_argument("--run_dir", help="Default ../runs/<split>")
    parser.add_argument("--workers", type=int, default=1, help="Images processed in parallel in each step.")
    parser.add_argument("--model", choices=config.CHAT_MODELS, default=config.DEFAULT_MODEL,
                        help="Text and vision model; embeddings remain text-embedding-3-large.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    main(parse_args())
