import os

os.environ.setdefault("DATABASE_URL", "sqlite:///tmp/test.db")
os.environ.setdefault("OPENAI_API_KEY", "test")

from app.services.kg_service import (
    strip_checklist_for_reference_view,
    strip_checklist_for_user_view,
)


def _sample_kg():
    return {
        "nodes": [
            {
                "id": "TCP",
                "status": "partial",
                "checklist": [
                    {
                        "item": "Explain that TCP is connection-oriented",
                        "source_quote": "TCP is a connection-oriented protocol.",
                        "page_number": 7,
                    },
                    {
                        "item": "Explain ACK usage",
                        "source_quote": "ACK is used for acknowledgements.",
                    },
                ],
                "checklist_result": [
                    {"item": "Explain that TCP is connection-oriented", "met": True},
                ],
            },
        ],
        "edges": [],
    }


def test_user_view_includes_stored_source_page_when_enabled():
    chunks = [
        {"content": "Other content", "page_number": 1},
        {
            "content": "TCP is a connection-oriented protocol. It provides reliable transport.",
            "page_number": 3,
        },
    ]

    view = strip_checklist_for_user_view(
        _sample_kg(),
        chunks=chunks,
        include_sources=True,
    )
    checklist = view["nodes"][0]["checklist"]

    assert checklist[0]["met"] is True
    assert checklist[0]["source_quote"] == "TCP is a connection-oriented protocol."
    assert checklist[0]["page_number"] == 7
    assert checklist[1]["met"] is False
    assert checklist[1]["page_number"] is None
    assert view["nodes"][0]["met_count"] == 1
    assert view["nodes"][0]["total_count"] == 2


def test_user_view_falls_back_to_chunk_match_for_legacy_items():
    kg = _sample_kg()
    del kg["nodes"][0]["checklist"][0]["page_number"]
    chunks = [
        {
            "content": "TCP is a connection-oriented protocol. It provides reliable transport.",
            "page_number": 3,
        },
    ]

    view = strip_checklist_for_user_view(kg, chunks=chunks, include_sources=True)

    assert view["nodes"][0]["checklist"][0]["page_number"] == 3


def test_default_user_and_reference_views_hide_source_quote():
    user_view = strip_checklist_for_user_view(_sample_kg())
    ref_view = strip_checklist_for_reference_view(_sample_kg())

    assert "source_quote" not in user_view["nodes"][0]["checklist"][0]
    assert "page_number" not in user_view["nodes"][0]["checklist"][0]
    assert "checklist" not in ref_view["nodes"][0]


if __name__ == "__main__":
    test_user_view_includes_stored_source_page_when_enabled()
    test_user_view_falls_back_to_chunk_match_for_legacy_items()
    test_default_user_and_reference_views_hide_source_quote()
    print("ok")
