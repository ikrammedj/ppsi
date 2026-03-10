import geopandas as gpd
import folium

# lire le shapefile
gdf = gpd.read_file("population_stage/population_dz.shp")

# centre de la carte (Algérie)
m = folium.Map(location=[28, 2], zoom_start=5)

# ajouter le shapefile
folium.GeoJson(gdf).add_to(m)

folium.GeoJson(
    gdf,
    tooltip=folium.GeoJsonTooltip(fields=["h3index", "Wilaya_58", "Commune_1", 'pop_dens'], aliases=["H3 Index", "wilaya", "commune", "densité de population"]),
).add_to(m)

# sauvegarder la carte
m.save("carte.html")