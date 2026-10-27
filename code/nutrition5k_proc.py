import csv
import hashlib
import json
import os
import random
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import requests

# Define file paths
PATH_DISH_1 = '../Nutrition5k/metadata/dish_metadata_cafe1.csv'
PATH_DISH_2 = '../Nutrition5k/metadata/dish_metadata_cafe2.csv'
OUTPUT_PATH = '../Nutrition5k/metadata/dish_metadata_available.csv'
# Object listing of imagery/realsense_overhead/ in the dataset's bucket (place_inputs.py)
PATH_OBJECTS = '../Nutrition5k/metadata/realsense_overhead_objects.json'
IMAGE_URL = 'https://storage.googleapis.com/nutrition5k_dataset/nutrition5k_dataset/imagery/realsense_overhead'
IMAGE_DIR = '../Nutrition5k/imagery/realsense_overhead'
SAMPLE_PATH = '../dish_metadata.csv'
DEV_SAMPLE_PATH = '../dish_metadata_dev.csv'
HASH_PATH = '../samples/nutrition5k_images.sha256'

# User decision 2026-10-27 (CHECKLIST.md principle 5): 150 test dishes, 10 development dishes
SEED = 20261027
N_TEST = 150
N_DEV = 10

def read_dish_metadata(path):
    """Read every line of a dish metadata CSV. Lines grow by 7 fields per ingredient, so
    they are read as wide as the longest; on_bad_lines='skip' dropped every dish with more
    ingredients than the file's first line (423 of 5006)."""
    with open(path) as f:
        width = max(len(row) for row in csv.reader(f))
    return pd.read_csv(path, header=None, names=range(width))

def process_dish_data(df_dish):
    """Process dish data to extract relevant information."""
    dish_properties = {
        'dish_id': [],
        'total_calories': [],
        'total_mass': [],
        'total_fat': [],
        'total_carbs': [],
        'total_protein': [],
        'ingredients': [],
        'sorted_ingredients': []
    }

    for _, row in df_dish.iterrows():
        ingredients = [
            row[i + 1] for i in range(1, len(row) - 1)
            if isinstance(row[i], str) and row[i].startswith("ingr_") and isinstance(row[i + 1], str)
        ]
        if ingredients:
            dish_properties['dish_id'].append(row[0])
            dish_properties['total_calories'].append(row[1])
            dish_properties['total_mass'].append(row[2])
            dish_properties['total_fat'].append(row[3])
            dish_properties['total_carbs'].append(row[4])
            dish_properties['total_protein'].append(row[5])
            sorted_ingredients = sorted(ingredients)
            dish_properties['ingredients'].append(ingredients)
            dish_properties['sorted_ingredients'].append(sorted_ingredients)

    df_ingredients = pd.DataFrame(dish_properties)
    df_ingredients['ingredients'] = df_ingredients['ingredients'].apply(', '.join)
    df_ingredients['sorted_ingredients'] = df_ingredients['sorted_ingredients'].apply(', '.join)

    return df_ingredients

def remove_duplicate_ingredients(df):
    """Remove duplicate ingredients based on sorted ingredients and total mass."""
    df_sorted = df.sort_values(by=['sorted_ingredients', 'total_mass'], ascending=[True, False])
    df_unique = df_sorted.drop_duplicates(subset='sorted_ingredients', keep='first')
    df_unique = df_unique.sort_values(by='dish_id')
    return df_unique

def image_available(dish_id):
    """HEAD request: the overhead RGB image exists (nothing is downloaded)."""
    return requests.head(f'{IMAGE_URL}/{dish_id}/rgb.png', timeout=30).status_code == 200

def filter_unavailable_images(df):
    """Filter out dishes with unavailable images."""
    df = df.reset_index(drop=True)  # remove_duplicate_ingredients keeps the old index labels
    with ThreadPoolExecutor(max_workers=8) as pool:
        available = list(pool.map(image_available, df['dish_id']))
    for dish_id, ok in zip(df['dish_id'], available):
        if not ok:
            print(f'Image URL is not accessible for dish_id: {dish_id}')

    df_filtered = df[available]
    df_filtered.reset_index(drop=True, inplace=True)
    return df_filtered

