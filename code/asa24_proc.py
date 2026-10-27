import os
import random
import zipfile
import pandas as pd

# Define file paths. The original scripts read ../df_image_link.csv and ../df_results.csv;
# the script that wrote them is not in the release (CHECKLIST.md B4).
IMAGES_ZIP_PATH = '../ASA24/Asa24PortionImages.zip'
METADATA_PATH = '../ASA24/ASA24_ImageMetadata.xlsx'
TOP_1000_PATH = '../NHANES/top_1000_frequent_select_foods.csv'
FOODS_PATH = '../FNDDS/2019-2020 FNDDS - Foods and Beverages.csv'
FOOD_WEIGHTS_PATH = '../FoodWeights.csv'
IMAGE_DIR = '../ASA24/images'
IMAGE_LINK_PATH = '../df_image_link.csv'
RESULTS_PATH = '../df_results.csv'
DEV_RESULTS_PATH = '../df_results_dev.csv'

# User decision 2026-10-27 (CHECKLIST.md principle 5): 50 codes x 3 portion sizes for the
# test set, 10 images of other codes for the development set
SEED = 20261027
N_CODES = 50
N_DEV = 10
SIZES = ['Largest', 'Medium', 'Smallest']
GRAM_PORTION_CODE = 98  # ASA24 ReadMe: PortionCode 98 = 1 gram


def load_data(metadata_path, images_zip_path):
    """Image rows of the ASA24 metadata, with the portion text of each image."""
    inventory = pd.read_excel(metadata_path, sheet_name='ImageFileInventory')
    codes = pd.read_excel(metadata_path, sheet_name='AssociatedCodes')
    with zipfile.ZipFile(images_zip_path) as z:
        files = {os.path.basename(name) for name in z.namelist() if name.endswith('.png')}
    codes = codes.dropna(subset=['FoodCode']).drop_duplicates()
    codes['FoodCode'] = codes['FoodCode'].astype(int)
    codes = codes.merge(inventory[['FileName', 'Portion']], left_on='Image', right_on='FileName', how='left')
    # PORTION images show one amount of the food; SIZE images (containers) have no portion
    # text and are mostly not in the zip. ModCode != 0 is a recipe modification.
    codes = codes[(codes['ImageType'] == 'PORTION') & (codes['ModCode'] == 0)
                  & codes['Image'].isin(files) & codes['Portion'].notna()]
    codes['Portion'] = codes['Portion'].str.strip()
    return codes.drop(columns=['FileName'])


def add_weights(codes, food_weights):
    """Grams shown in each image: Multiplier x the FNDDS 2019-2020 weight of PortionCode.

    The metadata codes portions in the FNDDS version ASA24 used; a (food code, portion code)
    pair missing from FNDDS 2019-2020 gets no weight, and no mapping is inferred.
    """
    weights = food_weights.set_index(['Food Code', 'Portion Code'])['Portion Weight']
    unit = [weights.get((code, portion)) for code, portion in zip(codes['FoodCode'], codes['PortionCode'])]
    codes = codes.assign(PortionWeight=pd.to_numeric(pd.Series(unit, index=codes.index)))
    codes.loc[codes['PortionCode'] == GRAM_PORTION_CODE, 'PortionWeight'] = 1.0
    codes['Weight'] = codes['Multiplier'] * codes['PortionWeight']
    return codes


