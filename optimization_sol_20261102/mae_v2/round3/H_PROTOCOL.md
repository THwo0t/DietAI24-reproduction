# H: training-only ingredient density with visual demonstrations

Registered before H inference on 2026-11-03. This extends G's four-image
training-fold demonstration pipeline with a supervised domain ingredient
catalog. It does not revise G or claim equivalence to original FNDDS retrieval.

Keep the same fixed 84 images / 78 groups, all five folds and all ten N5 checks.
ASA24 remains unchanged. All validation inputs stay sealed. No new downloads.

Use exactly G's label-blind four-example assignment from raw C features.
Exclude the query fold and group before constructing either the gallery or
catalog. The catalog is pooled only from ingredient metadata of the remaining
development groups. Its entries contain ID, name and four per-100-g densities;
do not expose dish-to-ingredient associations except for the four explicitly
chosen training images. No current-query reference field enters a request.

A request contains the training-only catalog, four supporting images with
their actual ingredient IDs and masses, then the query image. The supporting
ingredient records must be members of that training catalog; reference totals
are computed from those masses and catalog densities. The model predicts a
flat, non-overlapping list of query edible ingredients and their grams. Known
ingredient nutrients are computed by code, never replaced by model numbers.
The catalog is incomplete: allow unknown ingredients with explicit model-
estimated energy/fat/carbs/protein density per 100 g. Do not force an absent
food into the nearest listed class. Do not add ingredients from query labels,
omit unknown foods, or interpret missing catalog entries as zero nutrients.

Up to 20 unique item IDs; each has a nonempty description, positive grams,
and either an allowed catalog ingredient ID with null estimated density or
null ingredient ID with all four finite nonnegative estimated densities.
Duplicate ingredient IDs across different visible portions are permitted;
items must not overlap. Macro mass inconsistencies are audit flags. One main
Sol/zicc request plus at most one structural repair, temperature 1 and 8192
completion tokens; existing durable three-attempt HTTP rule. No embeddings
are generated: C features reuse the frozen official embeddings.

Failure uses the whole-dish five-target training-fold median, keeping all 84
rows. Record unknown ingredient count/mass fraction, failures, repairs, and
all-source hashes. Unknown count and residuals cannot trigger accuracy retries.
Raw H is compared with G/F/C as a single whole-dish method, never per-target
or per-image switching. H ordinary OOF outputs cannot safely train second-
stage calibration without a nested example-generation scheme. Keep H raw.

The lookup adapter may stream and hash mixed original metadata files, but
only parses numeric ingredient fields for the pre-existing 84 development
IDs. Full per-image ingredient records remain private and unavailable to the
prediction interface. The future validation catalog/gallery would be built
once from all development groups, never from validation annotations.
