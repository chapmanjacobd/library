import argparse
from pathlib import Path

from xklb import consts, db, media, usage, utils
from xklb.utils import log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="library places-import", usage=usage.places_import)
    parser.add_argument("database")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    Path(args.database).touch()
    args.db = db.connect(args)

    log.info(utils.dict_filter_bool(args.__dict__))
    return args


def google_maps_takeout(df):
    import pandas as pd

    new_df = pd.DataFrame()

    new_df["path"] = df["Google Maps URL"]
    new_df["time_modified"] = df["Updated"].apply(lambda x: int(x.to_pydatetime().timestamp()))
    new_df["time_downloaded"] = consts.APPLICATION_START
    new_df["title"] = df["Title"].fillna(df["Location"].apply(lambda x: x.get("Business Name")))

    new_df["address"] = df["Location"].apply(
        lambda x: "\n".join(
            [
                value if key == "Address" else f"{key}: {value}"
                for key, value in x.items()
                if key not in ["Business Name", "Geo Coordinates", "Country Code"]
            ],
        ),
    )

    df["geometry"] = df["geometry"].apply(lambda x: x.representative_point())
    new_df["latitude"] = df["geometry"].apply(lambda x: x.y)
    new_df["longitude"] = df["geometry"].apply(lambda x: x.x)

    return new_df


def places_import() -> None:
    args = parse_args()

    import geopandas as gpd

    for path in args.paths:
        file_stats = Path(path).stat()
        df = gpd.read_file(path)

        df = google_maps_takeout(df)
        df["time_created"] = int(file_stats.st_mtime) or int(file_stats.st_ctime)

        data = df.to_dict(orient="records")
        for d in data:
            media.add(args, utils.dict_filter_bool(d))


if __name__ == "__main__":
    places_import()
