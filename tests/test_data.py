"""B: the data tables the original scripts read (offline). Run code/place_inputs.py and the
processing scripts first (CHECKLIST.md B1-B6); a missing table skips its test."""
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))

import asa24_proc  # noqa: E402
import nutrition5k_proc  # noqa: E402
import place_inputs  # noqa: E402

FOODS_CSV = ROOT / 'FNDDS' / '2019-2020 FNDDS - Foods and Beverages.csv'
PORTIONS_XLSX = ROOT / 'FNDDS' / '2019-2020 FNDDS At A Glance - Portions and Weights.xlsx'
FOOD_WEIGHTS_CSV = ROOT / 'FoodWeights.csv'
TOP_1000_CSV = ROOT / 'NHANES' / 'top_1000_frequent_select_foods.csv'
DR1IFF = [ROOT / 'NHANES' / '2011-2012' / 'DR1IFF_G.XPT', ROOT / 'NHANES' / '2013-2014' / 'DR1IFF_H.XPT',
          ROOT / 'NHANES' / '2015-2016' / 'DR1IFF_I.XPT',
          ROOT / 'NHANES' / '2017 March-2020 Pre-pandemic' / 'P_DR1IFF.XPT']
IMAGE_LINK_CSV = ROOT / 'df_image_link.csv'
RESULTS_CSV = ROOT / 'df_results.csv'
DEV_RESULTS_CSV = ROOT / 'df_results_dev.csv'
DISH_CSV = ROOT / 'dish_metadata.csv'
DEV_DISH_CSV = ROOT / 'dish_metadata_dev.csv'
AVAILABLE_CSV = ROOT / 'Nutrition5k' / 'metadata' / 'dish_metadata_available.csv'
IMAGE_HASHES = ROOT / 'samples' / 'nutrition5k_images.sha256'


def need(path):
    if not path.exists():
        raise unittest.SkipTest(f'{path.relative_to(ROOT)} is missing: run the B steps first')


class TestInputs(unittest.TestCase):

    def test_inputs_match_the_snapshot(self):
        for _, target, expected in place_inputs.INPUTS:
            with self.subTest(target=target):
                need(ROOT / target)
                self.assertEqual(place_inputs.sha256(ROOT / target), expected)


class TestB1(unittest.TestCase):

    def test_fndds_descriptions(self):
        # paper.txt:130-131: J = 5624 FNDDS food codes, each with a description
        need(FOODS_CSV)
        df = pd.read_csv(FOODS_CSV)
        self.assertEqual(list(df.columns), ['Food code', 'Food description'])
        self.assertEqual(len(df), 5624)
        self.assertEqual(df['Food code'].nunique(), 5624)
        self.assertTrue(df['Food description'].str.startswith('The image shows the food category of ').all())
        self.assertFalse(df['Food description'].str.contains(r'\bNFS\b|\bNS\b').any())


class TestB2(unittest.TestCase):

    def test_food_weights_match_at_a_glance(self):
        need(FOOD_WEIGHTS_CSV)
        need(PORTIONS_XLSX)
        weights = pd.read_csv(FOOD_WEIGHTS_CSV)
        at = pd.read_excel(PORTIONS_XLSX, header=1).sort_values(['Food code', 'Seq num']).reset_index(drop=True)
        self.assertEqual(len(weights), 22710)
        self.assertEqual(len(weights), len(at))
        # nutrient_estimate.get_portion_weight needs exactly one row per food and portion code
        self.assertFalse(weights.duplicated(['Food Code', 'Portion Code']).any())
        self.assertEqual(weights['Food Code'].tolist(), at['Food code'].tolist())
        self.assertEqual(weights['Seq Num'].tolist(), at['Seq num'].tolist())
        self.assertEqual(weights['Portion Weight'].tolist(), at['Portion weight (g)'].tolist())
        self.assertEqual(weights['Portion Description'].tolist(), at['Portion description'].str.strip().tolist())

    def test_spot_checks(self):
        # looked up by hand in the At A Glance workbook
        need(FOOD_WEIGHTS_CSV)
        weights = pd.read_csv(FOOD_WEIGHTS_CSV).set_index(['Food Code', 'Portion Description'])['Portion Weight']
        self.assertEqual(weights[(11111000, '1 cup')], 244.0)
        self.assertEqual(weights[(63101000, '1 medium')], 200.0)
        self.assertEqual(weights[(51101000, '1 medium or regular slice')], 28.0)


class TestB3(unittest.TestCase):

    def test_top_1000_codes(self):
        # paper.txt:227-229: the top 1000 codes cover 81.4% of the NHANES records
        need(TOP_1000_CSV)
        for path in DR1IFF:
            need(path)
        top = pd.read_csv(TOP_1000_CSV)
        self.assertEqual(len(top), 1000)
        self.assertEqual(top['Food code'].nunique(), 1000)
        self.assertEqual(top['Rank'].tolist(), list(range(1000)))
        counts = pd.concat([pd.read_sas(path).query('DR1DRSTZ == 1')['DR1IFDCD'].astype(int)
                            for path in DR1IFF]).value_counts()
        share = counts[top['Food code']].sum() / counts.sum()
        self.assertAlmostEqual(share, 0.814, places=3)
        # every code outside the list is consumed no more often than the last one in it
        self.assertLessEqual(counts.drop(top['Food code']).max(), counts[top['Food code']].min())


