"""Finite metadata supplement; no exposure, association or action permission.

Only load_projected reads a body: the fixed authenticated census control artifact.
inspect_links returns private raw readlink text; callers must never publish it.
No target body, image, label or credential is opened. No CLI or writes exist.
"""
import os
from pathlib import Path
import posixpath
import stat

import source_census as sc

CENSUS = sc.OUTPUT
CENSUS_SHA = '46a40f27b9da663b93611523677ed3ddf038f8bc91111c80c250489284b5db04'
DELIVERY = 'optimization_sol_20261102/delivery/'
DEPENDENCY_ROOTS = ('.tools', '.venv-demo') + tuple(
    DELIVERY + folder + '/' + dependency
    for folder in ('clean-final', 'clean-review-v1', 'clean-review-v3', 'environment-preflight')
    for dependency in ('.tools', '.venv-demo'))
IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.heic', '.avif'}
KINDS = {'file', 'directory', 'symlink_unresolved', 'special_unresolved', 'excluded', 'credential_name_excluded'}


def canonical(path):
    sc.require(isinstance(path, str) and bool(path) and '\\' not in path
               and '\x00' not in path and not path.startswith('/')
               and all(p not in ('', '.', '..') for p in path.split('/')), 'canonical_relative_path_required')
    return path


def contract():
    return {key: False for key in ('exposure_complete', 'source_association_complete',
        'identity_complete', 'candidate_eligibility', 'grants_sampling_download_or_inference',
        'validation_content_opened', 'research_file_bodies_opened', 'production_writes', 'api_calls')}


def classification(path):
    if any(path == root or path.startswith(root + '/') for root in DEPENDENCY_ROOTS):
        return 'dependency'
    # Exact component names only; a directory containing "report" is insufficient.
    if any(part in {'report-render', 'report-smoke', 'reports'} for part in path.split('/')[:-1]):
        return 'rendered_evidence'
    return 'research_potential'


def project_paths(census):
    """Pure, bounded projection. Classification never establishes non-exposure."""
    entries = census.get('entries') if isinstance(census, dict) else None
    sc.require(isinstance(entries, list) and len(entries) <= sc.MAX_ENTRIES, 'finite_census_entries_required')
    rows, seen, credentials = [], set(), 0
    for entry in entries:
        sc.require(isinstance(entry, dict) and entry.get('kind') in KINDS, 'valid_census_entry_required')
        kind = entry['kind']
        if kind == 'credential_name_excluded':
            sc.require(set(entry) == {'kind'}, 'credential_names_must_remain_redacted')
            credentials += 1
            continue
        path = canonical(entry.get('path'))
        sc.require(path not in seen, 'duplicate_census_path')
        seen.add(path)
        label = classification(path)
        image = kind == 'file' and Path(path).suffix.lower() in IMAGE_SUFFIXES
        if kind == 'file':
            sc.require(type(entry.get('bytes')) is int and entry['bytes'] >= 0,
                       'census_file_size_required')
        rows.append({'path': path, 'kind': kind, **({'bytes': entry['bytes']} if kind == 'file' else {}),
                     'classification': label, 'image': image,
                     'disposition': 'unresolved_exclusion' if kind == 'excluded' else 'metadata_only_pending_identity',
                     'generated_evidence_explanation': ('explicit report-render/report-smoke/reports path; '
                         'generated provenance unverified; retained as potential input') if label == 'rendered_evidence' else None})
    rows.sort(key=lambda row: row['path'])
    images = [r['path'] for r in rows if r['image']]
    links = [r['path'] for r in rows if r['kind'] == 'symlink_unresolved']
    excluded = [r['path'] for r in rows if r['kind'] == 'excluded']
    return {'schema_version': 1, 'status': 'finite_metadata_projection_not_closure', 'entries': rows,
            'image_paths': images, 'potential_image_paths': list(images), 'linked_paths': links,
            'excluded_paths': excluded, 'credential_name_excluded_count': credentials,
            'counts': {'entries': len(entries), 'named_entries': len(rows), 'images': len(images),
                       'links': len(links), 'excluded': len(excluded), 'credential_name_excluded': credentials},
            'claims': contract()}


