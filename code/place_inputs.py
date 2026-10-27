"""Copy the input data from the local copies to where the original scripts read it.

The scripts run from code/ and read ../FNDDS, ../NHANES, ... (git-ignored). The snapshot
holds the official downloads (CHECKLIST.md, 资料位置); each copy is checked by sha256.
"""
import hashlib
import os
import shutil

REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SNAPSHOT = '/home/lelouch/Data/Projects/DietAI24_mac_snapshot_20261022/data'
NUTRITION5K = '/home/lelouch/Documents/Codex/DietAI24_Claude_Handoff_20261023/workspace/work/audit_data'

# (file in the snapshot, file in the repository, sha256)
INPUTS = [
    # B1, B2, C7: FNDDS 2019-2020 At A Glance, under the names the original scripts use
    ('fndds/raw/foods.xlsx', 'FNDDS/2019-2020 FNDDS At A Glance - Foods and Beverages.xlsx',
     '782012f0466093bd090c6b34d7f323e01421850b89a2695c99aa2bc53df127a6'),
    ('fndds/raw/portions.xlsx', 'FNDDS/2019-2020 FNDDS At A Glance - Portions and Weights.xlsx',
     '12f92fe5dafecb29e69fb9e6e59935cb75d9e057773206f94a8454eb07b354fd'),
    ('fndds/raw/nutrients.xlsx', 'FNDDS/2019-2020 FNDDS At A Glance - FNDDS Nutrient Values.xlsx',
     '5007ce9723eb77dc6c3423b3b95a5ef171c71d40ebe4725dc3cc1fe6f9d7161a'),
    # B2: portion codes and weights from the FNDDS 2019-2020 detailed database, extracted from
    # fndds/raw/FNDDS_2019-2020_SAS.EXE (sha256 6e861294...)
    ('fndds/detailed/foodweights.sas7bdat', 'FNDDS/foodweights.sas7bdat',
     'dd38f17b8381f47d723ed00e3dc64517b14743227002f927ee5353d2837af693'),
    ('fndds/detailed/foodportiondesc.sas7bdat', 'FNDDS/foodportiondesc.sas7bdat',
     'd780b0af6176aa4fe4003874e5c8a910bcc298894664dd82544393737fc7d594'),
    # B3: NHANES day-1 individual foods, four cycles
    ('nhanes/raw/DR1IFF_G.XPT', 'NHANES/2011-2012/DR1IFF_G.XPT',
     'bf40537bd378f95377b7c274198ac0e7b3a1fbf70b2ad9d995ccc72943b2c061'),
    ('nhanes/raw/DR1IFF_H.XPT', 'NHANES/2013-2014/DR1IFF_H.XPT',
     '2af08841d72b4b4f03fdeddb3e666e1fee2b86d7b0d99d74b3b6f7125b560af7'),
    ('nhanes/raw/DR1IFF_I.XPT', 'NHANES/2015-2016/DR1IFF_I.XPT',
     '36b516fa303611f075e80ce1c44360a8c964261adcc67b7aa3f2df8b937532f5'),
    ('nhanes/raw/P_DR1IFF.XPT', 'NHANES/2017 March-2020 Pre-pandemic/P_DR1IFF.XPT',
     '264a4dfd66455f106a8ac25a745ebb4e065564b049b45000a5f9c44296d48dec'),
    # B4: ASA24 portion images and their metadata (the same workbook is inside the zip)
    ('asa24/raw/Asa24PortionImages.zip', 'ASA24/Asa24PortionImages.zip',
     '2c0c68caaba894f43a87277a8d2484eded03c630d65fb7a308a590b2457e1c38'),
    ('asa24/ASA24_ImageMetadata.xlsx', 'ASA24/ASA24_ImageMetadata.xlsx',
     'd2382c6808427db7add17d2d29c85a3860674c693cd839fcaa91e28b0938b170'),
    # B5: Nutrition5k dish metadata and the object listing of imagery/realsense_overhead/,
    # fetched from the dataset's bucket for the earlier audit
    (f'{NUTRITION5K}/metadata_dish_metadata_cafe1.csv', 'Nutrition5k/metadata/dish_metadata_cafe1.csv',
     '881df31f27c2343d0ce219964527e0796f6ddadd60701ce6840fa801e8c2a960'),
    (f'{NUTRITION5K}/metadata_dish_metadata_cafe2.csv', 'Nutrition5k/metadata/dish_metadata_cafe2.csv',
     'ef9f800d7b9c2e7e9a9e7cda5cbb4cfe51c760a8c1af4c05786ccf051bf5d77d'),
    (f'{NUTRITION5K}/nutrition5k_objects_overhead_all.json', 'Nutrition5k/metadata/realsense_overhead_objects.json',
     'b4defe5e1142d2bef98d1393f8c01a3f813ce91abea07c1dca664cf38a7b8ec3'),
]


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def place(inputs=INPUTS):
    for source, target, expected in inputs:
        target_path = os.path.join(REPO_DIR, target)
        if os.path.exists(target_path) and sha256(target_path) == expected:
            continue
        source_path = os.path.join(SNAPSHOT, source)
        if sha256(source_path) != expected:
            raise RuntimeError(f'{source_path} does not match its sha256')
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copyfile(source_path, target_path)
        print(f'copied {target}')


if __name__ == '__main__':
    place()
