import geopandas as gpd

# lire le shapefile
gdf = gpd.read_file("population_stage/population_dz.shp")

# voir les colonnes
print(gdf.columns)

# voir les premières lignes
print(gdf.head())

# exporter en csv
gdf.drop(columns="geometry").to_csv("population_dz.csv", index=False)

print("CSV créé : population_dz.csv")