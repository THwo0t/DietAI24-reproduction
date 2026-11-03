"""Next-phase in-process memo: full proof once, exact evidence every use.

Not wired into frozen O. A frozen integration must supply a full verifier and
a read-only evidence collector covering content hashes, source/slot/import
bindings and the exact identity-related admission projection. No disk boolean,
mtime shortcut, automatic refresh or Provider is implemented here.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,
                                    separators=(',',':')).encode()).hexdigest()


def checked_file(path):
    path=Path(path)
    if not path.is_absolute() or path.resolve()!=path or path.is_symlink() or not path.is_file():
        raise ValueError('snapshot_regular_unaliased_file_required')
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
    return h.hexdigest()


def identity_projection(state,slots,payload_hashes):
    """Unrelated legal quantity appends do not invalidate the frozen identity."""
    bindings={sid:state['bindings'][sid] for sid in slots if sid in state['bindings']}
    reservations=[r for r in state['reservations'] if r['payload_hash'] in payload_hashes]
    ids={r['id'] for r in reservations}
    return {'bindings':bindings,'reservations':deepcopy(reservations),
            'outcomes':{rid:value for rid,value in state['outcomes'].items() if rid in ids},
            'repairs':{sid:deepcopy(proof) for sid,proof in state.get('repairs',{}).items() if sid in slots}}


class VerifiedIdentitySnapshot:
    def __init__(self,*args,**kwargs):
        raise TypeError('use_full_verify_factory')

    @classmethod
    def verify(cls,full_verifier,current_evidence):
        """full_verifier returns (identities, proof, exact verified evidence).

        Both callables are part of the next frozen trusted runtime, never API
        or user-supplied claims. current_evidence must recompute file contents
        and projection and enforce normal source, path and admission validation.
        """
        if not callable(full_verifier) or not callable(current_evidence):
            raise TypeError('snapshot_verifiers_required')
        identities,proof,evidence=full_verifier()
        if (not isinstance(identities,dict) or not identities or not isinstance(proof,dict)
                or proof.get('complete') is not True or not isinstance(evidence,dict) or not evidence):
            raise ValueError('complete_verified_snapshot_required')
        if evidence!=current_evidence():raise ValueError('snapshot_drift_during_full_verify')
        out=object.__new__(cls)
        out._identities,out._proof,out._evidence=deepcopy(identities),deepcopy(proof),deepcopy(evidence)
        out._fingerprint=digest([identities,proof,evidence])
        out._full_verifier,out._current_evidence=full_verifier,current_evidence
        return out

    def load(self):
        if digest([self._identities,self._proof,self._evidence])!=self._fingerprint:
            raise ValueError('snapshot_memory_mutated')
        if self._current_evidence()!=self._evidence:
            raise ValueError('snapshot_dependency_changed')
        return deepcopy(self._identities),deepcopy(self._proof)

    def revalidate_full(self):
        """Full terminal check; cannot silently replace a stale snapshot."""
        expected=self.load()
        identities,proof,evidence=self._full_verifier()
        if (identities,proof)!=expected or evidence!=self._evidence:
            raise ValueError('snapshot_full_revalidation_changed')
        if evidence!=self._current_evidence():raise ValueError('snapshot_terminal_dependency_changed')
        return deepcopy(identities),deepcopy(proof)
