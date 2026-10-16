import argparse
import re
import subprocess
import sys
from pathlib import Path

import pytest

from library import __main__
from library.__main__ import library as lb
from library.__main__ import _nested_group, _nested_target
from library import usage
from library.editdb import dedupe_media
from library.mediadb import download
from library.mediafiles import process_image
from library.playback import playback_control
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


def test_removed_surf_command_is_rejected():
    with pytest.raises(SystemExit) as exc_info:
        lb(["surf", "-h"])

    assert exc_info.value.code == 1


def test_removed_flat_search_is_rejected(capsys):
    # `search` collided with the `captions` resource; it is only reachable as `captions`
    with pytest.raises(SystemExit) as exc_info:
        lb(["search", v_db])

    assert exc_info.value.code == 1
    assert "subcommands" in capsys.readouterr().out


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


def test_nested_command_dispatches_to_canonical_target(monkeypatch):
    called = []
    monkeypatch.setattr("library.playback.play_actions.watch", lambda: called.append(sys.argv[1:]))

    lb(["play", "video", "video.db"])

    assert called == [["video.db"]]


def test_legacy_flat_command_dispatches_to_existing_target(monkeypatch):
    called = []
    monkeypatch.setattr("library.playback.play_actions.watch", lambda: called.append(sys.argv[1:]))

    lb(["watch", "video.db"])

    assert called == [["video.db"]]


def test_nested_links_download_dispatches_to_existing_entrypoint(monkeypatch):
    called = []
    monkeypatch.setattr("library.text.extract_links.links_download", lambda: called.append(sys.argv[1:]))

    lb(["links", "download", "https://example.com/"])

    assert called == [["https://example.com/"]]


def test_nested_direct_download_dispatches_to_existing_entrypoint(monkeypatch):
    called = []
    monkeypatch.setattr("library.text.extract_links.direct_download", lambda: called.append(sys.argv[1:]))

    lb(["download", "https://example.com/file.zip"])

    assert called == [["https://example.com/file.zip"]]


def test_download_without_db_is_direct(monkeypatch):
    called = []
    monkeypatch.setattr(
        "library.text.extract_links._download_paths",
        lambda _args, _cache: called.append(sys.argv[1:]),
    )

    lb(["download", "https://example.com/file.zip"])

    assert called == [["https://example.com/file.zip"]]


def test_download_with_db_delegates_to_database_download(monkeypatch):
    called = []
    monkeypatch.setattr("library.mediadb.download.download", lambda: called.append(sys.argv[1:]))

    lb(["download", "--db", "dl.db", "--prefix", "/tmp/out"])

    # the db override is injected as the database positional, everything else is preserved
    assert called == [["dl.db", "--prefix", "/tmp/out"]]


