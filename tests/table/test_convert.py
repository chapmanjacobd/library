import io
import json
import pytest

from library.__main__ import library as lb


def test_json_to_csv_accepts_jsonl(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"id": 1, "name": "Ada"}\n{"id": 2, "name": "Grace"}\n'))

    lb(["table", "convert", "csv", "id", "name"])

    assert capsys.readouterr().out == "id,name\r\n1,Ada\r\n2,Grace\r\n"


def test_json_to_csv_can_keep_selected_fields(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO('[{"id": 1, "name": "Ada", "extra": true}]'))

    lb(["table", "convert", "csv", "--keep-only", "name", "id"])

    assert capsys.readouterr().out == "name,id\r\nAda,1\r\n"


def test_csv_to_json_reads_header_from_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("id,name\n1,Ada\n2,Grace\n"))

    lb(["table", "convert", "json", "--header"])

    assert json.loads(capsys.readouterr().out) == [
        {"id": "1", "name": "Ada"},
        {"id": "2", "name": "Grace"},
    ]


def test_csv_to_json_applies_column_names(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("1,Ada\n2,Grace\n"))

    lb(["table", "convert", "json", "--column-names", "id,name"])

    assert json.loads(capsys.readouterr().out) == [
        {"id": "1", "name": "Ada"},
        {"id": "2", "name": "Grace"},
    ]


def test_csv_to_json_rejects_header_with_column_names(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("id,name\n1,Ada\n"))

    with pytest.raises(SystemExit):
        lb(["table", "convert", "json", "--header", "--column-names", "id,name"])
