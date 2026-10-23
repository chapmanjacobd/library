import pytest

from library.document import pdf_header


def test_pdf_header_requires_external_commands(monkeypatch):
    monkeypatch.setattr(pdf_header, "which", lambda _command: None)

    with pytest.raises(SystemExit):
        pdf_header._require_commands("pandoc")  # noqa: SLF001
