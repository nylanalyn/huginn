from __future__ import annotations

from briefing.llm.parse import parse_summary_response


def test_parse_fenced_json_response() -> None:
    result = parse_summary_response(
        """```json
        {"lede": "Quick read.", "summaries": [{"item_num": 1, "summary": "Useful summary."}]}
        ```""",
        item_count=1,
    )

    assert result is not None
    assert result.lede == "Quick read."
    assert result.summaries == {1: "Useful summary."}


def test_parse_garbage_response_degrades_to_none() -> None:
    assert parse_summary_response("not json", item_count=1) is None


def test_parse_missing_and_out_of_range_items_are_ignored() -> None:
    result = parse_summary_response(
        """
        {
          "lede": "",
          "summaries": [
            {"item_num": 1, "summary": ""},
            {"item_num": 2, "summary": "Good."},
            {"item_num": 9, "summary": "Bad."}
          ]
        }
        """,
        item_count=2,
    )

    assert result is not None
    assert result.summaries == {2: "Good."}
