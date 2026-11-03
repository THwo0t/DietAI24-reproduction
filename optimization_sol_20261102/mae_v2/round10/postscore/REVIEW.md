# Completed-O post-score diagnostic: one-pass bounded review

Reviewed commit `3c06416c03e42433884a9dadec0f035f266f4b65` and its four new `round10/postscore` files. This is a review of the separate diagnostic only, not a second O scientific review. Existing O review/freeze files were not modified.

## Decision: changes requested

### R-O-D-1 — P2: make read access fail closed outside the experiment root

Evidence: `guarded_diagnose_o.py:37-47`, particularly line 46. Read allowlisting applies only when the resolved path is inside `d.ROOT`; every external file otherwise passes unless its basename/extension happens to match the short denylist. For example, an external synthetic `credentials.json`, `.env.local`, `val.jsonl`, or `.tiff` file would pass this check without increasing `forbidden`. The `validation_opened: false`/key/image boundary therefore is not enforced for external paths, despite the promise in `README.md:15-16`. This matters to the requested guard independently of whether the present diagnostic happens to request such a path; no actual credential, image, validation file, or diagnostic entry point was opened to establish it.

Required fix: apply an explicit read allowlist globally, with only the minimal non-experiment runtime paths needed by this operation permitted, rather than treating all paths outside ROOT as safe. Include synthetic negative checks for external credential/validation/image paths, including names not covered by the existing suffix list. Keep these checks isolated from real data and credentials.

No P1 findings. No additional P2 or P3 findings.

## Reviewed behavior and limits

- The incomplete-batch/followup/zero-Provider replay prerequisites precede label opening (`diagnose_o.py:27-44,105-106`); source/population bindings and completed identity/development/scoring seals are checked before the label hook (`117-143`). No fit, profile-selection execution, new prediction request, or bootstrap operation occurs in the diagnostic; `evaluate(..., bootstrap=0)` recomputes point statistics only (`148-153`).
- The reused `mass_density` function uses the exact symmetric identity `(Wp-Wt)*(Dp+Dt)/2 + (Dp-Dt)*(Wp+Wt)/2 = Wp*Dp-Wt*Dt`, checks the residual, and reports excluded nonpositive-weight rows. The output and README explicitly avoid additive-MAE or ingredient-cause claims.
- Physical accounting reconstructs the saved standard, adjusted-unit, or direct-gram choices and replays only deterministic parsing/aggregation, comparing quantities, leaves, totals and E2E consistency (`physical_audit`, lines 47-86). The reused parser uses exact standard grams, `count * grams_per_unit`, and restricts direct grams to its declared state. This accounting concerns raw physical outputs; OOF mass diagnostics are separately reported.
- ASA continuous-to-option diagnostics exclude conditional fallbacks only from that separate continuous comparison and preserve the official primary summary including fallbacks (`conditional_projection`, lines 89-105).
- The wrapper blocks the named Provider/credential constructors and sockets, requires an external-network-free namespace, restricts ordinary write opens, and checks prior prepared/run/provider file size/mtime after successful execution. Those are static findings; the actual wrapper and completed-data diagnostic were intentionally not executed.

## Offline validation

Ran exactly the existing five synthetic tests in an isolated network namespace:

```text
unshare -Urn .venv/bin/python -B -m unittest discover -s optimization_sol_20261102/mae_v2/round10/postscore -p test_diagnose_o.py -v
Ran 5 tests in 0.005s — OK
```

These cover partial/followup/replay refusal before labels, standard/adjusted-unit replay and tamper refusal, a hand-computed mass/density identity, and continuous/legal-option separation. They do not exercise the wrapper's access guard. No paid API, real label/image/per-sample output, validation-set access, O runtime entry point, restart, or interruption was used. Only this review file was created by the reviewer; pre-existing unrelated worktree changes were left alone.

## Coordinator response — R-O-D-1 fixed

Read access is now allowlisted globally. Unregistered paths outside the
experiment are denied, regardless of extension or basename; no broad runtime
directory permission is needed after the imports. Unknown integer file
descriptors are also rejected; only descriptors opened through the checked
wrapper can be passed to fdopen. Write access remains restricted to the new
diagnostic and its guard receipt. Additional image suffixes are denied even
inside an otherwise allowed tree.

Coordinator negative checks use only synthetic paths: external credentials.json,
.env.local, val.jsonl, TIFF, AVIF and an arbitrary binary path all refuse both
read and write. An allowed source is readable but unwritable; the query-label
path refuses before its hook and permits after; a diagnostic JSON write permits
but a diagnostic TIFF write refuses. All6 unique synthetic tests pass offline.
No actual guard/diagnostic entrypoint, images, query labels, keys or API were
used for this fix confirmation. Status: fixed; no second formal review.
