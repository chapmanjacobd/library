import sys
from types import SimpleNamespace

import pytest

from library.__main__ import (
    NESTED_COMMANDS,
    _canonical_nested_paths,
    _nested_target,
    _target_module,
    library as lb,
)
from library.mediadb import download
from library.mediafiles import process_image
from library.playback.media_printer import media_printer
from library.text import extract_text
from library.utils import argparse_utils, arggroups
from library.utils.consts import DBType
from tests.utils import v_db


@pytest.mark.parametrize(
    "command",
    [
        ["cluster-sort", "--audio"],
        ["cluster-sort", "--video"],
        ["cluster-sort", "--text"],
        ["export-text", "--format", "json", ":memory:"],
        ["database", "download", "--safe", "--filesystem", v_db],
        ["database", "filesystem", "list", "--chromecast", v_db],
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
    assert args.direct is True


def test_download_links_uses_link_extraction_by_default(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download", v_db, "--print"])

    args = download.parse_args(links=True)

    assert args.profile == DBType.filesystem
    assert args.direct is False


def test_download_links_accepts_direct_mode(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download", v_db, "--direct", "--print"])

    args = download.parse_args(links=True)

    assert args.direct is True


def test_links_extract_does_not_accept_download_flag():
    with pytest.raises(SystemExit):
        lb(["links", "extract", "--download", "https://example.com/"])


def test_links_download_does_not_accept_no_extract_flag():
    with pytest.raises(SystemExit):
        lb(["links", "download", "--no-extract", "https://example.com/"])


def test_text_extract_keeps_download_flag(monkeypatch):
    monkeypatch.setattr("sys.argv", ["text", "--download", "https://example.com/"])

    args = extract_text.parse_args()

    assert args.download is True


def test_text_extract_renames_skip_links_flag(monkeypatch):
    monkeypatch.setattr("sys.argv", ["text", "--filter-links", "https://example.com/"])

    args = extract_text.parse_args()

    assert args.filter_links is True

    monkeypatch.setattr("sys.argv", ["text", "--skip-links", "https://example.com/"])
    with pytest.raises(SystemExit):
        extract_text.parse_args()


@pytest.mark.parametrize(
    "command",
    [
        ["watch", "-h"],
        ["listen", "-h"],
        ["playback-next", "-h"],
        ["fs-add", "-h"],
        ["database", "add", "hacker-news", "-h"],
        ["database", "hacker", "news", "add", "-h"],
        ["document", "images", "to", "pdf", "-h"],
        ["database", "mpv", "import", "watchlater", "-h"],
        ["database", "reddit", "enrich", "selftext", "-h"],
        ["database", "online", "merge", "local", "-h"],
        ["database", "play", "copy", "counts", "-h"],
        ["database", "media", "dedupe", "-h"],
        ["database", "torrents", "allocate", "-h"],
        ["database", "filesystem", "add", "-h"],
        ["database", "video", "update", "-h"],
        ["file", "czkawka", "dedupe", "-h"],
        ["folder", "mergerfs", "copy", "-h"],
        ["document", "text", "export", "-h"],
        ["text", "regex", "sort", "-h"],
        ["folder", "merge", "relative", "move", "-h"],
        ["folder", "merge", "relative", "copy", "-h"],
        ["text", "json", "rename", "keys", "-h"],
    ],
)
def test_removed_flat_commands_are_rejected(command):
    with pytest.raises(SystemExit) as exc_info:
        lb(command)

    assert exc_info.value.code == 1


def test_nested_command_dispatches_to_canonical_target(monkeypatch):
    called = []

    monkeypatch.setattr(
        "library.playback.play_actions.watch",
        lambda: called.append(sys.argv[1:]),
    )

    lb(["play", "video", "video.db"])

    assert called == [["video.db"]]


def test_links_download_dispatches_to_links_download(monkeypatch):
    called = []

    monkeypatch.setattr(
        "library.text.extract_links.links_download",
        lambda: called.append(sys.argv[1:]),
    )

    lb(["links", "download", "https://example.com/"])

    assert called == [["https://example.com/"]]


def test_direct_download_dispatches_to_direct_download(monkeypatch):
    called = []

    monkeypatch.setattr(
        "library.text.extract_links.direct_download",
        lambda: called.append(sys.argv[1:]),
    )

    lb(["download", "https://example.com/file.zip"])

    assert called == [["https://example.com/file.zip"]]


def test_direct_download_forces_no_extract(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "library.text.extract_links.parse_args",
        lambda usage, download=False: SimpleNamespace(no_extract=False),
    )
    monkeypatch.setattr(
        "library.text.extract_links._download_paths",
        lambda args: calls.append(args.no_extract),
    )

    from library.text import extract_links

    extract_links.direct_download()

    assert calls == [True]


def test_links_download_defaults_to_downloading(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "library.text.extract_links.extract_links",
        lambda download=False: calls.append((download, list(sys.argv[1:]))),
    )
    monkeypatch.setattr("sys.argv", ["lb", "https://example.com/"])

    from library.text import extract_links

    extract_links.links_download()

    assert calls == [(True, ["https://example.com/"])]


def test_database_download_links_defaults_to_filesystem_links(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "library.mediadb.download._download",
        lambda usage, links=False: calls.append((usage, links, list(sys.argv[1:]))),
    )
    monkeypatch.setattr("sys.argv", ["lb", "links.db"])

    download.download_links()

    usage, links, argv = calls[0]
    assert links is True
    assert argv == ["links.db"]
    assert usage.startswith("library database download links")


@pytest.mark.parametrize("command", [["db", "filesystem", "update"], ["db", "fs", "update"]])
def test_nested_database_shortcuts_dispatch_to_canonical_target(monkeypatch, command):
    called = []

    monkeypatch.setattr(
        "library.createdb.fs_add.fs_update",
        lambda: called.append(sys.argv[1:]),
    )

    lb([*command, "video.db"])

    assert called == [["video.db"]]


@pytest.mark.parametrize(
    ("alias", "canonical_path"),
    [
        ("doc", ["document", "export", "text"]),
        ("docs", ["document", "export", "text"]),
        ("files", ["file", "hash"]),
        ("folders", ["folder", "similar"]),
        ("tables", ["table", "columns"]),
        ("caption", ["captions"]),
    ],
)
def test_singular_plural_group_aliases(alias, canonical_path):
    assert _nested_target([alias, *canonical_path[1:]]) == _nested_target(canonical_path)


def test_all_canonical_routes_target_registered_commands():
    for group, command_tree in NESTED_COMMANDS.items():
        for path in _canonical_nested_paths(group, command_tree):
            target = _nested_target(path.split())
            assert target is not None
            _target_module(target[0])


@pytest.mark.parametrize(
    "argv",
    [
        ["database", "filesystem", "list", "video.db"],
        ["database", "filesystem", "usage", "extensions", "video.db"],
        ["text", "sort", "regex", "input.txt"],
        ["help", "search", "query"],
    ],
)
def test_canonical_groups_use_nested_parsers(argv):
    assert _nested_target(argv) is not None


def test_root_help_lists_recursive_canonical_paths(capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(["--help"])

    output = capsys.readouterr().out
    assert exc_info.value.code == 0
    assert "Create database subcommands:" in output
    assert "compatibility" not in output.lower()
    assert "Canonical commands:" not in output
    assert "Flat commands" not in output
    assert "text sort regex" in output
    assert "filesystem stats mounts" in output
    assert "document to-pdf images" in output
    assert "document images to-pdf" not in output
    assert "media status" not in output
    assert output.count("Other subcommands:") == 1
    assert output.count("database filesystem usage sizes") == 1
    assert output.count("folder merge copy") == 1


def test_group_help_accepts_long_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(["database", "--help"])

    output = capsys.readouterr().out
    assert exc_info.value.code == 0
    assert "  add tables" in output
    assert "  search" in output


def test_unknown_nested_route_suggests_canonical_command(capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(["playback", "pauze"])

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert "Did you mean: playback pause?" in output


def test_unknown_nested_route_with_help_still_reports_unknown_command(capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(["playback", "surf", "-h"])

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert "Unknown command: playback surf" in output


def test_known_subgroup_help_omits_unknown_command(capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(["database", "filesystem", "-h"])

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert "Unknown command" not in output


def test_nested_leaf_help_uses_canonical_usage(capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(["play", "video", "-h"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.startswith("usage: library play video")


@pytest.mark.parametrize(
    ("nested", "usage_prefix"),
    [
        (["database", "search", "-h"], "usage: library database search"),
        (["download", "-h"], "usage: library download"),
        (["play", "media", "-h"], "usage: library play media"),
        (["database", "download", "-h"], "usage: library database download"),
        (["database", "history", "-h"], "usage: library database history"),
        (["file", "check", "-h"], "usage: library file check"),
        (["database", "filesystem", "list", "-h"], "usage: library database filesystem list"),
        (["database", "filesystem", "usage", "-h"], "usage: library database filesystem usage"),
        (["file", "hash", "-h"], "usage: library file hash"),
        (["folder", "similar", "-h"], "usage: library folder similar"),
        (["document", "to-pdf", "images", "-h"], "usage: library document to-pdf images"),
        (["document", "edit", "pdf", "-h"], "usage: library document edit pdf"),
        (["document", "export", "text", "-h"], "usage: library document export text"),
        (["database", "add", "hackernews", "-h"], "usage: library database add hackernews"),
        (["database", "import", "mpv-watchlater", "-h"], "usage: library database import mpv-watchlater"),
        (["database", "enrich", "reddit-selftext", "-h"], "usage: library database enrich reddit-selftext"),
        (["database", "merge", "online-local", "-h"], "usage: library database merge online-local"),
        (["database", "copy", "play-counts", "-h"], "usage: library database copy play-counts"),
        (["database", "dedupe", "media", "-h"], "usage: library database dedupe media"),
        (["table", "analyze", "-h"], "usage: library table analyze"),
        (["text", "extract", "-h"], "usage: library text extract"),
        (["text", "sort", "regex", "-h"], "usage: library text sort regex"),
        (["text", "expand", "links", "-h"], "usage: library text expand links"),
        (["text", "dates", "-h"], "usage: library text dates"),
        (["filesystem", "free", "mounts", "-h"], "usage: library filesystem free mounts"),
        (["file", "normalize", "-h"], "usage: library file normalize"),
        (["file", "dedupe", "czkawka", "-h"], "usage: library file dedupe czkawka"),
        (["folder", "copy", "mergerfs", "-h"], "usage: library folder copy mergerfs"),
        (["archive", "extract", "-h"], "usage: library archive extract"),
        (["help", "search", "-h"], "usage: library help search"),
    ],
)
def test_new_nested_leaf_help_uses_canonical_usage(nested, usage_prefix, capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(nested)

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.startswith(usage_prefix)


@pytest.mark.parametrize(("flag", "expected"), [("--list", "p"), ("--aggregate", "a")])
def test_simplified_print_modes(monkeypatch, flag, expected):
    monkeypatch.setattr("sys.argv", ["download", v_db, flag])

    args = download.parse_args()

    assert args.print == expected


def test_media_type_and_fields_alias(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download", v_db, "--media-type", "audio", "--fields", "path,title"])

    args = download.parse_args()

    assert args.profile == DBType.audio
    assert args.print == ""
    assert args.cols == ["path", "title"]


def test_json_output_spelling_and_json_input_alias():
    output_parser = argparse_utils.ArgumentParser()
    arggroups.printing(output_parser)
    output_args = output_parser.parse_args(["--to-json"])

    assert output_args.to_json is True

    input_parser = argparse_utils.ArgumentParser()
    arggroups.paths_or_stdin(input_parser, required=False)
    arggroups.printing(input_parser)
    input_args = input_parser.parse_args(["--json"])

    assert input_args.from_json is True
    assert input_args.to_json is False


def test_database_profiles_accept_media_type():
    parser = argparse_utils.ArgumentParser()
    arggroups.db_profiles(parser)
    args = parser.parse_args(["--media-type", "text"])

    assert args.profiles == [DBType.text]


@pytest.mark.parametrize("group", ["shrink", "database", "links"])
def test_bare_nested_group_prints_help(group, capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb([group])

    assert exc_info.value.code == 1
    assert f"library {group} <command>" in capsys.readouterr().out


def test_print_template_formats_media(monkeypatch, capsys):
    class DummyDB:
        def table_names(self):
            return []

    monkeypatch.setattr("library.playback.media_printer.db_utils.columns", lambda *_args: ["path", "title"])
    args = SimpleNamespace(
        action="",
        print="%(title)s|%(path)s",
        cols=[],
        limit=None,
        timeout_size=None,
        verbose=0,
        db=DummyDB(),
        delete_files=False,
        delete_rows=False,
        mark_deleted=False,
        mark_watched=False,
        simulate=False,
        to_json=False,
        print_limit=None,
        no_url_decode=False,
    )

    media_printer(args, [{"path": "video.mp4", "title": "Example"}])

    assert capsys.readouterr().out == "Example|video.mp4\n"


def test_print_template_keeps_raw_values_and_adds_human_columns(monkeypatch, capsys):
    class DummyDB:
        def table_names(self):
            return []

    monkeypatch.setattr("library.playback.media_printer.db_utils.columns", lambda *_args: ["path", "size"])
    args = SimpleNamespace(
        action="",
        print="%(size)s|%(humansize)s|%(path)s|%(humanpath)s",
        cols=[],
        limit=None,
        timeout_size=None,
        verbose=0,
        db=DummyDB(),
        delete_files=False,
        delete_rows=False,
        mark_deleted=False,
        mark_watched=False,
        simulate=False,
        to_json=False,
        print_limit=None,
        no_url_decode=False,
    )

    media_printer(args, [{"path": "https://example.com/a%20b.mp4", "size": 123456789}])

    assert capsys.readouterr().out == "123456789|117.7MiB|https://example.com/a%20b.mp4|https://example.com/a b.mp4\n"


def test_print_template_reports_missing_fields(monkeypatch):
    class DummyDB:
        def table_names(self):
            return []

    monkeypatch.setattr("library.playback.media_printer.db_utils.columns", lambda *_args: [])
    args = SimpleNamespace(
        action="",
        print="%(missing)s",
        cols=[],
        limit=None,
        timeout_size=None,
        verbose=0,
        db=DummyDB(),
        delete_files=False,
        delete_rows=False,
        mark_deleted=False,
        mark_watched=False,
        simulate=False,
        to_json=False,
        print_limit=None,
        no_url_decode=False,
    )

    with pytest.raises(ValueError, match="Invalid --print template"):
        media_printer(args, [{"path": "video.mp4"}])
