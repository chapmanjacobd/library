from library.document import document_convert


def test_document_kind_uses_known_extensions():
    assert document_convert._document_kind("notes.md") == "text"  # noqa: SLF001
    assert document_convert._document_kind("photo.jpg") == "image"  # noqa: SLF001
    assert document_convert._document_kind("scan.pdf") == "pdf"  # noqa: SLF001
