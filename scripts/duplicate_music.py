import geopandas as gpd

DF = gpd.read_file("audio2.db")

DF["NUQ"] = (
    DF.path.replace(r"\s", "", regex=True)
    .replace(r"\-|\_|\]|\[", "", regex=True)
    .replace(r"\.\d\d\..*$", ".", regex=True)
    .replace(r"\..*$", "", regex=True)
    .replace(r"\/mnt\/d\/.*\/", "", regex=True)
)

DF["dupe"] = DF["NUQ"].duplicated(keep=False)

DF.to_file("audio4.db", driver="SQLite")
