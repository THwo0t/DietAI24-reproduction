# Registered source mass discrepancy — round four

Registered on 2026-11-03, after the fixed 230 training-image downloads and before
any round-four performance result. The original preparation stopped with
`ingredient_target_total_mismatch`; no training freeze was released. Its source
SHA256 was `7a5c450dc5cc3918bb283e9a042e16db95e69ef5ee887b2f79763d525e4600a3`.
The original failure and the private diagnostic remain archived; this change
does not describe the failed attempt as a successful preparation.

The fixed candidate list has 230 distinct conservative screening groups. Blind
byte/RGB comparison found no protected or candidate collision. Independent
Decimal parsing found one mass discrepancy, while all four nutrient sums in all
230 rows satisfy the unchanged absolute tolerance of 0.001. The other 229 mass
residuals are at most 0.000016 g. All 164 training ingredient classes satisfy
the existing name and density consistency checks.

The sole exception requires all of the following exact evidence:

- Source: `Nutrition5k/metadata/dish_metadata_cafe1.csv`.
- Complete source SHA256: `881df31f27c2343d0ce219964527e0796f6ddadd60701ce6840fa801e8c2a960`.
- Complete raw CSV record SHA256, including its original line ending:
  `6924b964d0da3b5dbed4bfe055f1f9c0cac0f072fac732c46393b418ad9e5201`.
- Target: weight only; ingredient mass sum minus official dish mass must equal
  exactly `Decimal('2.000000')` g. The four nutrients retain the 0.001 tolerance.

This record has three positive-mass ingredients, without duplicate ingredient
IDs. All four displayed mass fields have six decimal places. Their combined
nearest-rounding bound is 0.000002 g, one million times smaller than the observed
2 g difference. The source fields are inconsistent; CSV evidence cannot decide
which mass is physically correct. This is not a field-offset parsing correction
or a general rounding allowance.

Keep the official five targets and every original ingredient mass unchanged.
The training fallback uses official dish targets. Few-shot examples continue to
compute their displayed total mass from original ingredient masses; for this
record that total differs from the official dish mass by the registered 2 g.
Catalogue nutrients continue to use the original ingredient amounts and the
existing density checks. No image is removed, replaced or relabelled, and no
development or validation target motivated this exception.

The audit and freeze binding record the exact policy and the actual application
count. Production preparation and verification require exactly one application;
a missing application also stops release. Synthetic fixtures independently set
their own expected count. This document is itself a frozen source input. A changed
source, changed raw record, different sign/value, second unregistered anomaly,
or any nutrient mismatch remains a hard stop. The general tolerance stays at
0.001. No claim of physical plate independence or future accuracy follows from
this data-quality exception. Real preparation/release is a separate operation.
