# Prospective failure handling for the paired quantity/density comparison

This records the failure rule before any Q/D requests. It supplements the
successful-path comparison in DESIGN.md; no paid run or accuracy claim follows.

Use the predeclared training-fold five-target median whenever a Nutrition5k
profile cannot produce its complete native prediction after one structural
repair. Identity failure therefore sends all four profiles to the same median.
Original-quantity failure sends O and D to that median; Q failure sends Q and
Q+D to it; density-choice failure sends D and Q+D to it. Failures of an
intervention do not alter its unaffected control. Record every failed stage,
repair and whole-dish fallback; retain every observation in primary scoring.

Exact O/D and Q/Q+D physical-weight equality is required when both members of
that pair have successful native or repaired predictions. With a whole-dish
fallback the manipulation check is unavailable, and that status is reported.
Do not replace a successful control or reuse a successful stage as an undeclared
fallback just to force equality. This explicitly narrows DESIGN.md's
unconditional manipulation-check wording on failure branches; the complete
scoring population and training-fold-only median rule take precedence there.

Each successful parsed stage is validated again, including its fixed item IDs,
code membership, complete finite numeric values and quantity normalization.
Malformed objects declared successful are contract errors, not silent native
successes. Stage states are native, repaired or failed; the runner must enforce
the one-repair limit and authenticate the supplied median's training-fold source.
The pure composition module checks its binding format but cannot prove source
authenticity. Full runner review and freeze remain mandatory before use.

ASA24 still uses its isolated legal-option adapter and its registered per-code
median legal-option failure rule. Nutrition5k whole-dish medians must not be
substituted into ASA24 option scoring.
