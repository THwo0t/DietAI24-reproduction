# Continued development, round 3

Registered before F inference on 2026-11-03, after the user's instruction to
back up the failed v2 iteration and continue optimizing. V2 remains immutable.
No final report is produced for this intermediate iteration.

Keep all twenty paper-times-1.3 MAE limits and the exact per-unit definition.
Retain the passing ASA24 method and its existing 99-row development result.
Use all 84 active Nutrition5k development images / 78 association groups with
their existing five folds. No new data, filtered subset, or validation access.
The 200-image formal validation set remains sealed until development succeeds.

## F: independent visual nutrient estimation

F receives only the same single RGB image, aspect ratio preserved, maximum
edge 1024 without upscaling. Sol estimates visible edible food items, cooked
weights and four nutrient amounts. Programmatic summation yields the five
dish targets. A mixed dish is counted once, or exclusively through its parts.
No reference label, file identity, prior C prediction, retrieved code, or
dataset identity enters the request. This is an explicit methodological
departure from FNDDS-based nutrient aggregation, evaluated as a new candidate;
it is not called a faithful reproduction of the original pipeline.

Fixed provider: gpt-6.1-sol, zicc route, temperature 1, 8192 completion tokens.
This candidate needs no embedding requests. Any later retrieval keeps the
original official OpenAI embedding route. One ordinary request per image,
at most one structural repair, and the existing persistent three-HTTP-attempt
limit. Valid predictions are not resampled for their accuracy.

Malformed/empty/nonfinite/negative/duplicate-item output is explicit failure.
Irreparable prediction uses five componentwise training-fold medians. All 84
rows remain scored. Macro mass exceeding edible mass is an audit flag, not
an error-based exclusion or clipped answer. Preserve raw and parsed results.

The first result is F without supervised calibration. Report its five absolute
and five normalized errors, joint gates, native/repair/fallback counts and
request/token totals in a small machine-readable progress artifact. Compare
the same population with saved C. Do not choose methods independently by image
or nutrient. Later candidates and supervised postprocessing require separate
registration before their paid inference or final choice. Existing raw C
offline fitting explorations are labeled exploratory development analyses.

Source, prompt, protocol, cohort and model configuration hashes are bound
before the first request. Resume verifies existing record hashes and rejects
drift. Credentials and private rows stay local. No automatic validation or
publication command exists in this round's driver.
