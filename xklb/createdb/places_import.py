import argparse
from pathlib import Path

from xklb import usage
from xklb.mediadb import db_media
from xklb.utils import arggroups, argparse_utils, consts, nums, objects


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(prog="library places-import", usage=usage.places_import)
    arggroups.database(parser)
    parser.add_argument("paths", nargs="+")
    arggroups.debug(parser)
    args = parser.parse_intermixed_args()

    arggroups.args_post(args, parser, create_db=True)
    return args


def google_maps_takeout(df):
    import pandas as pd

    new_df = pd.DataFrame()

    new_df["path"] = df["Google Maps URL"]
    new_df["time_modified"] = df["Updated"].apply(lambda x: nums.to_timestamp(x.to_pydatetime()))
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
            db_media.add(args, objects.dict_filter_bool(d))


if __name__ == "__main__":
    places_import()