def _metadata(repo, relative, readlink=False):
    """Hold a no-follow parent; reject parent replacement before and after use."""
    path = Path(repo) / canonical(relative)
    fd = sc.directory_fd(path.parent)
    try:
        sc.require(sc.same_directory(path.parent, fd), 'link_parent_changed')
        before = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        raw = os.readlink(path.name, dir_fd=fd) if readlink and stat.S_ISLNK(before.st_mode) else None
        after = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        sc.require((before.st_dev, before.st_ino, before.st_mode, before.st_mtime_ns, before.st_ctime_ns)
                   == (after.st_dev, after.st_ino, after.st_mode, after.st_mtime_ns, after.st_ctime_ns)
                   and sc.same_directory(path.parent, fd), 'link_metadata_changed')
        return before, raw
    finally:
        os.close(fd)


def _target(repo, link, raw):
    # Lexical normalization only: never resolve a symlink or traverse outside root.
    root = os.fspath(repo).rstrip('/')
    absolute = posixpath.normpath(raw if raw.startswith('/') else root + '/' + posixpath.dirname(link) + '/' + raw)
    if not absolute.startswith(root + '/'):
        return None
    return canonical(absolute[len(root) + 1:])


def inspect_links(repo, projected):
    """Inspect only finite projected link paths; results and targets are PRIVATE.

    Internal-covered is a path-census observation, never target identity closure.
    Missing/unresolved entries still require disposition; nothing is traversed.
    """
    repo = Path(repo)
    sc.require(repo.is_absolute() and '..' not in repo.parts, 'absolute_repository_required')
    checked = project_paths({'entries': [{'path': r['path'], 'kind': r['kind'],
                                         **({'bytes': r['bytes']} if r['kind'] == 'file' else {})}
                                           for r in projected['entries']]})
    sc.require(checked['linked_paths'] == projected['linked_paths'], 'projection_link_mismatch')
    covered = {row['path'] for row in checked['entries']}
    result = []
    for path in checked['linked_paths']:
        row = {'path': path, 'status': 'unresolved', 'raw_target_private': None, 'target_path': None,
               'disposition': 'metadata_only_requires_explicit_disposition'}
        try:
            info, raw = _metadata(repo, path, True)
            if not stat.S_ISLNK(info.st_mode):
                result.append(row)
                continue
            row['raw_target_private'] = raw
            target = _target(repo, path, raw)
            row['target_path'] = target
            if target is None:
                row['status'] = 'outside'
            else:
                try:
                    target_info, _ = _metadata(repo, target)
                    row['status'] = ('unresolved' if stat.S_ISLNK(target_info.st_mode)
                                     else 'internal_already_covered' if target in covered else 'internal_uncovered')
                except FileNotFoundError:
                    row['status'] = 'missing'
        except (OSError, ValueError):
            pass
        result.append(row)
    return {'links': result, 'claims': contract(), 'raw_targets_private': True}


def load_projected(repo):
    """Authenticate the one existing census before/after pure projection."""
    raw = sc.bounded_read(Path(repo), CENSUS)
    sc.require(sc.sha(raw) == CENSUS_SHA, 'registered_path_census_required')
    value = sc.decode(raw)
    sc.require(value.get('status') == 'path_census_complete_not_exposure_closure'
               and value.get('research_file_bodies_opened') == 0
               and value.get('grants_sampling_download_or_inference') is False, 'path_only_census_required')
    result = project_paths(value)
    sc.require(sc.bounded_read(Path(repo), CENSUS) == raw, 'census_changed_during_projection')
    result['source_census_sha256'] = CENSUS_SHA
    return result


def inventory_metadata(repo):
    """Bound finite projection plus private link metadata to the fixed census.

    This function returns data only. It does not write or grant completeness.
    """
    raw = sc.bounded_read(Path(repo), CENSUS)
    sc.require(sc.sha(raw) == CENSUS_SHA, 'registered_path_census_required')
    projected = load_projected(repo)
    links = inspect_links(repo, projected)
    sc.require(sc.bounded_read(Path(repo), CENSUS) == raw, 'census_changed_during_link_inspection')
    return {'projection': projected, 'link_metadata_private': links,
            'source_census_sha256': CENSUS_SHA, 'claims': contract()}