def test_nested_group_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(["database", "-h"])

    assert exc_info.value.code == 0
    assert "usage: library database <command>" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("path", "usage_prefix"),
    [
        (["database", "add", "-h"], "usage: library database add <command>"),
        (["database", "filesystem", "-h"], "usage: library database filesystem <command>"),
        (["folder", "merge", "-h"], "usage: library folder merge <command>"),
        (["text", "sort", "-h"], "usage: library text sort <command>"),
    ],
)
def test_nested_intermediate_group_help(path, usage_prefix, capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(path)

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.startswith(usage_prefix)


def test_nested_playback_parsers_register_route_specific_arguments(monkeypatch):
    monkeypatch.setattr(
        playback_control.mpv_utils,
        "connect_default_mpv",
        lambda socket: (socket or "/tmp/test-mpv.sock", object()),
    )

    monkeypatch.setattr("sys.argv", ["library playback seek", "10"])
    seek_args = playback_control.parse_args(usage.seek, command="seek")
    assert seek_args.time == "10"

    monkeypatch.setattr("sys.argv", ["library playback next", "--delete"])
    next_args = playback_control.parse_args(usage.next, command="next")
    assert next_args.delete_files is True


def test_help_without_query_prints_top_level_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(["help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert output == f"{__main__.usage()}\n{__main__.parser.epilog}\n"


@pytest.mark.parametrize(
    ("nested", "usage_prefix"),
    [
        (["play", "video", "-h"], "usage: library play video"),
        (["database", "search", "-h"], "usage: library database search"),
        (["database", "filesystem", "list", "-h"], "usage: library database filesystem list"),
        (["file", "hash", "-h"], "usage: library file hash"),
        (["text", "sort", "regex", "-h"], "usage: library text sort regex"),
        (["playback", "next", "-h"], "usage: library playback next"),
        (["folder", "merge", "copy", "-h"], "usage: library folder merge copy"),
        (["folder", "move", "list", "-h"], "usage: library folder move list"),
        (["folder", "merge", "relative-move", "-h"], "usage: library folder merge relative-move"),
        (["shrink", "audio", "-h"], "usage: library shrink audio"),
        (["help", "search", "-h"], "usage: library help search"),
    ],
)
def test_nested_leaf_help_uses_canonical_usage(nested, usage_prefix, capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(nested)

    assert exc_info.value.code == 0
    first_line = capsys.readouterr().out.splitlines()[0]
    assert first_line.startswith(usage_prefix)
    assert first_line.count(" ".join(nested[:-1])) == 1


def test_help_search_accepts_ordinary_searches(capsys):
    lb(["help", "search", "database"])

    output = capsys.readouterr().out
    assert "Add local media with lb database add filesystem" in output
    assert "library database add filesystem" in output
    assert "Bug found" not in output


def test_help_query_without_search_keyword_searches(capsys):
    # `help <query>` is the v3 spelling for `help search <query>`
    lb(["help", "audio"])

    assert "Listen to audio with lb play audio" in capsys.readouterr().out


def test_help_search_selects_canonical_nested_paths(capsys):
    lb(["help", "search", "database", "add", "video"])

    output = capsys.readouterr().out
    assert output.startswith("usage: library database add video")


def test_help_search_indexes_nested_only_commands(capsys):
    lb(["help", "search", "audio"])

    output = capsys.readouterr().out
    assert "Play media of any supported type with lb play media" in output
    assert "Listen to audio with lb play audio" in output
    assert "Read text with lb play text" in output


def test_usage_catalog_lists_executable_help_path_only():
    output = __main__.usage()

    assert re.search(r"│ help search\s+│", output)
    assert not re.search(r"│ help\s+│", output)
    assert "play audio" in output
    assert "Show disk usage grouped by file extension" in output


def test_nested_help_examples_use_canonical_commands(capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(["database", "add", "filesystem", "-h"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "library fsadd" not in output
    assert not re.search(r"library fs(?:\s|$)", output)
    assert "library database add filesystem" in output


def test_generated_readme_matches_committed_documentation():
    generated = subprocess.run(
        [sys.executable, "-m", "library.readme"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert generated == Path(".github/README.md").read_text()


def test_generated_readme_documents_every_nested_command():
    readme = Path(".github/README.md").read_text()

    for path in __main__._canonical_nested_paths_for_all_groups():
        assert f"###### {path}\n" in readme
        # the per-command example and its usage header must use the canonical path, too
        assert f"    $ library {path} -h\n    usage: library {path}" in readme


def test_nested_unknown_command_suggests_group_usage(capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(["database", "unknown"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Unknown command: database unknown" in output
    assert "usage: library database <command>" in output


def test_group_aliases_report_unknown_subcommands(capsys):
    for group in (["db", "bogus"], ["fs", "bogus"], ["docs", "bogus"]):
        with pytest.raises(SystemExit) as exc_info:
            lb(group)

        assert exc_info.value.code == 1
        assert "Unknown command: " in capsys.readouterr().out


def test_compact_operation_first_spelling_is_group_agnostic():
    # `db fs update` and `database fs update` should both mean `database update filesystem`
    assert _nested_target(["db", "fs", "update"]) == ("fs-update", 3)
    assert _nested_target(["database", "fs", "update"]) == ("fs-update", 3)
    assert _nested_target(["databases", "fs", "update"]) == ("fs-update", 3)


def test_registering_parsers_does_not_mutate_module_aliases():
    from library.__main__ import create_subcommands_parser, modules

    before = {name: list(aliases) for name, aliases in modules.items()}
    create_subcommands_parser()

    assert modules == before


def test_db_and_fs_are_resource_group_aliases():
    assert _nested_group(["db"]) == "database"
    assert _nested_group(["fs"]) == "filesystem"
    assert _nested_target(["db", "add", "filesystem"]) == ("fs-add", 3)
    assert _nested_target(["fs", "stats", "mounts"]) == ("mount-stats", 3)
    assert _nested_target(["database", "fs", "list"]) == ("filesystem", 3)


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
