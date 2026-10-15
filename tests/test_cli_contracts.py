import pytest

from library.__main__ import library as lb
from library.editdb import dedupe_media
from library.mediadb import download
from library.mediafiles import process_image
from library.text import cluster_sort
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


def test_download_links_defaults_to_filesystem(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download-links", v_db, "--print"])

    args = download.parse_args(download.USAGE["download_links"], links=True)

    assert args.profile == DBType.filesystem


def test_download_media_type_includes_text(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download", "--media-type", "text", v_db, "--print"])

    args = download.parse_args()

    assert args.profile == DBType.text


def test_download_text_alias_selects_direct(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download", "--text", v_db, "--print"])

    args = download.parse_args()

    assert args.direct is True


def test_dedupe_media_type_leaves_strategy_unset(monkeypatch):
    monkeypatch.setattr("sys.argv", ["dedupe-media", "--audio", v_db])

    args = dedupe_media.parse_args()

    assert args.profile == DBType.audio
    assert args.strategy is None


def test_dedupe_strategy_is_not_a_profile(monkeypatch):
    monkeypatch.setattr("sys.argv", ["dedupe-media", "--id", v_db])

    args = dedupe_media.parse_args()

    assert args.profile is None
    assert args.strategy == "extractor_id"


def test_cluster_sort_image_is_not_a_profile(monkeypatch):
    monkeypatch.setattr("sys.argv", ["cluster-sort", "--image"])

    args = cluster_sort.parse_args()

    assert args.image is True
    assert not hasattr(args, "profile")
