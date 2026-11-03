"""Prospective PRIVATE blind fingerprints; opens every census-projected image.

Closed list includes dependency and chart copies, possibly protected images.
No labels, targets, visual analysis, inference, writes, or completeness/action
permission. Public loader has a fixed repository; private hooks serve fixtures.
"""
import hashlib
import io
import os
from pathlib import Path
import stat
import warnings

from PIL import Image
import asa_content_identity as asa
import local_input_inventory as inventory
import source_census as sc

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000
RGB_ALGORITHM = 'pillow-convert-RGB-size-tuple-nul-v1'


def _signature(info):
    return tuple(getattr(info, key) for key in
                 ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))


def _read(repo, path, size):
    """No-follow regular-file read, with held descriptor and fresh path checks."""
    inventory.canonical(path)
    sc.require(type(size) is int and 0 < size <= MAX_BYTES, 'bounded_census_image_required')
    full = Path(repo) / path
    parent = sc.directory_fd(full.parent)
    try:
        fd = os.open(full.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(fd)
            sc.require(stat.S_ISREG(before.st_mode) and before.st_size == size,
                       'regular_census_size_image_required')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                raw = stream.read(MAX_BYTES + 1)
            after = os.fstat(fd)
            current = os.stat(full.name, dir_fd=parent, follow_symlinks=False)
            sc.require(len(raw) == size and _signature(before) == _signature(after)
                       == _signature(current) and sc.same_directory(full.parent, parent),
                       'image_changed_during_read')
            return raw, _signature(before)
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def _fingerprint(raw, *, allow_dependency_gif=False):
    sc.require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BYTES, 'bounded_image_bytes_required')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                sc.require(image.format in (('PNG', 'JPEG', 'GIF') if allow_dependency_gif else ('PNG', 'JPEG')), 'unsupported_image_format')
                width, height = image.size
                sc.require(width > 0 and height > 0 and width * height <= MAX_PIXELS,
                           'image_pixel_bound_exceeded')
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                mode, fmt = image.mode, image.format
                sc.require(getattr(image, 'n_frames', 1) == 1, 'animated_image_out_of_scope')
                semantics = (mode not in ('RGB', 'L', 'P') or 'transparency' in image.info
                             or bool(image.info.get('icc_profile'))
                             or getattr(image, 'n_frames', 1) != 1
                             or image.getexif().get(274, 1) != 1)
                rgb = image.convert('RGB')
                rgb.load()
                digest = hashlib.sha256(str((width, height)).encode() + b'\0' + rgb.tobytes()).hexdigest()
    except ValueError:
        raise
    except Exception:
        raise ValueError('image_decode_failed') from None
    registered = None if fmt == 'GIF' else asa.image_fingerprint(raw)['rgb_sha256']
    return {'bytes_sha256': sc.sha(raw), 'rgb_sha256': digest,
            'rgb_algorithm': RGB_ALGORITHM, 'width': width, 'height': height,
            'mode': mode, 'format': fmt, 'nontrivial_render_semantics': bool(semantics),
            'asa_compatible': registered is not None, 'asa_rgb_sha256': registered,
            'asa_algorithm': asa.ALGORITHM if registered is not None else None}


def _load_at(repo, projected):
    # Authenticate supplied projection, then freeze the complete original census.
    raw = sc.bounded_read(Path(repo), inventory.CENSUS)
    sc.require(sc.sha(raw) == inventory.CENSUS_SHA, 'registered_path_census_required')
    authenticated = inventory.load_projected(repo)
    sc.require(projected == authenticated, 'authenticated_projection_required')
    census = sc.decode(raw)
    allowed = frozenset(authenticated['image_paths'])
    frozen = tuple((row['path'], row['bytes']) for row in census['entries']
                   if row.get('kind') == 'file' and row['path'] in allowed)
    sc.require(len(frozen) == len(authenticated['image_paths']), 'finite_image_allowlist_required')
    classes = {r['path']: r['classification'] for r in authenticated['entries']}
    rows, bindings = [], []
    for path, size in frozen:
        body, signature = _read(repo, path, size)
        rows.append({'path': path, 'classification': classes[path], **_fingerprint(body, allow_dependency_gif=(
            classes[path] == 'dependency' and inventory.dependency_gif_path(path)))})
        bindings.append((path, size, signature, sc.sha(body)))
    # Reopen recorded paths and rehash fresh bytes, not the retained decode buffer.
    for path, size, signature, digest in bindings:
        body, current = _read(repo, path, size)
        sc.require(current == signature and sc.sha(body) == digest, 'image_source_binding_changed')
    sc.require(sc.bounded_read(Path(repo), inventory.CENSUS) == raw
               and inventory.load_projected(repo) == authenticated, 'census_source_binding_changed')
    return {'rows_private': rows, 'source_census_sha256': inventory.CENSUS_SHA,
            'counts': {'images': len(rows), 'asa_compatible': sum(r['asa_compatible'] for r in rows),
                       'nontrivial_render_semantics': sum(r['nontrivial_render_semantics'] for r in rows)},
            'status': 'private_blind_fingerprints_no_completeness_or_permission'}


def load_local_content_inventory(projected):
    """Open only the authenticated closed image list in the fixed repository.

    Caller supplies load_projected's result. This can open protected images;
    mechanical protection policy belongs to the prospective source audit.
    """
    return _load_at(sc.REPO, projected)
