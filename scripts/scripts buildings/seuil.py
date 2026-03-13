import pandas as pd
import glob
import matplotlib.pyplot as plt

# Paramètres
CSV_FOLDER = "data/*.csv"
SAMPLE_SIZE = 100000
CONFIDENCE_PERCENTILE = 0.9
AREA_TOP_PERCENTILE = 0.75
OUTPUT_FOLDER = "histograms"  

import os
os.makedirs(OUTPUT_FOLDER, exist_ok=True)  

csv_files = glob.glob(CSV_FOLDER)
dfs = []

for f in csv_files:
    df = pd.read_csv(f, nrows=SAMPLE_SIZE)
    dfs.append(df)

df = pd.concat(dfs, ignore_index=True)

recommended_confidence = df["confidence"].quantile(CONFIDENCE_PERCENTILE)
recommended_area = df["area_in_meters"].quantile(AREA_TOP_PERCENTILE)

print(f"Seuil recommandé confiance : {recommended_confidence:.2f}")
print(f"Seuil recommandé surface : {recommended_area:.2f} m²")

plt.figure(figsize=(10,4))
df["confidence"].hist(bins=50)
plt.title("Distribution de la confiance des bâtiments")
plt.xlabel("Confidence")
plt.ylabel("Nombre de bâtiments")
plt.tight_layout()
plt.savefig(f"{OUTPUT_FOLDER}/hist_confidence.png")  
plt.close() 


plt.figure(figsize=(10,4))
df["area_in_meters"].hist(bins=50)
plt.title("Distribution de la surface des bâtiments (area_in_meters)")
plt.xlabel("Surface (m²)")
plt.ylabel("Nombre de bâtiments")
plt.tight_layout()
plt.savefig(f"{OUTPUT_FOLDER}/hist_area.png")  
plt.close()