def select_image_links(codes, top_codes, fndds_codes):
    """One row per (food code, image): the portion series of each code, weighed in FNDDS 2019-2020.

    Only the images with a weight enter a code's series; an image whose rows (several
    portion codes) disagree on its weight by more than 1% is left out. A code qualifies when
    it is among the top 1000 and in FNDDS 2019-2020, each portion text in its series has a
    single weight, and the series has at least three distinct weights. Each image keeps the
    row of the code's most frequent portion code, so Multiplier, which rag_portion_size.py
    sorts by, is on one scale wherever possible.
    """
    codes = codes[codes['FoodCode'].isin(top_codes) & codes['FoodCode'].isin(fndds_codes)
                  & codes['Weight'].notna()]
    rows = []
    for food_code, df in codes.groupby('FoodCode'):
        spread = df.groupby('Image')['Weight'].agg(lambda w: w.max() / w.min() - 1)
        df = df[df['Image'].isin(spread[spread <= 0.01].index)]
        frequency = df['PortionCode'].value_counts()
        df = df.assign(rank=-df['PortionCode'].map(frequency)).sort_values(['rank', 'PortionCode'])
        series = df.drop_duplicates('Image').drop(columns='rank').sort_values('Image')
        if series.groupby('Portion')['Weight'].nunique().max() > 1 or series['Weight'].nunique() < 3:
            continue
        rows.append(series)
    df_image_link = pd.concat(rows, ignore_index=True)
    df_image_link['Link'] = [os.path.join(IMAGE_DIR, image) for image in df_image_link['Image']]
    return df_image_link[['FoodCode', 'FC_Description', 'Category', 'Image', 'Portion', 'PortionCode',
                          'PortionSubCode', 'Multiplier', 'PortionWeight', 'Weight', 'Link']]


def portion_sizes(df_code):
    """The largest, median and smallest portion of one code, over its distinct weights (lower
    median when their number is even); the first image by name when several share a weight."""
    weights = sorted(df_code['Weight'].unique(), reverse=True)
    picks = [weights[0], weights[len(weights) // 2], weights[-1]]
    df_code = df_code.sort_values('Image')
    return pd.concat([df_code[df_code['Weight'] == w].head(1) for w in picks]).assign(Size=SIZES)


def sample(df_image_link, seed=SEED, n_codes=N_CODES, n_dev=N_DEV):
    """Test set: n_codes codes x 3 sizes. Development set: n_dev further codes, one image each
    (sizes in turn), skipping codes whose image is also in the test set."""
    codes = random.Random(seed).sample(sorted(df_image_link['FoodCode'].unique()), df_image_link['FoodCode'].nunique())
    test = pd.concat([portion_sizes(df_image_link[df_image_link['FoodCode'] == c]) for c in codes[:n_codes]],
                     ignore_index=True)
    dev = []
    for food_code in codes[n_codes:]:
        size = SIZES[len(dev) % 3]
        row = portion_sizes(df_image_link[df_image_link['FoodCode'] == food_code]).query('Size == @size')
        if row['Image'].isin(test['Image']).any():
            continue
        dev.append(row)
        if len(dev) == n_dev:
            break
    return test, pd.concat(dev, ignore_index=True)


def create_results(df):
    """The table rag_food_code.py fills in (Link, GPTFoodDescription, GPTFoodCode). The
    reference columns are read only by the portion step's protocol (C5) and the evaluation."""
    df = df.drop(columns=['FC_Description', 'Category']).copy()
    df['GPTFoodDescription'] = pd.NA
    df['GPTFoodCode'] = pd.NA
    return df


def extract_images(images_zip_path, image_dir, images):
    os.makedirs(image_dir, exist_ok=True)
    with zipfile.ZipFile(images_zip_path) as z:
        members = {os.path.basename(name): name for name in z.namelist() if name.endswith('.png')}
        for image in sorted(set(images)):
            with open(os.path.join(image_dir, image), 'wb') as f:
                f.write(z.read(members[image]))


def main():
    codes = load_data(METADATA_PATH, IMAGES_ZIP_PATH)
    codes = add_weights(codes, pd.read_csv(FOOD_WEIGHTS_PATH))
    top_codes = set(pd.read_csv(TOP_1000_PATH)['Food code'])
    fndds_codes = set(pd.read_csv(FOODS_PATH)['Food code'])
    df_image_link = select_image_links(codes, top_codes, fndds_codes)
    test, dev = sample(df_image_link)
    extract_images(IMAGES_ZIP_PATH, IMAGE_DIR, pd.concat([df_image_link['Image'], test['Image'], dev['Image']]))
    df_image_link.to_csv(IMAGE_LINK_PATH, index=False)
    create_results(test).to_csv(RESULTS_PATH, index=False)
    create_results(dev).to_csv(DEV_RESULTS_PATH, index=False)
    print(f"{df_image_link['FoodCode'].nunique()} codes qualify; test {len(test)} images of "
          f"{test['FoodCode'].nunique()} codes, development {len(dev)} images")


if __name__ == "__main__":
    main()
