import pandas as pd

CSV_FILE = "population_dz.csv"

print("Loading CSV...")
df = pd.read_csv(CSV_FILE)

total_lignes = len(df)
unique_h3 = df["h3index"].nunique()

doublons = total_lignes - unique_h3

print("Total lignes :", total_lignes)
print("H3 uniques   :", unique_h3)
print("Doublons     :", doublons)
