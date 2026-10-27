"""D: the evaluation of the ASA24 and Nutrition5k results (offline)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))

import evaluate  # noqa: E402
import nutrient_estimate  # noqa: E402
import nutrient_estimate_mix  # noqa: E402
import rag_portion_size  # noqa: E402

IMAGE_LINK = pd.DataFrame({
    'FoodCode': [63101000, 63101000, 63101000, 11111000, 11111000, 11111000],
    'FC_Description': ['Apple, raw', 'Apple, raw', 'Apple, raw', "Milk, cow's, fluid, whole, NFS", "Milk, cow's, fluid, whole, NFS",
                       "Milk, cow's, fluid, whole, NFS"],
    'Image': ['a1.png', 'a2.png', 'a3.png', 'm1.png', 'm2.png', 'm3.png'],
    'Portion': ['1/4 fruit', '1/2 fruit', '1 fruit', '1/4 cup', '1-1/2 cups', '2 cups'],
    'PortionCode': [60813, 60813, 60813, 30000, 10205, 10205],
    'PortionSubCode': [0] * 6,
    'Multiplier': [0.25, 0.5, 1.0, 2.0, 1.5, 2.0],
    'PortionWeight': [182.0, 182.0, 182.0, 30.5, 244.0, 244.0],
    'Weight': [45.5, 91.0, 182.0, 61.0, 366.0, 488.0],
})


class TestD1FoodCodeCommon(unittest.TestCase):

    def test_codes_in_the_answer(self):
        self.assertEqual(rag_portion_size.parse_food_codes("['11111000', '11112110']"), [11111000, 11112110])
        self.assertEqual(rag_portion_size.parse_food_codes("['Food code: 63101000 (apple)']"), [63101000])
        self.assertEqual(rag_portion_size.parse_food_codes("['123456789', '1234567']"), [])
        self.assertEqual(rag_portion_size.parse_food_codes(np.nan), [])

    def test_common_code_is_the_label_when_predicted(self):
        df = pd.DataFrame({'FoodCode': [63101000, 63101000, 11111000],
                           'GPTFoodCode': ["['63101110', '63101000']", "['63101110']", np.nan]})
        df = rag_portion_size.add_food_code_common(df, IMAGE_LINK)
        self.assertEqual(df.loc[0, 'FoodCodeCommon'], 63101000)
        self.assertEqual(df.loc[0, 'FC_Description'], 'Apple, raw')
        for i in (1, 2):  # a wrong code or no answer: no common code, so no portion step
            self.assertTrue(pd.isna(df.loc[i, 'FoodCodeCommon']))
            self.assertTrue(pd.isna(df.loc[i, 'FC_Description']))



# per 100 g, from the FNDDS 2019-2020 workbook
NUTRITION = pd.DataFrame({'Food code': [11111000, 63101000], 'Energy (kcal)': [61.0, 61.0],
                          'Total Fat (g)': [3.20, 0.15], 'Carbohydrate (g)': [4.63, 14.8], 'Protein (g)': [3.27, 0.17]})


def asa24_outputs():
    """nutrient_estimate.py output for four images: milk 1-1/2 cups answered '2 cups' (A),
    apple 1/2 fruit answered right (B), milk with a wrong code (C), apple with an answer that
    is not an option (D)."""
    df = pd.DataFrame({
        'FoodCode': [11111000, 63101000, 11111000, 63101000], 'Size': ['Largest', 'Medium', 'Smallest', 'Smallest'],
        'Weight': [366.0, 91.0, 61.0, 45.5], 'Portion': ['1-1/2 cups', '1/2 fruit', '1/4 cup', '1/4 fruit'],
        'GPTFoodCode': ["['11111000']", "['63101000']", "['11112110']", "['63101000']"],
        'FoodCodeCommon': [11111000.0, 63101000.0, np.nan, 63101000.0],
        'GPTPortionDescription': ['2 cups', '1/2 fruit', np.nan, 'one quarter'],
        'GPTPortionAmount': ['1.5', '0.25', np.nan, '0.25'], 'LabelAmount': [1.5, 0.5, 0.25, 0.25],
        'TotalWeight': [488.0, 91.0, np.nan, np.nan], 'AmountWeight': [366.0, 45.5, np.nan, 45.5]})
    per_100g = NUTRITION.set_index('Food code')
    for name in evaluate.NUTRIENTS:
        df[name] = [per_100g.loc[c, name] * w / 100 if not pd.isna(w) else np.nan
                    for c, w in zip(df['FoodCode'], df['TotalWeight'])]
    return df


class TestD2Asa24Mae(unittest.TestCase):

    def test_three_images_by_hand(self):
        result = evaluate.asa24_mae(asa24_outputs(), NUTRITION)
        option = result['option']['Total']
        # A: |488 - 366| = 122, B: 0; reference mean (366 + 91) / 2 = 228.5
        self.assertEqual(option['Weight (g)']['n'], 2)
        self.assertAlmostEqual(option['Weight (g)']['per_dish'], 61.0)
        self.assertAlmostEqual(option['Weight (g)']['per_unit'], 61.0 / 228.5)
        # fat: A 3.20 x (4.88 - 3.66) = 3.904, B 0; reference mean (11.712 + 0.1365) / 2
        self.assertAlmostEqual(option['Total Fat (g)']['per_dish'], 1.952)
        self.assertAlmostEqual(option['Total Fat (g)']['per_unit'], 1.952 / 5.92425)
        self.assertAlmostEqual(option['Energy (kcal)']['per_dish'], 61 * 1.22 / 2)
        # by size: C has no common code, D's answer is not an option, so no Smallest image
        self.assertEqual(result['option']['Largest']['Weight (g)']['per_dish'], 122.0)
        self.assertEqual(result['option']['Medium']['Weight (g)']['per_dish'], 0.0)
        self.assertEqual(result['option']['Smallest']['Weight (g)']['n'], 0)
        # amount reading: A 0, B |45.5 - 91|, D 0 over (366 + 91 + 45.5) / 3
        amount = result['amount']['Total']['Weight (g)']
        self.assertEqual(amount['n'], 3)
        self.assertAlmostEqual(amount['per_dish'], 45.5 / 3)
        self.assertAlmostEqual(amount['per_unit'], (45.5 / 3) / (502.5 / 3))
        self.assertAlmostEqual(result['amount']['Total']['Carbohydrate (g)']['per_dish'], 14.8 * 0.455 / 3)



FOOD_WEIGHTS = pd.DataFrame({
    'Food Code': [11111000, 11111000, 11111000, 11111000, 11112110, 11112110, 63101000, 63101000, 63101000],
    'Seq Num': [1, 2, 4, 6, 1, 2, 1, 2, 3],
    'Portion Code': [10205, 30000, 63480, 90000, 10205, 30000, 62015, 61238, 10180],
    'Subcode': [0] * 9,
    'Portion Weight': [244.0, 30.5, 2.5, 244.0, 244.0, 30.5, 149.0, 182.0, 109.0],
    'Portion Description': ['1 cup', '1 fl oz', 'Guideline amount per fl oz of beverage', 'Quantity not specified',
                            '1 cup', '1 fl oz', '1 small', '1 medium', '1 cup, sliced']})
E2E_NUTRITION = pd.DataFrame({'Food code': [11111000, 11112110, 63101000],
                              'Main food description': ['Milk, whole', 'Milk, reduced fat (2%), NFS', 'Apple, raw'],
                              'Energy (kcal)': [61.0, 50.0, 61.0], 'Total Fat (g)': [3.20, 1.90, 0.15],
                              'Carbohydrate (g)': [4.63, 4.80, 14.8], 'Protein (g)': [3.27, 3.30, 0.17]})


class PerImageVision:
    """Answers the shot and amount prompts per image, and keeps the prompts."""

    def __init__(self, answers):
        self.answers, self.prompts = answers, []

    def chat(self, prompt, image_path):
        self.prompts.append((prompt, image_path))
        shot, amount = self.answers[image_path]
        return shot if 'choose the option' in prompt else amount


def end_to_end_table():
    """Whole milk answered as 2% milk (a code not in FNDDS first), an apple without an answer,
    and an apple whose portion answer is not an option."""
    return pd.DataFrame({'FoodCode': [11111000, 63101000, 63101000], 'Size': ['Largest', 'Medium', 'Medium'],
                         'Portion': ['1-1/2 cups', '1/2 fruit', '1/2 fruit'], 'Weight': [366.0, 91.0, 91.0],
                         'Link': ['/img/m.png', '/img/a.png', '/img/b.png'],
                         'GPTFoodCode': ["['99999999', '11112110']", np.nan, "['63101000']"]})


class TestD3EndToEnd(unittest.TestCase):

    def test_options_come_from_the_predicted_code(self):
        df = rag_portion_size.prepare_end_to_end(end_to_end_table(), FOOD_WEIGHTS, E2E_NUTRITION)
        self.assertEqual(df['GPTFoodCodeE2E'].tolist()[::2], [11112110, 63101000])
        self.assertTrue(pd.isna(df.loc[1, 'GPTFoodCodeE2E']))
        self.assertEqual(df.loc[0, 'FC_DescriptionE2E'], 'Milk, reduced fat (2%), not further specified subcategory assigned')
        self.assertEqual(df.loc[0, 'PortionShotE2E'], '1 cup ,1 fl oz')
        self.assertEqual(df.loc[2, 'PortionShotE2E'], '1 small ,1 medium ,1 cup, sliced')
        unit = rag_portion_size.end_to_end_unit
        self.assertEqual(unit('1 small ,1 medium ,1 cup, sliced', '1 cup, sliced.'), 'cup, sliced')
        self.assertEqual(unit('1/2 bagel ,1 bagel', '1/2 bagel'), '1/2 bagel')
        self.assertTrue(pd.isna(unit('1 cup ,1 fl oz', 'a glass')))

    def test_end_to_end_run_uses_no_label(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        portion = os.path.join(tmp.name, 'portion.csv')
        end_to_end_table().to_csv(portion, index=False)
        weights, nutrition = os.path.join(tmp.name, 'w.csv'), os.path.join(tmp.name, 'n.xlsx')
        FOOD_WEIGHTS.to_csv(weights, index=False)
        llm = PerImageVision({'/img/m.png': ('1 cup', '1.5'), '/img/b.png': ('one apple', '1')})
        args = rag_portion_size.parse_args(['--portion_path', portion, '--end_to_end', '--food_weights_path', weights,
                                            '--nutrition_path', nutrition])
        with mock.patch.object(rag_portion_size, 'Vision', return_value=llm), \
                mock.patch.object(rag_portion_size.time, 'sleep'), \
                mock.patch.object(rag_portion_size.pd, 'read_excel', return_value=E2E_NUTRITION):
            rag_portion_size.main_end_to_end(args)
        # shot for both images with a code; amount only where the answer is an option
        self.assertEqual([path for _, path in llm.prompts], ['/img/m.png', '/img/b.png', '/img/m.png'])
        for prompt, _ in llm.prompts:
            for label in ('Milk, whole', '1-1/2 cups', '1/2 fruit', '366', '91'):
                self.assertNotIn(label, prompt)
        self.assertIn('how many cup of the food are visible', llm.prompts[2][0])
        df = nutrient_estimate.end_to_end_weight(pd.read_csv(portion), FOOD_WEIGHTS)
        self.assertEqual(df.loc[0, 'WeightE2E'], 366.0)  # 1.5 x 1 cup of 2% milk
        self.assertTrue(df.loc[1:, 'WeightE2E'].isna().all())

    def test_end_to_end_mae(self):
        df = end_to_end_table().assign(GPTFoodCodeE2E=[11112110.0, np.nan, 63101000.0],
                                       WeightE2E=[366.0, np.nan, np.nan])
        result = evaluate.asa24_end_to_end(df, E2E_NUTRITION)
        total = result['Total']
        self.assertAlmostEqual(total['success_rate'], 1 / 3)
        self.assertEqual(total['Weight (g)'], {'n': 1, 'per_dish': 0.0, 'per_unit': 0.0})
        # the nutrients of the predicted code: (61 - 50) x 3.66
        self.assertAlmostEqual(total['Energy (kcal)']['per_dish'], 11 * 3.66)
        self.assertAlmostEqual(total['Energy (kcal)']['per_unit'], 11 / 61)
        self.assertEqual(result['Medium']['success_rate'], 0.0)



class TestD4MatchLevels(unittest.TestCase):

    def test_levels(self):
        self.assertEqual(evaluate.match_level(11111000, 11111000), 'Exact')
        self.assertEqual(evaluate.match_level(11112110, 11111000), 'Close')  # same subgroup 11
        self.assertEqual(evaluate.match_level(14010000, 11111000), 'Far')    # same group 1, milk
        self.assertEqual(evaluate.match_level(63101000, 11111000), 'Mismatch')

    def test_cumulative_shares(self):
        df = pd.DataFrame({'FoodCode': [11111000] * 5, 'Size': ['Largest'] * 3 + ['Smallest'] * 2,
                           'GPTFoodCode': ["['11111000']", "['63101000', '11112110']", "['14010000']",
                                           "['63101000']", np.nan]})
        result = evaluate.asa24_match_levels(df)
        any_code = result['Total']['any']
        self.assertEqual(any_code['n'], 4)  # the image without a code is left out (Table 3)
        self.assertEqual([any_code[level] for level in evaluate.LEVELS], [0.25, 0.5, 0.75, 0.25])
        first = result['Total']['first']  # the second image's first code is a mismatch
        self.assertEqual([first[level] for level in evaluate.LEVELS], [0.25, 0.25, 0.5, 0.5])
        self.assertEqual(result['Smallest']['any']['n'], 1)
        self.assertEqual(result['Largest']['any']['Far'], 1.0)



class TestD5Portions(unittest.TestCase):

    def test_accuracy_and_errors(self):
        result = evaluate.asa24_portions(asa24_outputs())
        total = result['Total']
        self.assertEqual(total['n'], 3)  # C has no common code, so it was not asked
        # B is right; A chose '2 cups' for 1-1/2 cups; D's answer is not an option
        self.assertAlmostEqual(total['classification_accuracy'], 1 / 3)
        # units: A |1.5 - 1.5|, B |0.25 - 0.5|, D |0.25 - 0.25|
        self.assertEqual(total['unit_error']['n'], 3)
        self.assertAlmostEqual(total['unit_error']['per_dish'], 0.25 / 3)
        self.assertAlmostEqual(total['gram_error_option']['per_dish'], 61.0)
        self.assertAlmostEqual(total['gram_error_amount']['per_dish'], 45.5 / 3)
        self.assertEqual(result['Medium']['classification_accuracy'], 1.0)
        self.assertEqual(result['Smallest']['n'], 1)
        self.assertEqual(result['Smallest']['classification_accuracy'], 0.0)



def nutrition5k_outputs():
    """nutrient_estimate_mix.py output: a complete dish, a dish with one food unweighed, a dish
    with a code missing from FNDDS, and a dish without a food code."""
    return pd.DataFrame({
        'dish_id': ['d1', 'd2', 'd3', 'd4'],
        'total_mass': [300.0, 200.0, 150.0, 100.0], 'total_calories': [400.0, 250.0, 120.0, 90.0],
        'total_fat': [10.0, 8.0, 2.0, 1.0], 'total_carbs': [50.0, 30.0, 20.0, 15.0], 'total_protein': [30.0, 12.0, 5.0, 3.0],
        'GPTFoodCode': ['Chicken: 24198340; Rice: 56205000', 'Salmon: 26137110; Kale: 72125100; Oil: 82101000',
                        'Mystery: 99999999', np.nan],
        'IngredientNum': [2, 3, 1, 0], 'WeightError': [0, 1, 0, np.nan], 'FoodCodeError': [0, 0, 1, np.nan],
        'GPTWeight': [320.0, 150.0, 140.0, np.nan], 'Energy (kcal)': [380.0, 200.0, np.nan, np.nan],
        'Total Fat (g)': [12.0, 6.0, np.nan, np.nan], 'Carbohydrate (g)': [45.0, 10.0, np.nan, np.nan],
        'Protein (g)': [33.0, 20.0, np.nan, np.nan]})


class TestD6SuccessRates(unittest.TestCase):

    def test_asa24(self):
        result = evaluate.asa24_success_rates(asa24_outputs())
        total = result['Total']
        self.assertEqual(total['food_code'], 1.0)  # C's code is wrong but it is a code
        self.assertEqual(total['asked_portion'], 3)
        self.assertAlmostEqual(total['portion_option'], 2 / 3)  # D's answer is not an option
        self.assertEqual(total['portion_amount'], 1.0)
        self.assertEqual(total['nutrients'], 0.5)
        self.assertEqual(result['Smallest']['nutrients'], 0.0)

    def test_nutrition5k(self):
        result = evaluate.nutrition5k_success_rates(nutrition5k_outputs())
        self.assertEqual(result['food_code_per_dish'], 0.75)
        self.assertAlmostEqual(result['portion_per_dish'], 2 / 3)  # d2 misses one food's grams
        self.assertEqual(result['food_items'], 6)
        self.assertAlmostEqual(result['portion_per_food_item'], 5 / 6)



class TestD7Nutrition5kMae(unittest.TestCase):

    def test_complete_dishes(self):
        result = evaluate.nutrition5k_mae(nutrition5k_outputs())
        complete = result['complete']
        self.assertEqual(complete['Weight (g)'], {'n': 1, 'per_dish': 20.0, 'per_unit': 20.0 / 300})
        self.assertAlmostEqual(complete['Energy (kcal)']['per_dish'], 20.0)
        self.assertAlmostEqual(complete['Protein (g)']['per_unit'], 3.0 / 30)
        # every dish with an estimate: d1, d2 and d3 for weight; d3 has no nutrients
        anything = result['any_estimate']
        self.assertEqual(anything['Weight (g)']['n'], 3)
        self.assertAlmostEqual(anything['Weight (g)']['per_dish'], (20 + 50 + 10) / 3)
        self.assertEqual(anything['Energy (kcal)']['n'], 2)

    def test_report(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        asa24, n5k = os.path.join(tmp.name, 'a.csv'), os.path.join(tmp.name, 'n.csv')
        asa24_outputs().to_csv(asa24, index=False)
        nutrition5k_outputs().to_csv(n5k, index=False)
        out = [os.path.join(tmp.name, name) for name in ('m.json', 'm.md')]
        args = evaluate.parse_args(['--asa24', asa24, '--nutrition5k', n5k, '--output_json', out[0], '--output_md', out[1]])
        with mock.patch.object(evaluate.pd, 'read_excel', return_value=NUTRITION):
            evaluate.main(args)
        import json
        metrics = json.load(open(out[0]))
        self.assertAlmostEqual(metrics['asa24']['mae_protocol']['option']['Total']['Weight (g)']['per_dish'], 61.0)
        self.assertIsNone(metrics['asa24']['mae_protocol']['option']['Smallest']['Weight (g)']['per_dish'])
        self.assertEqual(metrics['nutrition5k']['dishes'], 4)
        text = open(out[1]).read()
        self.assertIn('| Weight (g) | 61 | 0.267 | 2 | 49.4 | 0.348 |', text)


class TestInvalidNumbers(unittest.TestCase):
    """R-C6-2: an answer that is not one valid number is a failure, in the success rates and the MAE."""

    def test_asa24(self):
        answers = ['1.5', '-2', '1,000', 'I cannot determine whether there are 2 cups from this image.', 'inf']
        weights = pd.DataFrame({'Food Code': [11111000], 'Portion Code': [10205], 'Subcode': [0], 'Portion Weight': [244.0],
                                'Portion Description': ['1 cup']})
        df = pd.DataFrame({'FoodCode': 11111000, 'Size': 'Largest', 'Portion': '1-1/2 cups', 'Weight': 366.0,
                           'GPTFoodCode': "['11111000']", 'FoodCodeCommon': 11111000.0, 'GPTPortionDescription': '1-1/2 cups',
                           'LabelAmount': 1.5, 'LabelUnit': 'cup', 'GPTPortionAmount': answers,
                           'GPTFoodCodeE2E': 11111000.0, 'GPTPortionDescriptionE2E': '1 cup', 'GPTPortionAmountE2E': answers})
        with mock.patch('builtins.print'):
            df = nutrient_estimate.estimate(df, weights, IMAGE_LINK, NUTRITION, evaluate.NUTRIENTS)
        df = nutrient_estimate.end_to_end_weight(df, weights)
        for column in ('AmountWeight', 'WeightE2E'):
            self.assertEqual(df.loc[[0, 2], column].tolist(), [366.0, 244000.0], column)  # 1,000 cups, not 1
            self.assertTrue(df.loc[[1, 3, 4], column].isna().all(), column)
        self.assertEqual(evaluate.asa24_success_rates(df)['Total']['portion_amount'], 2 / 5)
        self.assertEqual(evaluate.asa24_portions(df)['Total']['unit_error']['n'], 2)
        self.assertEqual(evaluate.asa24_mae(df, NUTRITION)['amount']['Total']['Weight (g)']['n'], 2)
        self.assertEqual(evaluate.asa24_end_to_end(df, NUTRITION)['Total']['success_rate'], 2 / 5)

    def test_nutrition5k(self):
        nutrition = pd.DataFrame({'Food code': [11111111, 22222222], 'a': 0, 'b': 0, 'c': 0, 'Energy (kcal)': [100.0, 50.0],
                                  'Total Fat (g)': [1.0, 1.0], 'Carbohydrate (g)': [20.0, 10.0], 'Protein (g)': [2.0, 5.0]})
        columns = nutrition.columns[4:]
        df = pd.DataFrame({'total_mass': 300.0, 'total_calories': 250.0, 'total_fat': 3.0, 'total_carbs': 50.0,
                           'total_protein': 9.0, 'GPTFoodCode': 'rice: 11111111; beans: 22222222',
                           'GPTAmount': ['rice: 200\nbeans: 100', 'rice: -20\nbeans: 100', 'rice: 1,000\nbeans: 100']})
        df['GPTAmountWeight'] = df['GPTAmount'].apply(nutrient_estimate_mix.parse_food_items)
        df[columns] = np.nan
        with mock.patch('builtins.print'):
            df = nutrient_estimate_mix.process_results(df, nutrition, columns)
        self.assertEqual(df['WeightError'].tolist(), [0, 1, 0])  # -20 g was read as 20 g
        self.assertEqual(df.loc[2, 'GPTWeight'], 1100.0)  # 1,000 g was read as 1 g
        rates = evaluate.nutrition5k_success_rates(df)
        self.assertAlmostEqual(rates['portion_per_dish'], 2 / 3)
        self.assertAlmostEqual(rates['portion_per_food_item'], 5 / 6)
        self.assertEqual(evaluate.nutrition5k_mae(df)['complete']['Weight (g)']['n'], 2)


class TestNoWeightIsNoEstimate(unittest.TestCase):
    """R-D7-1: a dish whose foods all lack grams has no weight, not 0 g in the D7 MAE."""

    def test_nutrition5k(self):
        nutrition = pd.DataFrame({'Food code': [11111111, 22222222], 'a': 0, 'b': 0, 'c': 0, 'Energy (kcal)': [100.0, 50.0],
                                  'Total Fat (g)': [1.0, 1.0], 'Carbohydrate (g)': [20.0, 10.0], 'Protein (g)': [2.0, 5.0]})
        columns = nutrition.columns[4:]
        codes = 'rice: 11111111; beans: 22222222'
        df = pd.DataFrame({'total_mass': 200.0, 'total_calories': 250.0, 'total_fat': 3.0, 'total_carbs': 50.0,
                           'total_protein': 9.0,
                           'GPTFoodCode': ['rice: 11111111', codes, codes, 'rice 11111111', codes, codes],
                           'GPTAmount': ['rice: none', 'no weights here', np.nan, 'rice: 100',  # all fail
                                         'rice: 100\nbeans: none', 'rice: 0\nbeans: 0']})  # partial; predicted 0 g
        df['GPTAmountWeight'] = df['GPTAmount'].apply(nutrient_estimate_mix.parse_food_items)
        df[columns] = np.nan
        with mock.patch('builtins.print'):
            df = nutrient_estimate_mix.process_results(df, nutrition, columns)
        self.assertEqual(df['IngredientNum'].tolist(), [1, 2, 2, 0, 2, 2])
        self.assertEqual(df['WeightError'].tolist(), [1, 2, 2, 0, 1, 0])
        self.assertTrue(df.loc[:3, 'GPTWeight'].isna().all())  # was 0 g for all but the third
        self.assertTrue(df.loc[:3, evaluate.NUTRIENTS].isna().all().all())
        self.assertEqual(df.loc[4:, 'GPTWeight'].tolist(), [100.0, 0.0])
        self.assertEqual(df.loc[5, 'Energy (kcal)'], 0.0)
        result = evaluate.nutrition5k_mae(df)
        # any_estimate: the partial dish and the 0 g one (it had n = 5, MAE 200 g for each failure)
        self.assertEqual(result['any_estimate']['Weight (g)'], {'n': 2, 'per_dish': 150.0, 'per_unit': 0.75})
        self.assertEqual(result['complete']['Weight (g)']['n'], 1)  # the 0 g dish
        self.assertEqual(result['any_estimate']['Energy (kcal)']['n'], 2)


if __name__ == '__main__':
    unittest.main()
