import pytest

from library.__main__ import library as lb
from library.mediadb import download
from library.mediafiles import process_image
from library.utils.consts import DBType
from tests.utils import v_db


@pytest.mark.parametrize(
    "command",
    [
        ["cluster-sort", "--audio"],
        ["cluster-sort", "--video"],
        ["cluster-sort", "--text"],
        ["export-text", "--format", "json", ":memory:"],
        ["download", "--safe", "--filesystem", v_db],
        ["media", "--chromecast", v_db],
        ["similar-files", "tests/data"],
        ["similar-folders", "tests/data"],
    ],
)
def test_unsupported_cli_modes_fail_during_parsing(command):
    with pytest.raises(SystemExit):
        lb(command)


def test_delete_original_is_independent_of_delete_larger(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["process-image", "--no-delete-larger", "--delete-original", "tests/data/test_frame.gif"],
    )

    args = process_image.parse_args()

    assert args.delete_larger is False
    assert args.delete_original is True


def test_download_defaults_to_video(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download", v_db, "--print"])

    args = download.parse_args()

    assert args.profile == DBType.video
