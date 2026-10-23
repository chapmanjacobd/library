import os
from pathlib import Path

import pytest

from library.utils import consts
from library.utils.path_utils import clean_path
from tests.utils import p


def test_basic_filename_cleaning():
    b = b"example.txt"
    result = clean_path(b)
    assert result == "example.txt"


def test_leading_slash_is_preserved():
    b = b"/folder/file.txt"
    result = clean_path(b)
    assert result.startswith(os.sep)
    assert result.endswith("file.txt")


@pytest.mark.skipif(consts.NOT_WINDOWS, reason="Windows-only drive path test")
def test_windows_drive_preserved():
    b = b"C:\\Users\\Test\\file.txt"
    result = clean_path(b)
    assert result.startswith("C:")
    assert result.endswith("file.txt")


def test_trims_spaces_and_dashes():
    b = b"/ -folder- / -file-.txt"
    result = clean_path(b)
    # prefixes and suffixes removed
    assert "folder" in result
    assert result.endswith("file.txt")


def test_lowercase_folders_flag():
    b = b"/MyFolder/File.txt"
    result = clean_path(b, lowercase_folders=True)
    assert p("/myfolder/") in result


def test_case_insensitive_flag_titles_if_contains_space_or_dot():
    b = b"/my folder/File.txt"
    result = clean_path(b, case_insensitive=True)
    # folder name should be titlecased
    assert "My Folder" in result


def test_stem_too_long_shortened():
    longname = "a" * 300
    b = f"{longname}.txt".encode()
    result = clean_path(b, max_name_len=50)
    assert len(Path(result).stem.encode()) <= 50 - len(b".txt") - 1
    assert "..." in Path(result).stem


def test_dot_space_replacement():
    b = b"/my folder/file.txt"
    result = clean_path(b, dot_space=True)
    assert "my.folder" in result


def test_long_emoji_filename_is_shortened():
    # 😀😃😄 repeated to exceed max length
    emojis = "😀😃😄" * 100
    b = f"{emojis}.txt".encode()
    result = clean_path(b, max_name_len=60)
    stem = Path(result).stem
    assert "..." in stem
    assert len(stem.encode("utf-8")) <= 60 - len(b".txt") - 1


def test_folder_with_mixed_emoji_and_text():
    b = "/docs/😀-project-😎/report.txt".encode()
    result = clean_path(b)
    assert "😀-project-😎" in result
    assert result.endswith("report.txt")


def test_dot_space_with_emojis():
    b = "/😀 cool 😎/file.txt".encode()
    result = clean_path(b, dot_space=True)
    # spaces should be replaced with dots, emojis intact
    assert "😀.cool.😎" in result


def test_case_insensitive_with_emojis():
    b = "/😀 Folder 😎/file.txt".encode()
    result = clean_path(b, case_insensitive=True)
    assert "😀 Folder 😎" in result
    assert result.endswith("file.txt")


def test_mojibake_fix_is_opt_in():
    b = "/docs/cafÃ©.txt".encode()

    assert clean_path(b) == p("/docs/cafÃ©.txt")
    assert clean_path(b, fix_mojibake=True) == p("/docs/café.txt")


def test_mojibake_fix_recleans_corrected_text():
    b = "/docs/fooï¼\x8fbar.txt".encode()

    assert clean_path(b, fix_mojibake=True) == p("/docs/foo bar.txt")
