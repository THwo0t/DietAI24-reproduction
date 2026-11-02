# G: four-image training-fold demonstrations

Registered after F completed, before any G inference, on 2026-11-03. F failed
all ten Nutrition5k checks and is retained as a negative development result.
G tests whether visually comparable labeled training images improve scale and
food-composition estimates. It is another direct-nutrient method departure,
not an original FNDDS-reproduction result.

Use the same 84 development images / 78 groups and their existing five folds.
For each query exclude its whole fold and every member of its association
group. Select exactly four remaining examples from four distinct groups.
Rank by cosine similarity of mass-weighted means of the frozen FNDDS vectors
for raw C's selected leaf codes. The mean is normalized; ties use sample ID.
Features use only the earlier label-blind C response, never reference nutrients,
error, true ingredient identity or the current query's reference weight.
No new embedding is needed. F outputs do not enter example selection.

Raw C is an upstream inference dependency, not a free input at deployment.
Future unseen images require its A-identity/total-ratio pipeline before G can
select supports; the training gallery and its labels are then fixed. Report
upstream plus G calls when comparing deployment cost. This development run
reuses already completed, sealed, label-blind C responses without rerunning them.

One request sees the four training images, each accompanied by its five true
dish totals, and the query image. Images use the same metadata-free native
encoding (maximum edge 1024). The prompt asks for independent query food-item
estimates and warns against copying the support values. Exactly the F item
schema and programmatic summation are used. Model/route/temperature/token cap
remain Sol/zicc/1/8192, with one format repair and persistent three-attempt
HTTP budget. Validation files are never read or available as examples.

Every query enters scoring. Irreparable output uses the componentwise median
of its training folds. Keep source/example hashes, all requests, parsed values,
and example membership for offline group-isolation auditing. No score-based
retry, example replacement, per-image method selection, or filtered denominator.
Compare raw G against F and preserved C on all ten fixed checks. The passing
ASA24 branch stays unchanged. Supervised calibration, if later investigated,
must not fit a second-stage model on ordinary OOF G predictions: those training
predictions can indirectly depend on the held-out fold's example labels. Use
a separately registered nested scheme or keep G uncalibrated.

Bind the original ASA OOF and C-selection hashes as well as the development
freeze, C record seal, vector manifest, protocol, inference sources and example
assignments before sending any G request. Completed external record seals are
verified before any resume or evaluation, and completion is immutable.
This intermediate experiment produces only result/progress artifacts, not
another final report. Formal validation remains sealed.
