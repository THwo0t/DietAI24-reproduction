import pandas as pd

# Define file paths. The At A Glance Portions and Weights table has the same rows but no
# portion codes, which nutrient_estimate.py looks up; the FNDDS 2019-2020 detailed database
# (FNDDS_2019-2020_SAS.EXE) has them.
FOOD_WEIGHTS_PATH = '../FNDDS/foodweights.sas7bdat'
PORTION_DESC_PATH = '../FNDDS/foodportiondesc.sas7bdat'
CSV_FILE_PATH = '../FoodWeights.csv'

def load_data(food_weights_path, portion_desc_path):
    """Load the food weights and join the portion descriptions."""
    weights = pd.read_sas(food_weights_path, encoding='latin-1')
    descriptions = pd.read_sas(portion_desc_path, encoding='latin-1')
    return weights.merge(descriptions[['Portion_code', 'Portion_description']], on='Portion_code', how='left')

def create_food_weights(data):
    """Name the columns as nutrient_estimate.py reads them. FNDDS 2019-2020 has no portion
    subcodes: (Food Code, Portion Code) is unique, so Subcode is 0 and never consulted."""
    data = data.sort_values(['Food_code', 'Seq_num'])
    return pd.DataFrame({
        'Food Code': data['Food_code'].astype(int),
        'Seq Num': data['Seq_num'].astype(int),
        'Portion Code': data['Portion_code'].astype(int),
        'Subcode': 0,
        'Portion Weight': data['Portion_weight'],
        'Portion Description': data['Portion_description'].str.strip(),
    })

def main():
    data = load_data(FOOD_WEIGHTS_PATH, PORTION_DESC_PATH)
    food_weights = create_food_weights(data)
    food_weights.to_csv(CSV_FILE_PATH, index=False)
    print(f"Saved {len(food_weights)} portion weights to {CSV_FILE_PATH}")

if __name__ == "__main__":
    main()
