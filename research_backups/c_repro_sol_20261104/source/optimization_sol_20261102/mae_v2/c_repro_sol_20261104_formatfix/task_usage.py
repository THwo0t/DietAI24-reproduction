"""Account for both the preserved parser-failure run and its cache repair."""
from collections import Counter
import json
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent.parent / 'src')]
from opt_provider import atomic_json

HERE = Path(__file__).resolve().parent
FIRST = HERE.parent / 'c_repro_sol_20261104'


def main():
    if not (HERE / 'summary.json').exists():
        raise ValueError('completed_format_repair_required')
    totals = {role: dict(requests=0, errors=0, prompt_tokens=0, completion_tokens=0, total_tokens=0)
              for role in ('chat', 'embedding')}
    by_run, successful_hashes = {}, {}
    for name, directory in (('initial_preserved_run', FIRST), ('format_compatible_run', HERE)):
        by_run[name] = Counter()
        successful_hashes[name] = set()
        for profile in ('N5', 'ASA'):
            path = directory / 'run' / profile / 'provider/requests.jsonl'
            for line in path.read_text().splitlines() if path.exists() else []:
                record = json.loads(line)
                role = record['role']
                values = totals[role]
                values['requests'] += 1
                values['errors'] += record.get('status') != 200
                by_run[name][role] += 1
                for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                    values[key] += record.get('usage', {}).get(key, 0)
                if record.get('status') == 200:
                    successful_hashes[name].add((role, record['request_hash']))
    overlap = successful_hashes['initial_preserved_run'] & successful_hashes['format_compatible_run']
    if overlap:
        raise ValueError('previous_successful_payload_was_transmitted_again')
    observations = Counter()
    for profile in ('N5', 'ASA'):
        path = HERE / 'run' / profile / 'provider/observations.jsonl'
        for line in path.read_text().splitlines() if path.exists() else []:
            record = json.loads(line)
            observations['cached_returns' if record['cache_present_before'] else 'uncached_returns'] += 1
    output = dict(scope='all_transmissions_for_this_user_task_including_initial_run_and_format_repair',
        totals=totals, by_run={name: dict(value) for name, value in by_run.items()},
        format_run_observations=dict(observations), retransmitted_previously_successful_payloads=0,
        third_party_cost_usd=None, note='Unit price unverified; reasoning is already included in completion tokens.',
        original_results_preserved=True, independent_acceptance_opened=False, github_uploaded=False)
    atomic_json(HERE / 'task_usage.json', output)
    print(json.dumps(output))


if __name__ == '__main__':
    main()
