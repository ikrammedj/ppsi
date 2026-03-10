import pandas as pd
import os

# lire le csv
df = pd.read_csv("population_dz.csv")

# créer un dossier pour les wilayas
os.makedirs("wilayas_csv", exist_ok=True)

# pour chaque wilaya
for wilaya, data in df.groupby("Wilaya_58"):
    
    # nettoyer le nom pour le fichier
    filename = wilaya.replace(" ", "_")
    
    # sauvegarder le csv
    data.to_csv(f"wilayas_csv/{filename}.csv", index=False)

print("Tous les fichiers ont été créés.")