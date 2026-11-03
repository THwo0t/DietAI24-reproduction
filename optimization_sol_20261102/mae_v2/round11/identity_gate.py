"""Next-phase verified identity loader; never installed into the running O.

The caller supplies the actual frozen ArtifactStore and ledger. This wrapper
retains the original full semantic proof at build/restart/terminal audit, while
each cached use verifies exact dependency contents and admission projection.
"""
from copy import deepcopy
from pathlib import Path
import stat
import sys

BASE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(BASE),str(BASE/'src'),str(BASE/'round7/src'),str(BASE/'round8/src'),str(BASE/'round10')]
from opt_provider import fingerprint
from stores_o import name,verify_proof
from service_o import slot_id
from verified_identity import VerifiedIdentitySnapshot,checked_file,identity_projection


def build_loader(ctx,ledger,store,*,data_root):
    root=Path(data_root)
    if root.resolve()!=root or not root.is_absolute():raise ValueError('snapshot_absolute_data_root_required')
    sealed=store.verify_completed()
    original_proof=deepcopy(sealed['service-proof'])
    # Freeze the entire identity slot universe, including previously unreachable
    # select/embed/repair slots; none may be appended after coding is sealed.
    slots={sid for sid,meta in ledger.slots.items()
           if meta['stage'] in ('identify','select') or meta['role']=='embedding'}
    hashes=set(original_proof['bindings'].values())
    imports=deepcopy(ctx.imports)
    def child(base,relative):
        relative=Path(relative)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('snapshot_relative_dependency_required')
        return base/relative
    dependency_paths={child(root,path) for path in ctx.binding['source_files']}
    dependency_paths.update(child(root,row['image_path']) for row in ctx.rows)
    dependency_paths.update(ledger.path(path) for path in original_proof['files'])
    dependency_paths.update(child(root,path) for path in imports['source_files'])
    dependency_paths.update(child(root.parent,path) for path in imports['legacy']['source_files'])

    def evidence():
        ctx.verify_sources()
        directory=store.directory
        if directory.resolve()!=directory or directory.is_symlink():raise ValueError('snapshot_identity_directory_changed')
        files=set(dependency_paths);directories=[]
        for path in directory.rglob('*'):
            if path.resolve()!=path or path.is_symlink():raise ValueError('snapshot_identity_tree_alias')
            if path.is_file():files.add(path)
            elif path.is_dir():directories.append((path.relative_to(directory).as_posix(),stat.S_IMODE(path.stat().st_mode)))
            else:raise ValueError('snapshot_identity_tree_nonregular')
        contents={str(path):{'sha256':checked_file(path),'mode':stat.S_IMODE(path.stat().st_mode)}
                  for path in sorted(files)}
        state=ledger.read()  # Preserve the full existing admission validation.
        return {'science_binding':fingerprint(ctx.binding),'manifest_rows':fingerprint(ctx.rows),
            'catalog':fingerprint(ctx.catalog),'ledger_binding':ledger.binding,
            'allowed_slots':fingerprint(ledger.slots),'parser_sha256':ledger.parser_sha256,
            'import_bundle':fingerprint(ctx.imports),'identity_files':contents,
            'identity_directories':sorted(directories),
            'admission_identity_projection':identity_projection(state,slots,hashes)}

    def full_verify():
        records=store.verify_completed()
        if records.get('service-proof')!=original_proof:raise ValueError('snapshot_identity_proof_changed')
        verify_proof(ledger,original_proof)
        state=ledger.read()
        for sid in slots & set(state['bindings']):
            meta=ledger.slots[sid]
            if meta['role']=='chat' and meta['ordinal']==1:
                initial=slot_id(meta['sample_id'],meta['stage'],0)
                if initial not in state['repairs']:raise ValueError('snapshot_identity_repair_authorization_missing')
        for sid,proof in state['repairs'].items():
            if sid not in slots:continue
            h=state['bindings'].get(sid)
            if h is None:raise ValueError('snapshot_identity_repair_without_initial')
            cache=ledger.target(h)['cache']
            if cache is None:raise ValueError('snapshot_identity_repair_without_answer')
            raw=cache['value'];error=ledger.task_gate().format_error(sid,raw)
            if (error is None or proof!={'raw_hash':fingerprint(raw),'error':error,
                                        'parser_sha256':ledger.parser_sha256}):
                raise ValueError('snapshot_identity_repair_not_actual_parser_failure')
        identities={row['sample_id']:records[name('identity',row)] for row in ctx.rows}
        if len(identities)!=len(ctx.rows):raise ValueError('snapshot_identity_population_changed')
        return identities,{'complete':True,'identity_records_sha256':fingerprint(identities)},evidence()

    return VerifiedIdentitySnapshot.verify(full_verify,evidence)
