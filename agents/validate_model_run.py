"""Coordinator's offline checks: source/ledger/metrics and budget reconciliation."""
import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))
import evaluate
from run_experiment import cost


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def response_health(chat):
    """R-F3-1: accounting equality does not establish usable model responses."""
    issues = []
    for row in chat:
        problems = []
        reasons, empty = row.get('finish_reasons'), row.get('empty_contents')
        if row.get('status') != 200:
            problems.append('non_200_status')
        if not isinstance(reasons, list) or not reasons:
            problems.append('missing_finish_metadata')
        elif any(reason != 'stop' for reason in reasons):
            problems.append('non_stop_finish')
        if (not isinstance(empty, list) or not empty or
                not all(isinstance(value, bool) for value in empty) or
                not isinstance(reasons, list) or len(empty) != len(reasons)):
            problems.append('missing_or_invalid_content_metadata')
        elif any(empty):
            problems.append('empty_content')
        if problems:
            issues.append({'request_id': row.get('request_id'), 'step': row.get('step'), 'problems': problems})
    return issues


def validate(directory):
    conf = json.loads((directory / 'config.json').read_text())
    assert len(conf['invocations']) == 1 and conf['invocations'][0]['status'] == 'completed'
    assert not conf['invocations'][0]['uncommitted_changes']
    for name, expected in conf['code_sha256'].items():
        assert hashlib.sha256((ROOT / 'code' / name).read_bytes()).hexdigest() == expected, name
    records = read_lines(directory / 'openai_api.jsonl')
    global_records = read_lines(ROOT / 'logs/openai_api.jsonl')
    wanted = []
    for step in conf['invocations'][0]['steps']:
        start, end = step['api_log_lines']
        wanted.extend({**row, 'invocation': 1, 'step': step['name']} for row in global_records[start:end])
    assert records == wanted, 'run/global ledgers differ'
    saved_cost = json.loads((directory / 'cost.json').read_text())
    assert saved_cost['run'] == cost(records), 'cost differs'
    chat = [row for row in records if row['endpoint'].endswith('chat/completions')]
    for row in chat:
        assert row['model_requested'] == 'gpt-6.1-sol'
        if row['status'] == 200:
            assert row['model_served'] == 'gpt-6.1-sol'
        assert row['temperature'] == 1 and row['max_tokens'] is None
        assert row['max_completion_tokens'] in (None, 600, 4096)
    recomputed = evaluate.no_nan(evaluate.evaluate_run(str(directory / 'asa24_nutrition.csv'),
            str(directory / 'nutrition5k_nutrition.csv'),
            str(ROOT / 'FNDDS/2019-2020 FNDDS At A Glance - FNDDS Nutrient Values.xlsx')))
    assert recomputed == json.loads((directory / 'metrics.json').read_text()), 'metrics differ'
    total = cost(global_records)
    issues = response_health(chat)
    health = 'needs review' if issues else 'PASS'
    result = {'checks': health, 'reconciliation_checks': 'PASS', 'response_health': health,
              'health_issues': issues, 'responses': len(records),
              'status_counts': dict(Counter(row['status'] for row in records)),
              'finish_counts': dict(Counter(reason for row in chat for reason in (row.get('finish_reasons') or []))),
              'empty_chat_responses': sum(any(row.get('empty_contents') or []) for row in chat),
              'models_served': saved_cost['run']['models_served'],
              'run_cost': saved_cost['run'], 'global_cost_usd': total['usd'],
              'remaining_budget_usd': 20 - total['usd'],
              'average_per_image': {dataset: {'usd': saved_cost[f'{dataset} per image'],
                  'reasoning_tokens': sum(row['usage'].get('completion_tokens_details', {}).get('reasoning_tokens', 0)
                       for row in chat if row['step'].startswith(dataset) and row['usage']) / conf['images'][dataset]}
                  for dataset in ('asa24', 'nutrition5k')}}
    if conf['split'] == 'dev':
        predicted = sum(saved_cost[f'{dataset} per image'] * 150 for dataset in ('asa24', 'nutrition5k'))
        result['test_projection_usd'] = predicted
        result['test_projection_with_2x_margin_usd'] = 2 * predicted
        result['projection_fits_budget'] = 2 * predicted <= result['remaining_budget_usd']
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    args = parser.parse_args()
    result = validate(args.run_dir)
    (args.run_dir / 'validation.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['checks'] == 'PASS' else 1)
