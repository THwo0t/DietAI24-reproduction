# Mechanical source role audit entry

`round11/source_role_audit.py` is a separate fixed-root, no-argument entry. It
requires an isolated network namespace and an absent output, and writes through
the existing exclusive private artifact writer. It does not rerun the mechanical
inventory, O, image decoding, selection, fitting, downloads or inference.

The sole held mechanical artifact is
`round11/preparation/source_inventory/source_inventory.json`. Before production
use, register its actual completed receipt SHA-256 in `INVENTORY_SHA256`; the
initial `None` deliberately refuses before reading that artifact. No CLI,
environment or artifact-provided replacement anchor exists.

The entry authenticates the receipt, completed-but-unresolved status, capture
implementation pins and fixed controls. It reloads fixed N5 identity sources
and development identity, compares their bindings to the inventory, and
revalidates those readers, the held artifact, controls, implementation, fixed
ASA metadata/archive bodies and legacy manifest bodies around graph use.
It reloads the fixed ASA role reader after graph use and requires the same
projection. Referenced image and label paths are never followed.

The ASA graph consumes only held mechanical ASA and local-content identities
and the authenticated role projection. Its existing identity contract preserves
original sample, group, fold and image-hash bindings; this entry makes no fold
repair. Private graph and source projections remain in the private artifact.
Standard output contains only whitelisted aggregate counts, false grants,
unresolved status and the private artifact SHA-256.

Caller registrations, full source associations, actual API exposure and source-
backed training/retired roles remain unresolved. Supplying these components
cannot close the audit. Eligibility, sampling, new downloads, inference and O
replay remain unauthorized and false, with zero action counters.

Synthetic verification (no actual inventory or data opened):

```sh
unshare -Urn .venv/bin/python -B -m unittest discover \
  -s optimization_sol_20261102/mae_v2/round11 -p test_source_role_audit.py
```

The fixture hook `_audit_at` is private and does not change production CLI
behavior. Tests cover receipt/control/source/implementation drift, stale held
snapshot, identity poisoning, false grants, unresolved success, output freshness,
CLI overrides and missing receipt registration. Component graph/reader tests
remain responsible for their detailed identity and topology contracts.

## Registered mechanical receipt

The completed inventory SHA-256 is now fixed as
`203bbb7c9f26f2bf6a4bf3846151fe068c3399f61efbb3f1a0b41c830dc9892d`.
The original one bounded entry review atd45b970 approved its logic with zero
findings; only the declared receipt constant is registered afterward. Root
confirmed all seven synthetic entry tests again. This does not change any
non-grant, source declaration, cohort boundary or scientific result.
