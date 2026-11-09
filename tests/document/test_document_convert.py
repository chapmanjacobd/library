from library.document import document_convert


def test_document_kind_uses_known_extensions():
    assert document_convert._document_kind("notes.md") == "text"  # ruff: ignore[private-member-access]
    assert document_convert._document_kind("photo.jpg") == "image"  # ruff: ignore[private-member-access]
    assert document_convert._document_kind("scan.pdf") == "pdf"  # ruff: ignore[private-member-access]
