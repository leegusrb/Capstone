import asyncio
import os
import re
import sys
from datetime import datetime
from io import BytesIO
from types import ModuleType, SimpleNamespace

from fastapi import BackgroundTasks, UploadFile

os.environ.setdefault("DATABASE_URL", "sqlite:///tmp/test.db")
os.environ.setdefault("OPENAI_API_KEY", "test")
sys.modules.setdefault("fitz", ModuleType("fitz"))

from app.api.v1 import documents
from app.models.document import Document


CURRENT_USER = SimpleNamespace(id=1, username="alice")


def _compile_filter(expr) -> str:
    return str(expr.compile(compile_kwargs={"literal_binds": True}))


class FilteringDB:
    def __init__(self, document_rows):
        self.document_rows = document_rows

    def query(self, model):
        assert model is Document
        return FilteringQuery(self.document_rows)


class FilteringQuery:
    def __init__(self, rows):
        self.rows = list(rows)

    def join(self, *_args, **_kwargs):
        return self

    def filter(self, *conditions):
        for condition in conditions:
            text = _compile_filter(condition)
            self.rows = [row for row in self.rows if _matches(row, text)]
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


def _matches(row, condition: str) -> bool:
    if "knowledge_graphs.reference_kg IS NOT NULL" in condition:
        return getattr(row.knowledge_graph, "reference_kg", None) is not None

    if "documents.user_id" in condition:
        return row.user_id == int(_rhs(condition))

    if "documents.id" in condition:
        return row.id == int(_rhs(condition))

    if "documents.file_hash" in condition:
        return row.file_hash == _rhs(condition).strip("'")

    if "documents.status" in condition:
        return row.status == _rhs(condition).strip("'")

    return True


def _rhs(condition: str) -> str:
    return re.split(r"\s=\s", condition, maxsplit=1)[1].strip()


def _document(id, user_id, file_hash="hash", status="done"):
    return SimpleNamespace(
        id=id,
        user_id=user_id,
        filename=f"lecture-{id}.pdf",
        file_path=f"/tmp/lecture-{id}.pdf",
        file_hash=file_hash,
        status=status,
        created_at=datetime(2026, 6, 7),
        chunks=[],
        knowledge_graph=SimpleNamespace(reference_kg={"nodes": [], "edges": []}),
    )


def test_list_documents_returns_only_current_user_documents():
    db = FilteringDB([
        _document(1, 1),
        _document(2, 2),
        _document(3, None),
    ])

    response = documents.list_documents(db=db, current_user=CURRENT_USER)

    assert [doc.id for doc in response] == [1]


def test_find_cached_document_scopes_cache_to_current_user():
    db = FilteringDB([
        _document(1, 2, file_hash="same"),
        _document(2, 1, file_hash="same"),
    ])

    cached = documents._find_cached_document(db, file_hash="same", user_id=1)

    assert cached.id == 2
    assert documents._find_cached_document(db, file_hash="same", user_id=99) is None


class UploadDB:
    def __init__(self):
        self.document = None
        self.committed = False

    def add(self, document):
        self.document = document
        document.id = 7
        document.created_at = datetime(2026, 6, 7)

    def commit(self):
        self.committed = True

    def refresh(self, _document):
        return None


def test_upload_document_returns_processing_and_registers_background(monkeypatch, tmp_path):
    db = UploadDB()
    background_tasks = BackgroundTasks()
    upload = UploadFile(filename="lecture.pdf", file=BytesIO(b"%PDF"))
    saved_path = tmp_path / "lecture.pdf"

    monkeypatch.setattr(
        documents,
        "save_uploaded_file",
        lambda _file_bytes, _filename: str(saved_path),
    )

    response = asyncio.run(
        documents.upload_document(
            background_tasks=background_tasks,
            file=upload,
            db=db,
            current_user=CURRENT_USER,
        )
    )

    assert response.id == 7
    assert response.status == "processing"
    assert response.chunk_count == 0
    assert db.document.user_id == CURRENT_USER.id
    assert db.document.status == "processing"
    assert len(background_tasks.tasks) == 1


class BackgroundDB:
    def __init__(self, document):
        self.document = document
        self.committed = False
        self.closed = False

    def query(self, _model):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.document

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_background_processing_marks_document_done(monkeypatch):
    document = SimpleNamespace(id=1, status="processing")
    db = BackgroundDB(document)

    monkeypatch.setattr(documents, "SessionLocal", lambda: db)
    monkeypatch.setattr(documents, "_process_document_upload", lambda _db, _document: 1)

    documents.process_document_upload_background(1)

    assert document.status == "done"
    assert db.committed is True
    assert db.closed is True


def test_background_processing_marks_document_failed(monkeypatch):
    document = SimpleNamespace(id=1, status="processing")
    db = BackgroundDB(document)

    def fail(_db, _document):
        raise RuntimeError("boom")

    monkeypatch.setattr(documents, "SessionLocal", lambda: db)
    monkeypatch.setattr(documents, "_process_document_upload", fail)

    documents.process_document_upload_background(1)

    assert document.status == "failed"
    assert db.committed is True
    assert db.closed is True
