"""Maintainer only: select documented success/failure examples and freeze offline evidence."""
import csv
import hashlib
import json
import math
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]

def rows(path):
    with path.open(newline='') as stream:return list(csv.DictReader(stream))

def number(s):
    try:
        v=float(s);return v if math.isfinite(v) else None
    except (TypeError,ValueError):return None

def complete(r):return number(r['IngredientNum'])>0 and number(r['WeightError'])==number(r['FoodCodeError'])==0

def main():
    run_dirs=[ROOT/'runs/test',ROOT/'runs/test-gpt-6.1-sol']
    examples=[]
    for dataset,key in [('asa24','Image'),('nutrition5k','dish_id')]:
        tables=[rows(run/(dataset+'_nutrition.csv')) for run in run_dirs]
        maps=[{r[key]:r for r in table} for table in tables]
        okay=(lambda r:number(r['TotalWeight']) is not None) if dataset=='asa24' else complete
        chosen=[]
        for both in [True,False]:
            selected=next(r for r in tables[0] if okay(r) and okay(maps[1][r[key]])==both)
            chosen.append((selected,'First saved row valid for both models.' if both else 'First saved row valid for GPT-4o but not Sol.'))
        for r,why in chosen:
            name=f'demo/images/{dataset}-{r[key]}.png'
            path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True)
            source=(ROOT/'code'/r['Link']).resolve()
            with Image.open(source) as image:
                image.thumbnail((512,512));image.save(path)
            predictions=[]
            for i,mapping in enumerate(maps):
                answer=mapping[r[key]]
                predictions.append({'model':['GPT-4o','Sol'][i],
                    'status':('Exact conditional estimate' if dataset=='asa24' else 'Complete dish') if okay(answer) else 'Excluded from main MAE',
                    'weight_g':number(answer['TotalWeight' if dataset=='asa24' else 'GPTWeight']),
                    'description':answer.get('GPTFoodDescription',''),'food_codes':answer['GPTFoodCode'],
                    'portion':answer.get('GPTPortionDescription',answer.get('GPTWeightDescription',''))})
            examples.append({'dataset':dataset,'id':r[key],'image':name,
                             'reference_weight_g':number(r['Weight' if dataset=='asa24' else 'total_mass']),
                             'selection':why,'predictions':predictions})
    (ROOT/'demo/examples.json').write_text(json.dumps(examples,indent=2,allow_nan=False)+'\n')
    names=['REPORT.md','demo/examples.json','runs/comparison-gpt-4o-vs-sol/comparison.json']
    for run in run_dirs:
        names.extend(str((run/name).relative_to(ROOT)) for name in
                     ['metrics.json','asa24_nutrition.csv','nutrition5k_nutrition.csv','config.json','cost.json'])
    names.extend(item['image'] for item in examples)
    names.extend('output/report/REPORT.'+ext for ext in ['md','pdf','docx'])
    manifest={'description':'Archived evidence and derived image previews. No new model inference.',
              'files':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}}
    (ROOT/'demo/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Prepared',len(examples),'examples and',len(names),'evidence hashes.')

if __name__=='__main__':main()
