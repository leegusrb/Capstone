import os
import sys
from types import ModuleType

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///tmp/test.db")
os.environ.setdefault("OPENAI_API_KEY", "test")
sys.modules.setdefault("fitz", ModuleType("fitz"))

from app.api.v1.documents import delete_document
from app.core.exceptions import DocumentNotFoundError
from app.models.document import Document


class FakeDB:
    def __init__(self, document):
        self.document = document
        self.deleted = None
        self.committed = False

    def query(self, _model):
        return FakeQuery(self.document)

    def delete(self, document):
        self.deleted = document

    def commit(self):
        self.committed = True


class FakeQuery:
    def __init__(self, document):
        self.document = document

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.document


def test_delete_document_removes_record_and_uploaded_file(tmp_path):
    file_path = tmp_path / "lecture.pdf"
    file_path.write_bytes(b"pdf")
    document = Document(id=7, filename="lecture.pdf", file_path=str(file_path), status="done")
    db = FakeDB(document)

    response = delete_document(7, db=db)

    assert response.id == 7
    assert response.deleted is True
    assert db.deleted is document
    assert db.committed is True
    assert not file_path.exists()


def test_delete_document_returns_404_when_missing():
    with pytest.raises(DocumentNotFoundError):
        delete_document(404, db=FakeDB(None))
