import geopandas as gpd

gdf = gpd.read_file("population/population_dz.shp")

df = gdf.drop(columns="geometry")

df.to_csv("population_dz.csv", index=False, encoding="utf-8")

print("CSV créé : population_dz.csv")