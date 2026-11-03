"""Private identity projection of four fixed legacy manifests, never eligibility.

Hashes describe this capture only. They are not historical exposure proof; a
caller must compare independently pinned old snapshots and preserve their blocks.
No image path, seal, label or other manifest is followed. No CLI or write path.
"""
import csv
import io
from pathlib import Path
import re

from source_census import LEGACY_MANIFESTS, REPO, bounded_read as secure_bounded_read, require, sha

DISH = re.compile(r'dish_[0-9]{10}\Z')
PATH_DISH = re.compile(r'(?<![A-Za-z0-9])dish_[0-9]{10}(?![0-9])')
CODE = re.compile(r'[0-9]{8}\Z')
IDENTITY = re.compile(r'[A-Za-z0-9_.-]{1,255}\Z')
MAX_ROWS = 100000


def _read(root, relative):
    require(relative in LEGACY_MANIFESTS, 'unregistered_legacy_manifest')
    return secure_bounded_read(root, relative)


def _project(raw):
    # csv decoding is structural only: nonidentity columns remain uninterpreted
    # strings and never leave this function, including in error messages.
    reader = csv.reader(io.StringIO(raw.decode('utf-8-sig'), newline=''), strict=True)
    headers = next(reader, None)
    require(headers and len(headers) == len(set(headers)), 'unique_legacy_headers_required')
    require('dataset' in headers, 'legacy_dataset_header_required')
    columns = {key: headers.index(key) for key in
               ('dataset', 'dish_id', 'sample_id', 'image_path', 'reference_food_code') if key in headers}
    out, seen = [], set()
    for values in reader:
        require(len(out) < MAX_ROWS and len(values) == len(headers), 'bounded_rectangular_legacy_rows_required')
        row = {key: values[index] for key, index in columns.items()}
        dataset = row['dataset'].lower()
        require(dataset in ('asa24', 'nutrition5k'), 'unknown_legacy_dataset')
        item = {'dataset': dataset}
        sample = row.get('sample_id', '')
        if sample:
            require(IDENTITY.fullmatch(sample), 'invalid_legacy_sample_identity')
            item['sample_id'] = sample
        image = row.get('image_path', '')
        # Pure lexical extraction: absolute/traversal-looking paths are never
        # resolved or opened. Only a safe basename can become an identity.
        basename = image.rsplit('/', 1)[-1] if image else ''
        if basename:
            require(IDENTITY.fullmatch(basename) and basename not in ('.', '..'),
                    'invalid_legacy_image_basename')
            item['image_basename'] = basename
        if dataset == 'nutrition5k':
            candidates = set()
            explicit = row.get('dish_id', '')
            if explicit:
                require(DISH.fullmatch(explicit), 'invalid_legacy_dish_identity')
                candidates.add(explicit)
            if sample:
                value = sample.removeprefix('nutrition5k-')
                require(DISH.fullmatch(value), 'invalid_legacy_n5_sample_identity')
                candidates.add(value)
            candidates.update(PATH_DISH.findall(image))
            require(len(candidates) == 1, 'unambiguous_legacy_dish_identity_required')
            item['dish_id'] = candidates.pop()
            key = (dataset, item['dish_id'])
        else:
            require(bool(basename), 'legacy_asa_image_identity_required')
            code = row.get('reference_food_code', '')
            if code:
                require(CODE.fullmatch(code), 'exact_legacy_food_code_required')
                item['reference_food_code'] = code
            key = (dataset, basename)
        require(key not in seen and (not sample or ('sample', sample) not in seen),
                'duplicate_legacy_identity')
        seen.add(key)
        if sample:
            seen.add(('sample', sample))
        out.append(item)
    return out


def _load_at(root):
    """Private synthetic-fixture hook: root only, never an alternate file list."""
    root = Path(root)
    require(root.is_absolute() and '..' not in root.parts, 'absolute_legacy_root_required')
    captured, sources = {}, []
    for relative in LEGACY_MANIFESTS:
        try:
            raw = _read(root, relative)
        except FileNotFoundError:
            sources.append({'path': relative, 'status': 'missing_unresolved'})
            continue
        captured[relative] = raw
        sources.append({'path': relative, 'status': 'captured_prospective', 'sha256': sha(raw)})
    # Authenticate captured bytes before parsing and once again afterwards.
    def revalidate():
        for source in sources:
            relative = source['path']
            if relative in captured:
                require(_read(root, relative) == captured[relative], 'legacy_source_changed')
            else:
                try:
                    _read(root, relative)
                except FileNotFoundError:
                    continue
                raise ValueError('legacy_source_changed')
    revalidate()
    identities = []
    for source in sources:
        if source['path'] not in captured:
            continue
        rows = _project(captured[source['path']])
        if not rows:
            source['status'] = 'empty_unresolved'
        source['identity_count'] = len(rows)
        identities.extend(dict(row, source_path=source['path']) for row in rows)
    revalidate()
    missing = sum(s['status'] == 'missing_unresolved' for s in sources)
    empty = sum(s['status'] == 'empty_unresolved' for s in sources)
    return {'private_identities': identities, 'sources': sources,
            'summary': {'fixed_manifest_count': len(LEGACY_MANIFESTS),
                        'missing_unresolved_count': missing, 'empty_unresolved_count': empty,
                        'unknown_identity_count': 0,
                        'dataset_identity_counts': {d: sum(r['dataset'] == d for r in identities)
                                                    for d in ('asa24', 'nutrition5k')}},
            'source_hashes_are_prospective': True,
            'historical_exposure_proven': False, 'exposure_complete': False,
            'source_association_complete': False, 'candidate_eligibility_evaluated': False,
            'grants_sampling_download_or_inference': False,
            'may_remove_historical_snapshot_blocks': False,
            'api_calls': 0, 'image_files_opened': 0, 'candidate_targets_interpreted': 0}


def load_legacy_inputs():
    """Fixed public entrypoint; private result must not be printed or published."""
    return _load_at(REPO.parent)
