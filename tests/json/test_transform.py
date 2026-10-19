import io
import pytest

from library.__main__ import library as lb


def test_remove_nulls_recursively(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"a": null, "nested": {"b": 1, "c": null}, "items": [null, 2]}'))

    lb(["json", "remove-nulls"])

    assert capsys.readouterr().out == '{"nested":{"b":1},"items":[2]}\n'


def test_remove_nulls_rejects_indentation_for_jsonl(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"a": 1}\n{"b": 2}\n'))

    with pytest.raises(ValueError, match="JSONL"):
        lb(["json", "remove-nulls", "--indent", "2"])