class TestB4(unittest.TestCase):

    def setUp(self):
        for path in (IMAGE_LINK_CSV, RESULTS_CSV, DEV_RESULTS_CSV, TOP_1000_CSV, FOODS_CSV, FOOD_WEIGHTS_CSV):
            need(path)
        self.link = pd.read_csv(IMAGE_LINK_CSV)
        self.test = pd.read_csv(RESULTS_CSV)
        self.dev = pd.read_csv(DEV_RESULTS_CSV)

    def test_sample_sizes(self):
        # CHECKLIST.md principle 5: 50 codes x largest, medium, smallest; 10 development images
        self.assertEqual(len(self.test), 150)
        self.assertEqual(self.test['FoodCode'].nunique(), 50)
        sizes = self.test.pivot(index='FoodCode', columns='Size', values='Weight')
        self.assertTrue(((sizes['Largest'] > sizes['Medium']) & (sizes['Medium'] > sizes['Smallest'])).all())
        self.assertEqual(len(self.dev), 10)
        self.assertFalse(self.dev['FoodCode'].isin(self.test['FoodCode']).any())
        self.assertFalse(self.dev['Image'].isin(self.test['Image']).any())
        self.assertTrue(self.test['GPTFoodCode'].isna().all())
        self.assertNotIn('FC_Description', self.test.columns)

    def test_sampling_is_reproducible(self):
        test, dev = asa24_proc.sample(self.link)
        self.assertEqual(test['Image'].tolist(), self.test['Image'].tolist())
        self.assertEqual(dev['Image'].tolist(), self.dev['Image'].tolist())

    def test_reference_weights(self):
        # the image shows Multiplier x the FNDDS 2019-2020 weight of its portion code
        weights = pd.read_csv(FOOD_WEIGHTS_CSV).set_index(['Food Code', 'Portion Code'])['Portion Weight']
        for _, row in pd.concat([self.link, self.test, self.dev]).iterrows():
            unit = 1.0 if row['PortionCode'] == 98 else weights[(row['FoodCode'], row['PortionCode'])]
            self.assertAlmostEqual(row['Weight'], row['Multiplier'] * unit)
        # each portion text of a code names one weight, so C6 can look it up
        self.assertEqual(self.link.groupby(['FoodCode', 'Portion'])['Weight'].nunique().max(), 1)
        self.assertTrue((self.link.groupby('FoodCode')['Weight'].nunique() >= 3).all())
        sampled = pd.concat([self.test, self.dev]).merge(self.link, on=['FoodCode', 'Image'], suffixes=('', '_link'))
        self.assertEqual(len(sampled), 160)
        self.assertTrue((sampled['Portion'] == sampled['Portion_link']).all())

    def test_codes_and_images(self):
        top = set(pd.read_csv(TOP_1000_CSV)['Food code'])
        fndds = set(pd.read_csv(FOODS_CSV)['Food code'])
        self.assertTrue(self.link['FoodCode'].isin(top & fndds).all())
        for link in pd.concat([self.test, self.dev])['Link']:
            self.assertTrue((ROOT / 'code' / link).exists(), link)


class TestB5(unittest.TestCase):

    def setUp(self):
        for path in (DISH_CSV, DEV_DISH_CSV, AVAILABLE_CSV, IMAGE_HASHES):
            need(path)
        self.test = pd.read_csv(DISH_CSV)
        self.dev = pd.read_csv(DEV_DISH_CSV)

    def test_every_metadata_line_is_read(self):
        # on_bad_lines='skip' dropped the dishes with more ingredients than the first line
        for name, lines in (('cafe1', 4768), ('cafe2', 238)):
            df = nutrition5k_proc.read_dish_metadata(ROOT / 'Nutrition5k' / 'metadata' / f'dish_metadata_{name}.csv')
            self.assertEqual(len(df), lines)

    def test_sample(self):
        # CHECKLIST.md principle 5: 150 test dishes, 10 development dishes, no overlap
        self.assertEqual(len(self.test), 150)
        self.assertEqual(len(self.dev), 10)
        self.assertEqual(pd.concat([self.test, self.dev])['dish_id'].nunique(), 160)
        frame = nutrition5k_proc.remove_missing_labels(pd.read_csv(AVAILABLE_CSV))
        test, dev = nutrition5k_proc.sample_dishes(frame)
        self.assertEqual(test['dish_id'].tolist(), self.test['dish_id'].tolist())
        self.assertEqual(dev['dish_id'].tolist(), self.dev['dish_id'].tolist())
        # no dish without nutrient labels; one dish per ingredient list
        labels = self.test[['total_calories', 'total_fat', 'total_carbs', 'total_protein']]
        self.assertFalse((labels == 0).all(axis=1).any())
        self.assertFalse(frame['sorted_ingredients'].duplicated().any())

    def test_images_match_their_hashes(self):
        lines = [line.split() for line in IMAGE_HASHES.read_text().splitlines()]
        self.assertEqual(len(lines), 160)
        links = dict(zip(pd.concat([self.test, self.dev])['dish_id'], pd.concat([self.test, self.dev])['Link']))
        for digest, name, split in lines:
            path = ROOT / 'code' / links[name.split('/')[0]]
            self.assertEqual(place_inputs.sha256(path), digest)
        self.assertEqual([s for *_, s in lines], ['test'] * 150 + ['dev'] * 10)


if __name__ == '__main__':
    unittest.main()