def remove_missing_labels(df):
    """Dishes whose calories, fat, carbohydrate and protein are all 0 while the mass is not
    have no nutrient label (CHECKLIST.md B5)."""
    nutrients = df[['total_calories', 'total_fat', 'total_carbs', 'total_protein']]
    missing = (nutrients == 0).all(axis=1) & (df['total_mass'] > 0)
    print(f'{missing.sum()} dishes without nutrient labels removed')
    return df[~missing].reset_index(drop=True)

def sample_dishes(df, seed=SEED, n_test=N_TEST, n_dev=N_DEV):
    """Random test and development dishes, without overlap (paper.txt:235-237)."""
    dish_ids = random.Random(seed).sample(sorted(df['dish_id']), n_test + n_dev)
    df = df.set_index('dish_id')
    return [df.loc[ids].reset_index() for ids in (dish_ids[:n_test], dish_ids[n_test:])]

def download_images(dish_ids):
    """Download the overhead RGB images; return their sha256."""
    hashes = {}
    for dish_id in dish_ids:
        path = os.path.join(IMAGE_DIR, dish_id, 'rgb.png')
        if not os.path.exists(path):
            response = requests.get(f'{IMAGE_URL}/{dish_id}/rgb.png', timeout=60)
            response.raise_for_status()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'wb') as f:
                f.write(response.content)
        with open(path, 'rb') as f:
            hashes[dish_id] = hashlib.sha256(f.read()).hexdigest()
    return hashes

def create_results(df):
    """The table rag_food_code.py fills in (Link, GPTFoodDescription, GPTFoodCode)."""
    df = df.copy()
    df['Link'] = [os.path.join(IMAGE_DIR, dish_id, 'rgb.png') for dish_id in df['dish_id']]
    df['GPTFoodDescription'] = pd.NA
    df['GPTFoodCode'] = pd.NA
    return df

def main():
    df_dish_1 = read_dish_metadata(PATH_DISH_1)
    df_dish_2 = read_dish_metadata(PATH_DISH_2)
    df_ingredients_1 = process_dish_data(df_dish_1)
    df_ingredients_2 = process_dish_data(df_dish_2)
    df_ingredients = pd.concat([df_ingredients_1, df_ingredients_2], ignore_index=True)

    df_ingredients = remove_duplicate_ingredients(df_ingredients)
    df_ingredients_available = filter_unavailable_images(df_ingredients)
    with open(PATH_OBJECTS) as f:
        listed = {item['name'].split('/')[-2] for item in json.load(f) if item['name'].endswith('/rgb.png')}
    if set(df_ingredients_available['dish_id']) != set(df_ingredients['dish_id']) & listed:
        raise RuntimeError('HEAD results differ from the bucket listing')
    df_ingredients_available.to_csv(OUTPUT_PATH, index=False)
    print("Processed data saved to:", OUTPUT_PATH)

    df_labeled = remove_missing_labels(df_ingredients_available)
    df_test, df_dev = sample_dishes(df_labeled)
    hashes = download_images(pd.concat([df_test['dish_id'], df_dev['dish_id']]))
    create_results(df_test).to_csv(SAMPLE_PATH, index=False)
    create_results(df_dev).to_csv(DEV_SAMPLE_PATH, index=False)
    os.makedirs(os.path.dirname(HASH_PATH), exist_ok=True)
    with open(HASH_PATH, 'w') as f:
        for split, df in (('test', df_test), ('dev', df_dev)):
            for dish_id in df['dish_id']:
                f.write(f'{hashes[dish_id]}  {dish_id}/rgb.png  {split}\n')
    print(f'{len(df_ingredients)} unique dishes, {len(df_ingredients_available)} with an overhead image, '
          f'{len(df_labeled)} labeled; sampled {len(df_test)} test and {len(df_dev)} development dishes')

if __name__ == "__main__":
    main()
