# I: visual boundary and portion checks on the H pipeline

Registered on 2026-11-03 before I inference. H remains immutable. This is one
prompt ablation, motivated by post-hoc inspection of six development failures
from C/F. It is development work, not independent evidence of generalization.
No validation inputs or new data downloads are used.

Keep H's exact training-fold ingredient catalogs, four G support assignments,
support order, five processed RGB images, output schema and programmatic
ingredient-density aggregation. Keep the unknown-ingredient branch, one
structural repair, persistent HTTP budget, fixed Sol/zicc model, temperature 1,
8192 completion tokens, and training-fold whole-dish median fallback.

The only inference change is a fixed paragraph added to the query instruction:

1. Identify the main serving vessel carrying the central meal. Count its food;
   exclude food belonging to adjacent plates and background vessels.
2. Treat pale color as insufficient to identify a food. Compare particle
   separation, surface continuity, porosity, sheen and shape with the allowed
   training catalog. Use the unknown branch when a catalog identity is not
   supported. Do not name a particular development food in the instruction.
3. Check each item's area together with thickness, piling and occlusion.
   A thick or dense raised portion need not have the same mass per visible area
   as a thin portion. Training photographs provide portion examples, not a
   shared plate diameter or a common pixels-to-grams scale.

Apply the same instruction to every query. Do not add per-image exceptions,
diagnostic IDs, current-query ingredient labels, reference quantities, or error
feedback. Do not introduce another recognition/crop/reasoning call. The model
still returns only the existing ingredient JSON; no chain-of-thought is stored.

Run all 84 development images / 78 groups once under the same fixed folds.
Every row enters the ten Nutrition5k checks; preserve ASA24's 99-row method.
Keep I uncalibrated. Ordinary I OOF predictions cannot train a second stage for
an outer fold without nested example/catalog generation excluding that fold.
Compare H and I as whole methods, never choose predictions per target or row.
Retain all failed and passing outputs, request usage and immutable bindings.
H must finish and pass completed-artifact integrity verification before I starts.
Choose by worst threshold ratio, then mean ratio, then simpler/fewer-call method;
formal validation stays sealed until the full development gate is satisfied.
