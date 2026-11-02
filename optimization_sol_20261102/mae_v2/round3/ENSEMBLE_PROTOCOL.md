# Fixed whole-vector combinations after I completes

Registered on 2026-11-03 while I is running, before its aggregate metrics or
per-image errors are read. This is a development-only variance experiment;
validation remains sealed. No new API calls or changes to H/I are required.

Compare exactly two additional methods on all 84 Nutrition5k development rows:

- `HI_mean`: arithmetic mean of raw H and raw I for each of the five targets.
- `CHI_median`: componentwise median of raw C, raw H and raw I for all targets.

The same combiner applies to all targets and rows. Do not tune coefficients,
select a model per row/target, discard failures, or use calibrated C outputs.
Retain each member's registered complete-population fallback where applicable.
The combination is supervised-example model aggregation, not the original
single grams-times-FNDDS-density method; retain constituent outputs unchanged.
All members used no current-query labels: C is label-blind; H/I catalogs,
examples and fallbacks exclude the query's entire fold. No parameters are fit
using any development labels in these two combiners. Labels are used only
after the combined predictions have been produced and sealed.

Require completed member artifacts, external record seals, exact population,
matching frozen development inputs and the reviewed raw-C binding. Each record
contains member hashes, all five member quantities, the combined quantities,
and constituent failure states. Preserve ASA24's existing 99-row predictions.
Score all ten N5 checks and the twenty-check joint result with the existing
unrounded thresholds. A combined prediction's completeness must not conceal a
member fallback. Its deployment cost includes every upstream member call and
C's official-embedding dependencies, even though this experiment reuses them.

Choose a whole method by the existing worst-ratio / mean-ratio / simplicity
rule. These are additional development comparisons, not independent validation
or evidence that the final acceptance gate has been reached.
