# DietAI24 Reproduction Report

Reference: *DietAI24*, Communications Medicine 5, 458 (2025), [doi:10.1038/s43856-025-01159-0](https://doi.org/10.1038/s43856-025-01159-0). The reproduction starts from the authors' released code (v1.0-paper; repository baseline `5946365`).

## Summary

**The supplementary model comparison was motivated by the withdrawal of GPT-4 Turbo service.** The original model was unavailable when this reproduction was performed on 27 October 2026: requests to `gpt-4-turbo` and `gpt-4-turbo-2024-04-09` returned HTTP 404 deprecation errors (CHECKLIST A3). We therefore used `gpt-4o-2024-08-06` for the primary reproduction, then added a comparison with `gpt-6.1-sol` to assess how sensitive the remaining MAE gap was to the replacement model.

Both runs used the same 150 ASA24 records and 150 Nutrition5k dishes. Prompts, parsing, retrieval index and evaluation were fixed between them; necessary differences in supported model parameters are documented below. Each configuration had one formal test run.

The Sol configuration reduced Nutrition5k weight underestimation: on 79 dishes completed by both models, weight MAE decreased from **96.0 to 62.2 g**. Energy MAE did not improve, changing from **126.9 to 131.8 kcal**. ASA24 Exact matches decreased from **21 to 11**; its lower MAE estimates were based on a smaller conditional subset. These results support a partial improvement in weight estimation, while leaving much of the nutritional error unexplained.

## 1. Study design

### 1.1 Pipeline and data

Published code was retained where available, missing components were reconstructed from the paper, and explicit conflicts were resolved in favor of the paper. The pipeline:

1. Resizes each image to 256 × 256 pixels and generates a food description.
2. Generates multiple textual queries and retrieves FNDDS candidates from the same persisted index of 5,624 food descriptions, embedded with `text-embedding-3-large`.
3. Selects food codes using the image and retrieved candidates.
4. Estimates ASA24 portion options and amounts, or grams for each identified Nutrition5k food.
5. Converts grams to nutrients using FNDDS values per 100 g. For a Nutrition5k food with several candidate codes, nutrient densities are averaged before summing foods.

Each image is processed independently, without carrying earlier images or answers into later requests. Reference labels are excluded from inference except for the explicitly conditional ASA24 protocol described below.

| Dataset | Reproduction sample | Paper sample | Sampling frame |
|---|---|---|---|
| ASA24 | 150 records: 50 codes × three portion sizes | 3,000 images: 1,000 codes × three sizes | 50 codes sampled with a fixed seed from 284 eligible high-frequency codes with exact portion-code mappings and three distinct weights |
| Nutrition5k | 150 dishes | 1,000 dishes | Fixed-seed sample from 1,906 eligible overhead-image dishes, all from Cafe 1, after ingredient-set deduplication and exclusion of missing nutrient labels |

Development data comprised 10 ASA24 records and 10 Nutrition5k dishes, separate from the test sets; ASA24 development codes were also separate. Image resizing uses bicubic interpolation without preserving aspect ratio; ASA24 transparency is retained.

ASA24 contains **117 distinct photographs among the 150 records**. A portion photograph can be associated with several food codes. Reference weight is the metadata multiplier times the matching FNDDS portion weight. These properties limit how well the image alone identifies its assigned code and complicate uncertainty estimates.

### 1.2 Evaluation

- **MAE per dish** is mean absolute prediction error. **MAE per unit** is MAE divided by the mean reference value over the same valid observations, following Tables 1–2. The targets are weight, energy, fat, carbohydrate and protein.
- **ASA24 conditional protocol:** nutrition is evaluated only when the predicted codes contain the reference code (`FoodCodeCommon`). Portion options and nutrient density then use that reference code, so nutritional error reflects portion estimation. The main *option* reading uses the selected portion's weight. The secondary *amount* reading uses the predicted number of units times unit weight. This conditional interpretation follows the released code's data flow; the paper does not explicitly state the MAE inclusion rule.
- **Nutrition5k:** the main analysis includes only complete dishes: at least one identified food, valid grams for every identified item, and a valid FNDDS code for every item. Partial-dish estimates remain available as secondary results.
- **Recognition:** Exact means the full code matches; Close means the first two digits match; Far means the first digit matches. Close includes Exact, and Far includes Close, following the cumulative interpretation of Table 3. *Any* uses the best match among predicted codes; *first* uses only the first. Their denominator is records with a code output.
- **Success rates** measure whether the required code or portion output was produced, regardless of correctness. Invalid options, unreadable numbers, missing codes and unestimated items remain failures. They are not converted into successful zero-error observations.
- **Portion classification accuracy** compares the selected option with the reference option. Unit error compares the predicted amount with the reference number of units; unreadable amounts are excluded from that error and separately counted as failures.

The supplementary ASA24 end-to-end analysis uses predicted codes without reference-code conditioning. Its results remain in the saved metrics and are not expanded here. Size-specific, amount-based and partial-dish results are also retained in the original metric files.

### 1.3 Replacement models and necessary parameter differences

The paper used GPT-4 Vision-Preview and GPT-4 1106-Preview (GPT-4 Turbo), with temperature 0. Both text and vision steps were replaced together in this reproduction.

| Setting | Primary reproduction: GPT-4o | Supplementary comparison: Sol |
|---|---|---|
| Model identifier | `gpt-4o-2024-08-06` | `gpt-6.1-sol` |
| Temperature | 0 | 1, because 0 was rejected |
| Description token limit | `max_tokens=200` | `max_completion_tokens=4096` |
| Portion token limit | `max_tokens=600` | `max_completion_tokens=600` |
| Multi-query / code-selection limit | No explicit cap | No explicit cap |
| Reasoning effort | Not applicable | Unspecified; documented default medium |

Sol rejected `max_tokens`. With the replacement parameter but the original 200-token description limit, one development response spent its entire budget on reasoning and returned no text. Only its description limit was therefore increased to 4096. The final development run had 92 successful chat responses, all nonempty and normally completed, before the formal test.

All other inputs and inference logic were held fixed, including the development-approved prompt adaptations in Section 4. The comparison evaluates **replacement models with their necessary supported settings**. Because temperature and the description budget also changed, their effects cannot be separated from model capability. Sol's token limits include reasoning as well as visible output; each run is one realization of model responses.

## 2. Results

### 2.1 Output success, recognition and portions

| Metric and denominator | GPT-4o | Sol | Paper reference |
|---|---|---|---|
| ASA24: code output / all 150 rows | 83.3% | 100.0% | 84–93% across sizes |
| ASA24: valid portion option / Exact rows | 100% (21/21) | 100% (11/11) | — |
| ASA24: readable amount / Exact rows | 95.2% (20/21) | 100% (11/11) | — |
| ASA24: portion classification accuracy | 42.9% (9/21) | 27.3% (3/11) | 74.3% |
| ASA24: mean absolute unit error | 0.369 (n=20) | 0.398 (n=11) | 0.55 units |
| Nutrition5k: code output / all 150 dishes | 85.3% | 100.0% | 98.9% |
| Nutrition5k: all items have grams / dishes with codes | 73.4% | 78.7% | 84.2% |
| Nutrition5k: items with grams / identified items | 83.3% | 84.5% | 80.5% |

ASA24 matching levels are shown below. Close and Far are cumulative. The paper's GPT-4 Turbo Exact rates range from 22.1% to 29.1% across portion sizes; those size-specific rates are not a pooled estimate directly equivalent to the totals below.

| Model | Reading | Rows with codes | Exact count (%) | Close | Far | Mismatch |
|---|---|---|---|---|---|---|
| GPT-4o | any | 125 | 21 (16.8%) | 49.6% | 61.6% | 38.4% |
| GPT-4o | first | 125 | 18 (14.4%) | 49.6% | 60.8% | 39.2% |
| Sol | any | 150 | 11 (7.3%) | 43.3% | 59.3% | 40.7% |
| Sol | first | 150 | 11 (7.3%) | 43.3% | 59.3% | 40.7% |

Across all 150 ASA24 records, Exact coverage fell from **21/150 (14.0%) to 11/150 (7.33%)**, despite increased code-output success. Sol retained 10 of GPT-4o's Exact records, lost 11 and gained one. Producing more codes therefore did not improve exact identification.

Among records with codes but no Exact match, the reference code was absent from the final retrieved candidates in 95/104 GPT-4o cases and 127/139 Sol cases. It was retrieved but not selected in the remaining 9 and 12 cases. These diagnostic denominators differ because GPT-4o produced no code for 25 records. Predictions associated with the same photograph under another code occurred in 31 and 32 non-Exact cases, respectively. These counts locate retrieval and selection failures without establishing a unique cause for every error.

For Nutrition5k, GPT-4o provided grams for 190/228 identified items. Its 38 missing items were classified by the retained heuristic as 20 combined names split into components, 14 other renamings or splits/merges, three nonnumeric “Not visible” responses and one whole-response refusal. Another 10 items had grams but no valid food code. Sol provided grams for 175/207 items; its 32 unmatched items occurred in 32 dishes and were classified as 30 combined-name splits and two other renamings. It had no whole-response gram refusal or item with grams but no valid food code. These name-based categories are approximate; the item-level records are preserved.

### 2.2 Main MAE estimates and comparison with the paper

Each result cell is **MAE per dish / MAE per unit**. Values are rounded; full-precision results are retained in the comparison JSON. ASA24 uses the main option reading; Nutrition5k uses complete dishes. The two models' successful subsets differ, so their MAEs combine prediction differences with changes in sample composition. Paper values are reference points from larger samples, not estimates on the same evaluated records.

| Dataset | Target | n: GPT-4o / Sol | GPT-4o | Sol | Paper: Tables 1–2 |
|---|---|---|---|---|---|
| ASA24 | Weight (g) | 21 / 11 | 92.65 / 0.4726 | 59.68 / 0.3265 | 49.4 / 0.348 |
| ASA24 | Energy (kcal) | 21 / 11 | 92.99 / 0.3877 | 71.19 / 0.3548 | 47.7 / 0.196 |
| ASA24 | Total Fat (g) | 21 / 11 | 3.607 / 0.3516 | 2.014 / 0.3549 | 1.8 / 0.174 |
| ASA24 | Carbohydrate (g) | 21 / 11 | 11.92 / 0.4129 | 11.32 / 0.3722 | 6.95 / 0.208 |
| ASA24 | Protein (g) | 21 / 11 | 3.542 / 0.4096 | 2.182 / 0.2921 | 1.38 / 0.233 |
| Nutrition5k | Weight (g) | 86 / 118 | 95 / 0.4062 | 69.42 / 0.271 | 45.1 / 0.156 |
| Nutrition5k | Energy (kcal) | 86 / 118 | 123 / 0.4227 | 124.6 / 0.3993 | 68.2 / 0.197 |
| Nutrition5k | Total Fat (g) | 86 / 118 | 7.69 / 0.5183 | 8.99 / 0.5643 | 4.01 / 0.226 |
| Nutrition5k | Carbohydrate (g) | 86 / 118 | 11.86 / 0.494 | 13.3 / 0.5214 | 5.98 / 0.212 |
| Nutrition5k | Protein (g) | 86 / 118 | 9.907 / 0.5285 | 10.71 / 0.5307 | 3.88 / 0.188 |

The ASA24 estimates use 21 records from 10 codes for GPT-4o and 11 records from nine codes for Sol. The Nutrition5k analyses use 86 and 118 complete dishes, respectively. Secondary ASA24 amount estimates and Nutrition5k partial estimates are not substituted for these main results.

## 3. Supplementary model-substitution comparison

### 3.1 Shared subsets and paired intervals

To reduce the effect of changing successful subsets, the paired analysis uses the **same 10 jointly Exact ASA24 records from eight codes**, and the **same 79 jointly complete Nutrition5k dishes**. Each target uses identical valid records on both sides. ASA24 nutrient density is identical within each paired record, leaving portion predictions as the source of its nutritional differences. Nutrition5k food decompositions and code choices can still differ between models.

Intervals are percentile intervals from 10,000 paired bootstrap replicates, seed 20261027. ASA24 resamples the 50 sampled codes as groups, retaining all their portion sizes and failures; Nutrition5k resamples dishes. The same draws feed both models. Differences are **Sol minus GPT-4o**; negative MAE differences favor Sol. These intervals condition on the observed responses, exclude model-response randomness and uncertainty in the paper's estimates, and do not model photographs shared across ASA24 codes. One ASA24 replicate had no usable paired estimate and was explicitly excluded; Nutrition5k had none.

| Dataset | Target | Shared n | GPT-4o: MAE / per unit | Sol: MAE / per unit | Difference in MAE | Paired 95% interval |
|---|---|---|---|---|---|---|
| ASA24 | Weight (g) | 10 | 102.3 / 0.525 | 59.4 / 0.3049 | -42.88 | [-88.15, 0.75] |
| ASA24 | Energy (kcal) | 10 | 101.2 / 0.4656 | 74.87 / 0.3446 | -26.31 | [-71.24, 18.01] |
| ASA24 | Total Fat (g) | 10 | 2.897 / 0.4646 | 2.21 / 0.3544 | -0.6872 | [-3.437, 1.112] |
| ASA24 | Carbohydrate (g) | 10 | 14.99 / 0.4601 | 11.57 / 0.3552 | -3.417 | [-10.5, 2.99] |
| ASA24 | Protein (g) | 10 | 4.108 / 0.5015 | 2.374 / 0.2899 | -1.734 | [-5.373, 0.159] |
| Nutrition5k | Weight (g) | 79 | 96.01 / 0.4048 | 62.24 / 0.2624 | -33.77 | [-48.92, -19.66] |
| Nutrition5k | Energy (kcal) | 79 | 126.9 / 0.4286 | 131.8 / 0.4454 | 4.976 | [-28.25, 40.39] |
| Nutrition5k | Total Fat (g) | 79 | 7.969 / 0.5299 | 9.435 / 0.6274 | 1.465 | [-0.9601, 3.879] |
| Nutrition5k | Carbohydrate (g) | 79 | 12.27 / 0.4912 | 13.66 / 0.5471 | 1.396 | [-1.779, 4.893] |
| Nutrition5k | Protein (g) | 79 | 10 / 0.5349 | 10.06 / 0.5377 | 0.05324 | [-1.73, 1.792] |

On the shared ASA24 records, both models classified 3/10 portions correctly, with the same record-level pattern of correct and incorrect choices. Their observed accuracy difference and conditional bootstrap interval are both zero. This does not establish equivalence in the population or across repeated model calls.

### 3.2 Weight underestimation in Nutrition5k

Signed error is predicted minus reference weight; a negative value indicates underestimation. Ratios use positive reference weights.

| Subset | Model | n | Mean signed error (g) | Median predicted/reference ratio |
|---|---|---|---|---|
| Own complete dishes | GPT-4o | 86 | -71.53 | 0.6827 |
| Own complete dishes | Sol | 118 | -35.18 | 0.9196 |
| Shared complete dishes | GPT-4o | 79 | -75.05 | 0.6787 |
| Shared complete dishes | Sol | 79 | -25.15 | 0.9402 |

On the 79 shared dishes, weight MAE decreased by 33.8 g, with a paired interval of −48.9 to −19.7 g. The mean signed error improved from −75.1 to −25.2 g, and the median ratio increased from 0.679 to 0.940. These results support reduced weight underestimation on this shared subset, conditional on the observed responses.

Energy MAE instead changed from 126.9 to 131.8 kcal; its difference interval includes zero. Fat, carbohydrate and protein difference intervals also include zero. Weight improvement therefore did not translate into a consistent nutrient improvement. Different food decompositions or FNDDS densities are possible contributors, but their individual effects were not isolated.

For ASA24, the shared weight and energy MAE point estimates decreased, but both paired intervals include zero. With only 10 shared records and unchanged classification accuracy, the evidence for a stable portion-estimation improvement is limited.

## 4. Departures from the paper and released code

The main departures are summarized here; the item-by-item register remains in [CHECKLIST.md](CHECKLIST.md), with evidence and review decisions in [REVIEW.md](REVIEW.md).

| Area | Departure or reconstruction | Register |
|---|---|---|
| Model and API availability | Unavailable GPT-4 Turbo models were replaced with GPT-4o, then compared with Sol; Azure clients were replaced with the official OpenAI interface. Supported settings differ as documented in Section 1.3. | A2–A4, F1–F3 |
| Conflicts resolved using the paper | Independent image requests, 256 × 256 preprocessing, a persisted index, description-only retrieval, and image-assisted code selection were restored or implemented. | A5, B6, C1, C3–C4 |
| Missing data preparation | ASA24 labels and exact portion mappings, FoodWeights with 22,710 portions, and Nutrition5k sampling were reconstructed. Unmapped ASA24 portions were excluded rather than inferred; portion code 98 uses the metadata multiplier in grams. Missing Nutrition5k nutrient labels were excluded. | B2, B4–B5 |
| Missing inference and evaluation | Portion text was mapped to codes and multiplied quantities; Nutrition5k code/gram prompts and evaluation were reconstructed. ASA24 conditional inclusion and cumulative matching levels are documented interpretations of the code and paper. | C6, C8, D1–D7 |
| Correctness repairs | Numeric parsing, rate-limit backoff, continuation skipping and missing-value handling were repaired. Invalid food codes and absent gram estimates remain failures rather than valid zero totals. | C5–C6, C8–C9, D7 |
| Food-list parsing | Shared parsing preserves punctuation in names, removes list preambles, merges duplicate names and retains items without valid codes as failures. This changes item counts, failure denominators and complete-dish membership relative to the released parser. | C8, R-C8-1 |
| Retries and retained behavior | The released code's limit of five semantic passes was retained; the SDK retry limit was raised from two to six, with four images processed concurrently. Generated blank lines can still trigger empty retrieval queries. Semantic passes remain ambiguous relative to the paper's once-per-image statement. | C3, C9, E4 |

Three adaptations were approved from development evidence before the GPT-4o test: remove the refusal opt-out sentence from description/portion prompts, request a best estimate in grams for Nutrition5k, and parse the full gram response rather than only its first paragraph. Early development responses showed widespread refusals and estimates placed after disclaimers. **All three adaptations were held fixed for the Sol comparison.** The broader food-list repair above is a separate change, not one of these three adaptations.

The study does not reproduce commercial or direct-vision baselines, food-subclass results, all 65 nutrients, or dietitian ratings. The scope is the two datasets and five main targets reported here.

## 5. Interpretation and limitations

The primary GPT-4o reproduction ran the reconstructed pipeline but did not recover the paper's main MAEs. The supplementary comparison, motivated by the original model's unavailability, shows that replacement-model choice and supported settings can improve part of the weight error. Sol's own-subset Nutrition5k weight MAE is 69.4 g versus the paper's 45.1 g, while energy remains 124.6 kcal versus 68.2 kcal. ASA24's lower MAE point estimates accompany fewer Exact records and wide paired intervals.

The main limits are:

- **Conditional coverage:** MAE applies only to valid conditional estimates, not every test record. The shared subsets are also selected subsets of the full test samples. Sol completed 39 Nutrition5k dishes that GPT-4o did not, but failed to complete seven that GPT-4o did; comparing own subsets alone cannot separate this selection effect.
- **Sample and label differences:** ASA24 sampling is restricted to 284 eligible codes, and its photographs are often shared by several labels. Nutrition5k images all come from Cafe 1. The smaller samples and mapping exclusions differ from the paper's broader evaluation.
- **Protocol interpretation:** ASA24 reference-code conditioning follows the released code, while the paper does not explicitly give the MAE inclusion count. Cumulative matching levels and unit-based portion error are also documented interpretations. Prompt adaptations further limit exact equivalence to the published procedure.
- **Response uncertainty:** each configuration was tested once. Temperature 0 is not perfectly repeatable, and Sol uses temperature 1 with a larger reasoning-inclusive description budget. Bootstrap intervals reflect sampling under these fixed answers, not repeated model responses; cross-code photograph dependence may make ASA24 intervals too narrow.

The comparison supports a **partial reduction in weight underestimation**, without a corresponding improvement in exact identification or nutrient MAE. It cannot attribute the full reproduction gap to model capability, nor establish that the remaining gap must arise from sampling or protocol differences. Retrieval, food composition, nutrient mapping and sample/protocol effects remain unresolved contributors.

## 6. Records, cost and verification

| Formal run | Saved results | API responses | HTTP errors | Estimated cost |
|---|---|---|---|---|
| GPT-4o | `runs/test/` | 8,867 | 0 | $5.28 |
| Sol | `runs/test-gpt-6.1-sol/` | 3,234 | 1 | $2.30 |

Each configuration has one completed formal invocation. Semantic code-generation attempts totaled 309/295 for ASA24/Nutrition5k with GPT-4o and 155/152 with Sol; these are distinct from SDK retries of an individual request. Inference commits were `ea3c08b` and `fbe5157`, respectively. Configuration files retain input/source fingerprints, request parameters, actual served model names and step-level usage.

Sol's one HTTP 500 was retried by the retained SDK logic, and the formal run completed. All 1,391 successful chat responses ended normally with nonempty content. Ledger and metric reconciliation passed, while `validation.json` deliberately retains `response_health=needs review` and the overall warning for that historical error. The corresponding audit command returns nonzero; the warning was accepted in review and was not rewritten as PASS.

Costs are estimates from returned token usage and recorded prices, not invoice totals. Sol cost $2.29594796, including 64,977 reasoning tokens within 124,310 completion tokens, without double charging. The project total, including index construction, development and both formal tests, is **$9.00796341**, within the $20 limit. Run records preserve the prices used; the Sol records also include the official pricing source and verification date.

Implementation and numerical results passed two independent review checkpoints and 121 offline tests. Full evidence is available in:

- [Primary metrics](runs/test/metrics.json) and [primary diagnostics](runs/test/diagnostics/).
- [Sol metrics](runs/test-gpt-6.1-sol/metrics.json), [diagnostics](runs/test-gpt-6.1-sol/diagnostics/) and [validation record](runs/test-gpt-6.1-sol/validation.json).
- [Full model comparison](runs/comparison-gpt-4o-vs-sol/comparison.json), including all own/shared estimates, paired intervals, sample keys and excluded bootstrap counts.
- [CHECKLIST.md](CHECKLIST.md) and [REVIEW.md](REVIEW.md) for implementation decisions, source references and review history; `samples/` and `paper/supplementary/SOURCES.md` for data provenance.

Offline comparison and Exact diagnostics can be reproduced from the repository root:

```sh
python code/compare_models.py --baseline runs/test --comparison runs/test-gpt-6.1-sol --output runs/comparison-gpt-4o-vs-sol
python runs/test/diagnostics/exact_misses.py --run-dir runs/test-gpt-6.1-sol
```

The preserved force-terminated development run was not resumed. Forced termination can prevent the driver from archiving its current step; future recovery requires reconciliation with the global API log. Both formal runs completed normally. No test results were used to alter prompts, parsing, inference settings or evaluation after their respective configurations were frozen.
