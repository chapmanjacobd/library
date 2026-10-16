import argparse

import pytest

from library.__main__ import library as lb
from library import usage
from library.editdb import dedupe_media
from library.mediadb import download
from library.mediafiles import process_image
from library.text import cluster_sort, extract_links
from library.utils import arggroups, consts, objects
from library.utils.consts import DBType, SC
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


def test_download_defaults_to_auto(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download", v_db, "--print"])

    args = download.parse_args()

    assert args.profile == DBType.auto


def test_download_media_type_auto(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download", "--media-type", "auto", v_db, "--print"])

    args = download.parse_args()

    assert args.profile == DBType.auto


def test_extract_links_parse_args_compatibility(monkeypatch):
    monkeypatch.setattr("sys.argv", ["extract-links", "https://example.com/"])

    args = extract_links.parse_args()

    assert args.download is False
    assert args.direct is False


def test_download_links_defaults_to_auto(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download-links", v_db, "--print"])

    args = download.parse_args(usage.download_links, links=True)

    assert args.profile == DBType.auto


def test_links_download_defaults_to_auto(monkeypatch):
    monkeypatch.setattr("sys.argv", ["links-download", "https://example.com/"])

    args = extract_links.parse_args_links_download()

    assert args.profile == DBType.auto


def test_links_download_accepts_direct(monkeypatch):
    monkeypatch.setattr("sys.argv", ["links-download", "--direct", "https://example.com/"])

    args = extract_links.parse_args_links_download()

    assert args.direct is True


def test_links_download_accepts_text(monkeypatch):
    monkeypatch.setattr("sys.argv", ["links-download", "--text", "https://example.com/"])

    args = extract_links.parse_args_links_download()

    assert args.profile == DBType.text


def test_direct_download_has_no_profile_or_safe(monkeypatch):
    """direct-download only uses the built-in downloader, so it must not advertise
    profile/media-type/safe options that would be ignored."""
    monkeypatch.setattr("sys.argv", ["direct-download", "https://example.com/x"])

    args = extract_links.parse_args_direct_download()

    assert args.direct is True
    assert not hasattr(args, "profile")
    assert not hasattr(args, "safe")


def test_expand_profiles_auto_expands_to_all_media_types(monkeypatch):
    monkeypatch.setattr(arggroups, "text_profile_available", lambda: True)
    monkeypatch.setattr(arggroups, "image_profile_available", lambda: True)
    expanded = arggroups.expand_profiles([DBType.auto])

    assert set(expanded) == {DBType.video, DBType.audio, DBType.image, DBType.text}
    assert DBType.filesystem not in expanded


def test_expand_profiles_auto_skips_text_without_deps(monkeypatch):
    monkeypatch.setattr(arggroups, "text_profile_available", lambda: False)
    monkeypatch.setattr(arggroups, "image_profile_available", lambda: True)
    expanded = arggroups.expand_profiles([DBType.auto])

    assert set(expanded) == {DBType.video, DBType.audio, DBType.image}
    assert DBType.text not in expanded


def test_expand_profiles_auto_skips_image_without_deps(monkeypatch):
    monkeypatch.setattr(arggroups, "text_profile_available", lambda: True)
    monkeypatch.setattr(arggroups, "image_profile_available", lambda: False)
    expanded = arggroups.expand_profiles([DBType.auto])

    assert set(expanded) == {DBType.video, DBType.audio, DBType.text}
    assert DBType.image not in expanded


def test_expand_profiles_explicit_text_is_kept_without_deps(monkeypatch):
    monkeypatch.setattr(arggroups, "text_profile_available", lambda: False)

    assert arggroups.expand_profiles([DBType.text]) == [DBType.text]


def test_expand_profiles_explicit_image_is_kept_without_deps(monkeypatch):
    monkeypatch.setattr(arggroups, "image_profile_available", lambda: False)

    assert arggroups.expand_profiles([DBType.image]) == [DBType.image]


def test_expand_profiles_require_deps_false_keeps_optional(monkeypatch):
    monkeypatch.setattr(arggroups, "text_profile_available", lambda: False)
    monkeypatch.setattr(arggroups, "image_profile_available", lambda: False)

    expanded = arggroups.expand_profiles([DBType.auto], require_deps=False)

    assert set(expanded) == {DBType.video, DBType.audio, DBType.image, DBType.text}


def test_resolve_profiles_require_deps_false_keeps_all_media_types(monkeypatch):
    """Extension-only commands (merge-mv) must not drop text/image just because the
    optional extraction deps are missing."""
    monkeypatch.setattr(arggroups, "text_profile_available", lambda: False)
    monkeypatch.setattr(arggroups, "image_profile_available", lambda: False)

    resolved = arggroups.resolve_profiles(SC.merge_mv, [DBType.auto], require_deps=False)

    assert set(resolved) == {DBType.video, DBType.audio, DBType.image, DBType.text}


def test_profile_extensions_maps_media_types():
    exts = arggroups.profile_extensions([DBType.text], ocr=True, speech_recognition=True)

    assert consts.TEXTRACT_EXTENSIONS <= exts
    assert consts.OCR_EXTENSIONS <= exts
    assert consts.SPEECH_RECOGNITION_EXTENSIONS <= exts

    video_only = arggroups.profile_extensions([DBType.video])
    assert consts.VIDEO_EXTENSIONS <= video_only
    # filesystem is not a media type and contributes no extensions
    assert arggroups.profile_extensions([DBType.filesystem]) == set()


def test_fs_add_defaults_to_auto():
    assert arggroups.default_profile(SC.fs_add) == [DBType.auto]
    assert arggroups.default_profile(SC.fs_update) == [DBType.auto]


def test_merge_mv_defaults_to_filesystem():
    assert arggroups.default_profile(SC.merge_mv) == [DBType.filesystem]
    assert arggroups.expand_profiles(arggroups.default_profile(SC.merge_mv)) == [DBType.filesystem]


def test_download_media_type_includes_text(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download", "--media-type", "text", v_db, "--print"])

    args = download.parse_args()

    assert args.profile == DBType.text


def test_download_text_alias_selects_text_profile(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download", "--text", v_db, "--print"])

    args = download.parse_args()

    assert args.profile == DBType.text
    assert args.direct is False


def test_download_links_text_alias_selects_text_profile(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download-links", "--text", v_db, "--print"])

    args = download.parse_args(usage.download_links, links=True)

    assert args.profile == DBType.text


@pytest.mark.parametrize("extra", [["--direct"], ["--text"], ["--filesystem"], ["--media-type", "text"]])
def test_download_safe_rejects_unsupported_profiles(monkeypatch, extra):
    monkeypatch.setattr("sys.argv", ["download", "--safe", v_db, *extra, "--print"])

    with pytest.raises(SystemExit):
        download.parse_args()


@pytest.mark.parametrize("extra", [[], ["--audio"], ["--video"], ["--image"], ["--media-type", "auto"]])
def test_download_safe_accepts_supported_profiles(monkeypatch, extra):
    monkeypatch.setattr("sys.argv", ["download", "--safe", v_db, *extra, "--print"])

    args = download.parse_args()

    assert args.safe is True


def test_dedupe_media_rejects_text_profile(monkeypatch):
    monkeypatch.setattr("sys.argv", ["dedupe-media", "--text", v_db])

    with pytest.raises(SystemExit):
        dedupe_media.parse_args()


def test_dedupe_media_does_not_offer_soft_delete_flags(monkeypatch):
    """dedupe-media always soft-deletes the rows it removes, so the generic
    --mark-deleted/--delete-rows/--mark-watched flags are not advertised."""
    monkeypatch.setattr("sys.argv", ["dedupe-media", "--audio", v_db])

    args = dedupe_media.parse_args()

    assert not hasattr(args, "mark_deleted")
    assert not hasattr(args, "delete_rows")
    assert not hasattr(args, "mark_watched")


def test_is_profile_auto_matches_scannable_types():
    args = argparse.Namespace(profile=DBType.auto)

    assert objects.is_profile(args, DBType.video)
    assert objects.is_profile(args, DBType.audio)
    assert objects.is_profile(args, DBType.image)
    # text matches `auto` too; the extractor itself skips when textract is unavailable
    assert objects.is_profile(args, DBType.text)
    assert not objects.is_profile(args, DBType.filesystem)


def test_cluster_sort_image_is_an_explicit_flag(monkeypatch):
    monkeypatch.setattr("sys.argv", ["cluster-sort", "--image"])

    args = cluster_sort.parse_args()

    assert args.image is True


def test_cluster_sort_defaults_to_lines(monkeypatch):
    monkeypatch.setattr("sys.argv", ["cluster-sort"])

    args = cluster_sort.parse_args()

    assert args.image is False
    assert not hasattr(args, "lines")


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
