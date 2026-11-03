# Separate completed-O diagnostic

This helper is outside O's frozen inference modules. It cannot fit, select,
bootstrap or send a prediction request. Do not execute on a partial batch.
The original completed scores, verification, source/input bindings and private
artifact seals must agree before any development label is opened. It uses
the existing raw/OOF outputs, not a new calibration fit. Validation is excluded.

After the same O follower reaches `development_scored`:

```bash
unshare -Urn .venv/bin/python -B optimization_sol_20261102/mae_v2/round10/postscore/guarded_diagnose_o.py
```

The wrapper forbids network/Provider/key/image/validation access and protects
earlier prepared/run/service files by size/mtime. The once-only private seal
is `round10/diagnostics/completed_o`; an existing completion refuses recompute.
Inspect its existing aggregate instead. No new predictor or threshold is chosen.

The namespace precondition parses the kernel's `/proc/self/net/dev` view and
requires exactly loopback with the complete expected header/counter format.
Shared `/sys/class/net` can retain the parent's mount view after `unshare -n`
and is therefore not used to decide namespace isolation. Actual offline
evidence caught that false refusal; malformed or additional interfaces still
refuse. This corrects only the separate diagnostic wrapper, not frozen O.

The aggregate reproduces point errors with full denominators, signed bias and
error concentration; checks standard/unit/gram accounting; and decomposes
whole-serving nutrient error into symmetric mass and density algebraic terms.
Those terms can cancel and are not additive MAE contributions or ingredient
causes. Missing component annotations prevent a true omission/duplication or
recipe-cause rate. ASA continuous-to-option diagnostics are separate from the
official conditional legal-option scores, which retain all Exact fallbacks.

The first actual diagnostic sealed its aggregate but its legacy integer-key
return comparison failed after JSON normalization. The original guard receipt
is absent. Existing completion prohibits recomputation; the future JSON-stable
output correction does not alter or recreate that artifact.

`reverify_sealed_o.py` is a separate, read-only recovery entry. After its bounded
review/fixes, run in a fresh process:

```bash
unshare -Urn .venv/bin/python -B optimization_sol_20261102/mae_v2/round10/postscore/reverify_sealed_o.py
```

It pins the original O freeze and historical diagnostic source/helper, verifies
complete O/diagnostic stores, original closed inputs and aggregate point values,
without labels, catalogue contents, images, provider responses or recomputation.
A process audit policy blocks other reads, mutations, children and socket events.
Its exclusive `evidence/postscore_guard_recovery.json` explicitly does not claim
the old guard passed or that its counters/mtime snapshot were recovered. Hash
anchors for unopened data files do not claim a new physical integrity check.
The receipt grants no permission to prepare data, sample, download or infer.

R-O-REC1-1 closes documented CPython mutation events including truncate, time,
ownership, permissions, flags and extended attributes, plus child-process and
native mapping/call paths. The event list was checked against the
[Python 3.10 audit table](https://docs.python.org/3.10/library/audit_events.html).
Fresh synthetic processes test successful receipt creation and refused label,
truncate, utime, chmod, chown and setxattr attempts, with unchanged victim bytes/
metadata and no receipt after refusal. This policy covers the trusted Python
recovery routine; it is not a general-purpose sandbox for untrusted native code.
