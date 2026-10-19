import io

from library.__main__ import library as lb


def test_group_lines_uses_capture_groups(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("alpha: one\nbeta: two\nno separator\n"))

    lb(["text", "group", r"^([a-z]+):", "-"])

    assert capsys.readouterr().out == "(no match):\nno separator\nalpha:\nalpha: one\nbeta:\nbeta: two\n"


def test_group_lines_handles_unmatched_optional_capture(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("b\n"))

    lb(["text", "group", r"^(a)?b$", "-"])

    assert capsys.readouterr().out == ":\nb\n"


def test_interleave_lines(tmp_path, capsys):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("a1\na2\n", encoding="utf-8")
    second.write_text("b1\nb2\nb3\n", encoding="utf-8")

    lb(["text", "interleave", str(first), str(second)])

    assert capsys.readouterr().out == "a1\nb1\na2\nb2\nb3\n"
