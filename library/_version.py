# Copyright (c) 2026, Jacob Chapman

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from pathlib import Path
import tomllib


def get_version() -> str:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    if pyproject_path.is_file():
        with pyproject_path.open("rb") as pyproject_file:
            project_version = tomllib.load(pyproject_file)["project"].get("version")
        if isinstance(project_version, str):
            return project_version
        message = f"Missing string project version in {pyproject_path}"
        raise RuntimeError(message)

    try:
        return installed_version("library")
    except PackageNotFoundError as error:
        raise RuntimeError("Unable to determine the library version") from error


__version__ = get_version()
