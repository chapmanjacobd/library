from library.document import document_convert


def test_document_kind_uses_known_extensions():
    assert document_convert._document_kind("notes.md") == "text"
    assert document_convert._document_kind("photo.jpg") == "image"
    assert document_convert._document_kind("scan.pdf") == "pdf"
