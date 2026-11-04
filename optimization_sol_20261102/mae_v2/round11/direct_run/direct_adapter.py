"""Network-isolated ASA code/full-option adapter after complete coding."""
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    devices = Path('/proc/self/net/dev').read_text()
    interfaces = [line.split(':',1)[0].strip() for line in devices.splitlines() if ':' in line]
    if interfaces != ['lo']:
        raise ValueError('direct_adapter_network_isolation_required')
    rows = json.loads((BASE/'round11/prepared/cohort/dev.json').read_bytes())
    identities = json.loads((HERE/'identities.json').read_bytes())
    if len(rows) != 843 or set(identities) != {row['sample_id'] for row in rows}:
        raise ValueError('direct_adapter_incomplete_coding')
    labels = json.loads((BASE/'round11/prepared/cohort/dev_labels.json').read_bytes())
    catalog = json.loads((BASE/'round11/prepared/catalog.json').read_bytes())
    contexts = {}
    for row in rows:
        if row['dataset'] != 'asa24':
            continue
        sid = row['sample_id']
        identity = identities[sid]['result']
        code = labels[sid]['food_code']
        if code in identity.get('final_codes', []):
            contexts[sid] = {'code':code, 'options':catalog['asa_options'][code]}
    output = HERE/'contexts.json'
    fd = os.open(str(output)+'.tmp', os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(contexts, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(output)+'.tmp', output)
    print(json.dumps({'status':'direct_adapter_complete', 'rows':len(rows),
                      'contexts':len(contexts), 'exported_fields':['code','options']}))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print(json.dumps({'status':'direct_adapter_failed', 'error_type':type(error).__name__}))
        raise SystemExit(1) from None
