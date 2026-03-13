import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import h3
import glob

H3_RESOLUTION = 8
CONFIDENCE_THRESHOLD = 0.88
MIN_AREA = 110.77                 

csv_files = glob.glob("data_buildings/*.csv")
dfs = [pd.read_csv(f) for f in csv_files]
df = pd.concat(dfs, ignore_index=True)

df = df[(df["confidence"] >= CONFIDENCE_THRESHOLD) & (df["area_in_meters"] >= MIN_AREA)]


df["geometry"] = df.apply(lambda row: Point(row["longitude"], row["latitude"]), axis=1)
gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
gdf["h3index"] = gdf.geometry.apply(lambda p: h3.latlng_to_cell(p.y, p.x, H3_RESOLUTION))


building_count = gdf.groupby("h3index").size().reset_index(name="building_count")

h3_ids_file = pd.read_csv("population_dz.csv")
h3_ids = h3_ids_file["h3index"].tolist()
result = building_count[building_count["h3index"].isin(h3_ids)]


missing_ids = set(h3_ids) - set(result["h3index"])
if missing_ids:
    missing_df = pd.DataFrame({"h3index": list(missing_ids), "building_count": 0})
    result = pd.concat([result, missing_df], ignore_index=True)


result.to_csv("building_count_88.csv", index=False)