"""Fixed-path ASA PNG archive reader prototype, not a phase entry point.

Only a later reviewed phase runner may call this on real data, after complete O
scoring/retrospective and registered source pins. This module neither grants
that permission nor authenticates a caller-supplied expected hash. It does not
open metadata, labels, images outside the ZIP, credentials or network sources.
"""
import hashlib
import os
from pathlib import Path,PurePosixPath
import stat
import zipfile

from asa_content_identity import ALGORITHM,MAX_BYTES,png_fingerprint
from asa_identity import image_name,require,sha_value

RELATIVE='ASA24/Asa24PortionImages.zip'
MAX_ARCHIVE_BYTES=16*1024**3
MAX_MEMBERS=100000


def _open(repo):
    root=Path(repo)
    require(root.is_absolute() and root.resolve()==root,'canonical_archive_root_required')
    path=root/RELATIVE
    require(path.resolve()==path,'linked_archive_path_refused')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and 0<info.st_size<=MAX_ARCHIVE_BYTES,
                'regular_bounded_archive_required')
        return os.fdopen(fd,'rb')
    except BaseException:
        os.close(fd);raise


def _digest(stream):
    stream.seek(0);hasher=hashlib.sha256();total=0
    while True:
        block=stream.read(1024*1024)
        if not block:break
        total+=len(block)
        require(total<=MAX_ARCHIVE_BYTES,'archive_size_bound_exceeded')
        hasher.update(block)
    return hasher.hexdigest(),total


def _member(info):
    name=info.filename
    require(isinstance(name,str) and name and '\\' not in name and '\0' not in name
            and info.orig_filename==name,
            'unsafe_archive_member')
    path=PurePosixPath(name)
    require(not path.is_absolute() and all(v not in ('','.','..') for v in name.rstrip('/').split('/')),
            'unsafe_archive_member')
    mode=(info.external_attr>>16)&0xFFFF
    kind=stat.S_IFMT(mode)
    require(kind in (0,stat.S_IFREG,stat.S_IFDIR) and not info.flag_bits&1,
            'unsupported_archive_member_type')
    require(not info.is_dir() or kind in (0,stat.S_IFDIR),'inconsistent_archive_directory')
    require(kind!=stat.S_IFDIR or info.is_dir(),'inconsistent_archive_directory')
    return path.name


def capture_archive(repo,expected_sha256):
    """PRIVATE all-PNG fingerprint/member records plus an ID-free aggregate.

    Every PNG is read by its ZipInfo, retaining duplicate-member evidence. The
    exact source hash is verified before parsing and again through the same fd
    and current fixed path afterwards. No extraction or basename overwrite.
    Unsupported PNGs/CRC faults are fatal, never silently treated as missing.
    """
    expected=sha_value(expected_sha256);rows=[];members=[];by_name={};others=0
    try:
        with _open(repo) as stream:
            digest,size=_digest(stream)
            require(digest==expected,'archive_source_hash_changed')
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                infos=archive.infolist()
                require(len(infos)<=MAX_MEMBERS,'archive_member_count_bound_exceeded')
                for index,info in enumerate(infos):
                    basename=_member(info)
                    if info.is_dir() or not basename.lower().endswith('.png'):
                        others+=1;continue
                    image_name(basename)
                    require(0<info.file_size<=MAX_BYTES,'png_member_size_bound_exceeded')
                    with archive.open(info,'r') as image:
                        raw=image.read(MAX_BYTES+1)
                    require(len(raw)==info.file_size and len(raw)<=MAX_BYTES,
                            'png_member_size_mismatch')
                    fingerprint=png_fingerprint(raw)
                    require(basename not in by_name or by_name[basename]==fingerprint,
                            'conflicting_archive_basename_content')
                    by_name[basename]=fingerprint
                    rows.append({'image':basename,**fingerprint})
                    members.append({'member_index':index,'member_path':info.filename,'image':basename,
                        'bytes':len(raw),'compressed_bytes':info.compress_size,**fingerprint})
            require(_digest(stream)==(expected,size),'archive_source_changed_during_capture')
        with _open(repo) as current:
            require(_digest(current)==(expected,size),'archive_path_changed_during_capture')
    except (zipfile.BadZipFile,EOFError,NotImplementedError,RuntimeError):
        raise ValueError('archive_or_member_decode_failed') from None
    require(rows,'nonempty_png_archive_required')
    return {'image_fingerprints':rows,'members':members,'source_sha256':expected}, {
        'archive_bytes':size,'archive_members':len(infos),'png_members':len(rows),
        'unique_png_image_names':len(by_name),'duplicate_basename_members':len(rows)-len(by_name),
        'other_members':others,'algorithm':ALGORITHM,'metadata_coverage_proven':False,
        'external_exposure_completeness_proven':False,'new_samples_selected':0,'api_calls':0}
