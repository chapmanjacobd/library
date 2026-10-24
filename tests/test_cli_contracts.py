import argparse
import io
import re
import subprocess
import sys
from pathlib import Path

import pytest

from library import __main__
from library.__main__ import library as lb
from library.__main__ import _nested_group, nested_target
from library import usage
from library.database.add import gallery_add, tube_add
from library.database.manage import dedupe_media
from library.download import download
from library.shrink import process_image
from library.playback import playback_control
from library.utils import arggroups, argparse_utils, consts, objects
from library.utils.consts import DBType, SC
from tests.utils import v_db


def test_direct_download_rejects_unknown_options(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download", "--direct", "--unknown-option", "https://example.com/file"])

    with pytest.raises(SystemExit):
        download.parse_args()


@pytest.mark.parametrize(
    ("parse_args", "action", "usage_text", "argv"),
    [
        (tube_add.parse_args, SC.tube_add, usage.tube_add, [v_db, "--image", "https://example.com"]),
        (tube_add.parse_args, SC.tube_update, usage.tube_update, [v_db, "--filesystem"]),
        (gallery_add.parse_args, SC.gallery_add, usage.gallery_add, [v_db, "--video", "https://example.com"]),
        (gallery_add.parse_args, SC.gallery_update, usage.gallery_update, [v_db, "--text"]),
    ],
)
def test_backend_add_commands_reject_mismatching_profiles(monkeypatch, parse_args, action, usage_text, argv):
    monkeypatch.setattr("sys.argv", ["command", *argv])

    with pytest.raises(SystemExit):
        parse_args(action, usage_text)


@pytest.mark.parametrize(
    "command",
    [
        ["cluster-sort", "--audio"],
        ["cluster-sort", "--video"],
        ["cluster-sort", "--text"],
        ["cluster-sort", "--image"],
        ["cluster-sort", "--images"],
        ["export-text", "--format", "json", ":memory:"],
        ["download", "--safe", "--filesystem", v_db],
        ["media", "--chromecast", "--db", v_db],
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
    monkeypatch.setattr("sys.argv", ["download", "--db", v_db, "--print"])

    args = download.parse_args()

    assert args.profile == DBType.auto


def test_download_media_type_auto(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download", "--media-type", "auto", "--db", v_db, "--print"])

    args = download.parse_args()

    assert args.profile == DBType.auto


def test_download_links_defaults_to_auto(monkeypatch):
    monkeypatch.setattr("sys.argv", ["links-download", "--db", v_db, "--print"])

    args = download.parse_args(usage.download_links, links=True)

    assert args.profile == DBType.auto


def test_database_link_download_registers_link_spider_options(monkeypatch):
    monkeypatch.setattr("sys.argv", ["links-download", "--db", v_db, "--recursive", "--webcache", "--print"])

    args = download.parse_args(usage.download_links, links=True)

    assert args.recursive is True
    assert args.webcache is True


def test_links_download_defaults_to_auto(monkeypatch):
    monkeypatch.setattr("sys.argv", ["links-download", "https://example.com/"])

    args = download.parse_args(usage.links_download, links=True)

    assert args.profile == DBType.auto


def test_database_download_positional_is_the_database(monkeypatch):
    monkeypatch.setattr("sys.argv", ["database-download", v_db, "--print"])

    args = download.parse_args(usage.download_database, database_positional=True)

    assert args.database == v_db


def test_database_download_requires_positional_database(monkeypatch):
    monkeypatch.setattr("sys.argv", ["database-download", "--print"])

    with pytest.raises(SystemExit):
        download.parse_args(usage.download_database, database_positional=True)


def test_links_download_accepts_extractor_options(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["links-download", "--url-encode", "--no-sanitize", "--extra", "https://example.com/"],
    )

    args = download.parse_args(usage.links_download, links=True)

    assert args.url_encode is True
    assert args.no_sanitize is True
    assert args.extra is True
    assert args.unk == []


@pytest.mark.parametrize(
    ("command", "links", "expected_path"),
    [
        (["download"], False, "https://old.reddit.com/r/python/top/?sort=top&t=month"),
        (["links-download"], True, "https://old.reddit.com/r/python/top/?sort=top&t=month"),
        (["download", "--no-sanitize"], False, "https://www.reddit.com/r/python/new/"),
    ],
)
def test_download_commands_apply_extractor_path_sanitization(monkeypatch, command, links, expected_path):
    monkeypatch.setattr("sys.argv", [*command, "https://www.reddit.com/r/python/new/"])

    args = download.parse_args(usage.download_links if links else None, links=links)

    assert args.paths == [expected_path]


def test_download_requires_db_flag_for_databases(monkeypatch):
    """`lb download`/`lb dl` must use `--db`; a bare positional is a URL/path, not a database."""
    monkeypatch.setattr("sys.argv", ["download", v_db, "--print"])

    args = download.parse_args()

    assert args.database is None
    assert args.paths == [v_db]


def test_download_with_db_treats_paths_as_filters(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download", "--db", v_db, "https://example.com/", "--print"])

    args = download.parse_args()

    assert args.database == v_db
    assert args.paths == []
    assert args.include == ["https://example.com/"]


def test_links_download_with_db_delegates_to_database_download(monkeypatch):
    called = []
    monkeypatch.setattr("library.download.download.download_links", lambda: called.append(sys.argv[1:]))

    lb(["links-download", "--db", "links.db", "https://example.com/"])

    assert called == [["--db", "links.db", "https://example.com/"]]


def test_links_download_accepts_direct(monkeypatch):
    monkeypatch.setattr("sys.argv", ["links-download", "--direct", "https://example.com/"])

    args = download.parse_args(usage.links_download, links=True)

    assert args.direct is True


def test_links_download_accepts_text(monkeypatch):
    monkeypatch.setattr("sys.argv", ["links-download", "--text", "https://example.com/"])

    args = download.parse_args(usage.links_download, links=True)

    assert args.profile == DBType.text


def test_direct_download_usage_keeps_top_level_route():
    text = __main__.canonicalize_usage_for_command(usage.download, "download")

    assert "library download --db dl.db" in text


def test_download_accepts_direct_and_safe(monkeypatch):
    """`lb download` routes by default (auto) but `--direct` selects the built-in downloader."""
    monkeypatch.setattr("sys.argv", ["download", "--direct", "https://example.com/x"])

    args = download.parse_args()

    assert args.direct is True
    assert args.profile == DBType.auto
    assert hasattr(args, "safe")


def test_nested_command_dispatches_to_canonical_target(monkeypatch):
    called = []
    monkeypatch.setattr("library.play.play_actions.watch", lambda: called.append(sys.argv[1:]))

    lb(["play", "video", "--db", "video.db"])

    assert called == [["--db", "video.db"]]


@pytest.mark.parametrize("filesystem_flag", ["--filesystem", "--io", "--fs"])
def test_file_check_filesystem_aliases_dispatch_to_io_check(monkeypatch, filesystem_flag):
    called = []
    monkeypatch.setattr(
        "library.file.io_check.io_check",
        lambda args: called.append((args.filesystem, args.paths)),
    )

    lb(["file", "check", filesystem_flag, "/mnt/media"])

    assert called == [(True, ["/mnt/media"])]


def test_legacy_flat_command_dispatches_to_existing_target(monkeypatch):
    called = []
    monkeypatch.setattr("library.play.play_actions.watch", lambda: called.append(sys.argv[1:]))

    lb(["watch", "--db", "video.db"])

    assert called == [["--db", "video.db"]]


def test_nested_links_download_dispatches_to_existing_entrypoint(monkeypatch):
    called = []
    monkeypatch.setattr("library.links.extract_links.links_download", lambda: called.append(sys.argv[1:]))

    lb(["links", "download", "https://example.com/"])

    assert called == [["https://example.com/"]]


def test_nested_direct_download_dispatches_to_existing_entrypoint(monkeypatch):
    called = []
    monkeypatch.setattr("library.download.download.download", lambda: called.append(sys.argv[1:]))

    lb(["download", "https://example.com/file.zip"])

    assert called == [["https://example.com/file.zip"]]


def test_nested_alias_dispatches_with_canonical_program(monkeypatch):
    called = []

    def record_call():
        called.append((sys.argv[0], sys.argv[1:]))

    monkeypatch.setattr("library.filesystem.filesystem.filesystem", record_call)

    lb(["fs", "list", "--db", "files.db"])

    assert called == [("library filesystem list", ["--db", "files.db"])]


@pytest.mark.parametrize("command", [["open-directory"], ["web"]])
def test_database_directory_command_dispatches_with_canonical_program(monkeypatch, command):
    called = []

    def record_call():
        called.append((sys.argv[0], sys.argv[1:]))

    monkeypatch.setattr("library.database.add.web_add.web_add", record_call)

    lb(["database", "add", *command])

    assert called == [("library database add open-directory", [])]


def test_canonicalize_usage_rewrites_legacy_flat_commands_only():
    text = "library fs-add ROOT\nlibrary database add filesystem ROOT\n"

    assert __main__.canonicalize_usage(text) == (
        "library database add filesystem ROOT\nlibrary database add filesystem ROOT\n"
    )


def test_nested_unknown_leaf_suggests_closest_command(capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(["database", "add", "filesytem"])

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Unknown command: database add filesytem" in output
    assert "Did you mean: database add filesystem?" in output


def test_version_flag_prints_version(capsys):
    lb(["--version"])

    assert capsys.readouterr().out.strip() == __main__.__version__


def test_download_without_db_is_direct(monkeypatch):
    called = []
    monkeypatch.setattr(
        "library.links.extract_links.download_paths",
        lambda _args, _cache: called.append(sys.argv[1:]),
    )

    lb(["download", "https://example.com/file.zip"])

    assert called == [["https://example.com/file.zip"]]


def test_download_with_db_preserves_argv(monkeypatch):
    called = []
    monkeypatch.setattr("library.download.download.download", lambda: called.append(sys.argv[1:]))

    lb(["download", "--db", "dl.db", "--prefix", "/tmp/out"])

    assert called == [["--db", "dl.db", "--prefix", "/tmp/out"]]


def test_database_download_dispatches_to_distinct_entrypoint(monkeypatch):
    called = []
    monkeypatch.setattr("library.download.download.download_database", lambda: called.append(sys.argv[1:]))

    lb(["database", "download", "dl.db", "--prefix", "/tmp/out"])

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
        (["filesystem", "-h"], "usage: library filesystem <command>"),
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
        (["links", "download", "-h"], "usage: library links download"),
        (["database", "search", "-h"], "usage: library database search"),
        (["filesystem", "list", "-h"], "usage: library filesystem list"),
        (["file", "hash", "-h"], "usage: library file hash"),
        (["text", "sort", "regex", "-h"], "usage: library text sort regex"),
        (["image", "sort", "cluster", "-h"], "usage: library image sort cluster"),
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
    assert first_line.count(usage_prefix.removeprefix("usage: library ")) == 1


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
    catalog = __main__.command_catalog()
    commands = [command for _category, category_commands in catalog for command, _description in category_commands]

    assert re.search(r"│ help search\s+│", output)
    assert "play audio" in output
    assert "Show disk usage grouped by file extension" in output
    assert len(catalog) >= 14
    assert len(commands) >= 99
    assert len(commands) == len(set(commands))
    assert set(commands) == set(__main__._canonical_nested_paths_for_all_groups())  # noqa: SLF001


def test_usage_catalog_normalizes_nested_aliases():
    catalog = dict(__main__.command_catalog())
    commands = dict(catalog["Database updating subcommands"])

    assert "database update open-directory" in commands


def test_nested_help_examples_use_canonical_commands(capsys):
    with pytest.raises(SystemExit) as exc_info:
        lb(["database", "add", "filesystem", "-h"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
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

    for path in __main__._canonical_nested_paths_for_all_groups():  # noqa: SLF001
        assert f"###### {path}\n" in readme
        nested = __main__.nested_target(path.split())
        assert nested is not None
        target, _consumed = nested
        canonical_path = __main__.canonical_target_paths().get(target, path)
        assert f"    $ library {path} -h\n    usage: library {canonical_path}" in readme


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
    assert nested_target(["db", "fs", "update"]) == ("fs-update", 3)
    assert nested_target(["database", "fs", "update"]) == ("fs-update", 3)
    assert nested_target(["databases", "fs", "update"]) == ("fs-update", 3)


def test_registering_parsers_does_not_mutate_module_aliases():
    from library.__main__ import create_subcommands_parser, modules

    before = {name: list(aliases) for name, aliases in modules.items()}
    create_subcommands_parser()

    assert modules == before


def test_db_and_fs_are_resource_group_aliases():
    assert _nested_group(["db"]) == "database"
    assert _nested_group(["fs"]) == "filesystem"
    assert nested_target(["db", "add", "filesystem"]) == ("fs-add", 3)
    assert nested_target(["fs", "mounts", "stats"]) == ("mount-stats", 3)
    assert nested_target(["fs", "mounts", "free"]) == ("disk-free", 3)
    # The former operation-first spellings remain accepted as compatibility routes.
    assert nested_target(["fs", "stats", "mounts"]) == ("mount-stats", 3)
    assert nested_target(["fs", "free", "mounts"]) == ("disk-free", 3)
    assert nested_target(["filesystem", "list"]) == ("filesystem", 2)
    assert nested_target(["fs", "usage"]) == ("disk-usage", 2)


def test_download_block_is_nested_under_download():
    assert nested_target(["database", "download", "block"]) == ("block", 3)


def test_database_export_html_is_nested_under_database():
    assert nested_target(["database", "export", "html"]) == ("export-text", 3)


def test_pdf_adjustment_is_nested_under_document():
    assert nested_target(["document", "adjust", "pdf"]) == ("pdf-edit", 3)


def test_torrent_allocation_is_nested_under_torrent():
    assert nested_target(["torrent", "allocate"]) == ("allocate-torrents", 2)


def test_database_stats_words_is_nested_under_stats():
    assert nested_target(["database", "stats", "words"]) == ("stats-words", 3)


@pytest.mark.parametrize(
    ("command", "target"),
    [
        (["database", "enrich", "imdb"], "enrich-imdb"),
        (["database", "tail"], "tail"),
        (["database", "stats", "schema"], "stats-schema"),
        (["file", "case-conflicts"], "casefold"),
        (["filesystem", "usage", "modified"], "modified-hist"),
    ],
)
def test_new_feature_commands_route_to_canonical_targets(command, target):
    assert nested_target(command) == (target, len(command))


def test_torrent_match_and_audit_are_nested_under_torrent():
    assert nested_target(["torrent", "match"]) == ("torrent-match", 2)
    assert nested_target(["torrent", "audit"]) == ("torrent-audit", 2)


def test_json_key_renaming_is_nested_under_json():
    assert nested_target(["json", "rename-keys"]) == ("json-keys-rename", 2)


def test_document_conversion_routes_are_explicit():
    assert nested_target(["image", "convert"]) == ("image-convert", 2)
    assert nested_target(["document", "convert"]) == ("document-convert", 2)
    assert nested_target(["document", "pdf", "header"]) == ("pdf-header", 3)
    assert nested_target(["text", "convert"]) == ("document-convert", 2)
    assert nested_target(["shrink", "table"]) == ("process-table", 2)


def test_cluster_sort_images_is_a_nested_subcommand():
    assert nested_target(["text", "sort", "cluster"]) == ("cluster-sort", 3)
    assert nested_target(["image", "sort", "cluster"]) == ("cluster-images", 3)


def test_top_level_filesystem_routes_dispatch_to_migrated_commands(monkeypatch):
    called = []
    monkeypatch.setattr("library.filesystem.filesystem.filesystem", lambda: called.append(sys.argv[1:]))
    monkeypatch.setattr("library.filesystem.disk_usage.disk_usage", lambda: called.append(sys.argv[1:]))

    lb(["fs", "list", "--db", "files.db"])
    lb(["filesystem", "usage", "--db", "files.db"])

    assert called == [
        ["--db", "files.db"],
        ["--db", "files.db"],
    ]


def test_migrated_path_parsers_promote_legacy_database_position():
    args = argparse.Namespace(database=None, paths=["tests/data/video.db", "path-filter"], include=[])

    arggroups.database_paths_post(args, legacy_database=True)

    assert args.database == "tests/data/video.db"
    assert args.include == ["path-filter"]
    assert args.paths == []


def test_migrated_path_parsers_promote_memory_database():
    args = argparse.Namespace(database=None, paths=[":memory:", "path-filter"], include=[])

    arggroups.database_paths_post(args, legacy_database=True)

    assert argparse_utils.is_sqlite(":memory:")
    assert args.database == ":memory:"
    assert args.include == ["path-filter"]
    assert args.paths == []


def test_migrated_path_parsers_keep_non_sqlite_db_path(tmp_path):
    path = tmp_path / "archive.db"
    path.write_text("not a database")
    args = argparse.Namespace(database=None, paths=[str(path)], include=[])

    arggroups.database_paths_post(args, legacy_database=True)

    assert args.database is None
    assert args.paths == [str(path)]


def test_database_paths_post_reads_implicit_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("first\nsecond\n"))
    args = argparse.Namespace(database=None, paths=[], include=[])

    arggroups.database_paths_post(args)

    assert args.paths == ["first", "second"]


def test_database_paths_post_moves_explicit_paths_to_filters():
    args = argparse.Namespace(database="tests/data/video.db", paths=["path-filter"], include=[])

    arggroups.database_paths_post(args)

    assert args.include == ["path-filter"]
    assert args.paths == []


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

    assert exts >= consts.TEXTRACT_EXTENSIONS
    assert exts >= consts.OCR_EXTENSIONS
    assert exts >= consts.SPEECH_RECOGNITION_EXTENSIONS

    video_only = arggroups.profile_extensions([DBType.video])
    assert video_only >= consts.VIDEO_EXTENSIONS
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


def test_is_profile_auto_matches_scannable_types():
    args = argparse.Namespace(profile=DBType.auto)

    assert objects.is_profile(args, DBType.video)
    assert objects.is_profile(args, DBType.audio)
    assert objects.is_profile(args, DBType.image)
    # text matches `auto` too; the extractor itself skips when textract is unavailable
    assert objects.is_profile(args, DBType.text)
    assert not objects.is_profile(args, DBType.filesystem)


def test_dedupe_media_accepts_audio_profile(monkeypatch):
    monkeypatch.setattr("sys.argv", ["dedupe-media", "--audio", v_db])

    args = dedupe_media.parse_args()

    assert args.profile == DBType.audio


def test_dedupe_strategy_selects_extractor_id(monkeypatch):
    monkeypatch.setattr("sys.argv", ["dedupe-media", "--id", v_db])

    args = dedupe_media.parse_args()

    assert args.strategy == "extractor_id"
