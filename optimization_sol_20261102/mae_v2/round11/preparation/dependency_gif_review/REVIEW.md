# Finite dependency GIF delta review

Date: 2026-11-04. Reviewer: independent Codex `gpt-6.1-sol` agent.
Decision: **approved**. No P1, P2 or P3 findings in the bounded delta.

## Scope and design basis

One review of commit `8057af2` against its parent, limited to
`local_input_inventory.py`, `local_content_inventory.py`,
`n5_potential_identity.py`, their three test modules, and
`preparation/DEPENDENCY_GIF_IDENTITY.md` under this round11 directory.
Read repository `AGENTS.md` first. This is a supplement-contract review;
the already reviewed ASA V3 implementation and the wider project were not
reviewed again. The design basis is the supplement, especially lines 3–6,
18–28 and 36–40, rather than a new paper-method claim.

## Evidence

- Exact finite paths: `local_input_inventory.py:32–47` enumerates the root
  runtime plus four named delivery copies and the four exact Tk/IDLE
  directories. Canonical relative paths and exact remainder dirname prevent
  unrelated roots, traversal and nested-directory admission. This implements
  supplement lines 18–22; `test_local_input_inventory.py:82–94` exercises the
  five-by-four grid and rejected near misses.
- Private loader gate: `local_content_inventory.py:88–104` authenticates the
  projection and combines dependency classification with the exact predicate.
  Default format admission remains PNG/JPEG at line 61. GIF reaches neither
  ASA fingerprinting nor ASA compatibility (`local_content_inventory.py:80–85`),
  matching supplement lines 3–6 and 21–27. The synthetic ASA-call trap and
  twenty-path retention checks are at `test_local_content_inventory.py:95–109`.
- Static bounded identity: `local_content_inventory.py:55–75` retains byte and
  pixel bounds, verify, single-frame rejection and full RGB loading; lines
  75–85 retain N5 size-tuple/NUL/RGB and byte digests. Fresh binding checks
  remain at lines 105–111. GIF negative-path tests at
  `test_local_content_inventory.py:111–128` cover unrelated paths, byte/pixel
  limits and animation. This matches supplement lines 23–25.
- Overlay: `n5_potential_identity.py:70–84` independently requires the exact
  dependency path/classification for GIF, false ASA compatibility, null ASA
  metadata and valid digests. Existing verbatim rows, byte/RGB fixed-point
  bridges, all aliases and unassigned rows remain at lines 87–107 and
  128–130. `test_n5_potential_identity.py:86–105` verifies GIF aliases across
  all five roots and rejects invalid path/classification/ASA/digest/target
  rows. This matches supplement lines 25–28.
- No source or action closure: `local_input_inventory.py:50–53`,
  `local_content_inventory.py:112–115`, and
  `n5_potential_identity.py:23–26,128–137` retain explicitly provisional
  status/non-grants. Supplement lines 36–40 explicitly withhold capture and
  future action permission.

## Offline verification

From the round11 directory, ran exactly:

```sh
unshare -Urn /home/lelouch/Data/Projects/DietAI24_original/.venv/bin/python -B -m unittest -v test_local_input_inventory test_local_content_inventory test_n5_potential_identity
```

Result: **55 tests passed**, exit status 0. The count includes inherited and
imported synthetic lineage tests; it is not a count of new GIF tests. Network
was isolated by the user/network namespace. Fixtures use temporary synthetic
files and generated images only. No actual research data, census artifact,
project image, label, credential or `.env` body was opened; no download or API
call was made. The coordinator-supplied real preflight counts and cancellation
history in supplement lines 8–16 and 37–38 were not independently reproduced.

Only this review file was created. Approval is confined to the code/design
delta and synthetic validation; it grants no capture retry, source closure,
eligibility, sampling, download, inference, freeze or paid action.

## Implementation disposition and root confirmation

The one bounded review is approved without findings. Root independently ran
the then-current complete suite under `unshare -Urn` with `.venv/bin/python -B`: 
323 distinct unittest IDs passed (34.649 seconds; inherited regressions included).
No scientific output or action grant is inferred. The separately authorized
mechanical inventory is proceeding with source/role closure and cohort actions
still pending; original O and old manifests are unchanged.
