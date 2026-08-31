import json
from pathlib import Path
import sys
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit


SCRIPTS_PATH = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_PATH))

from zotero_skill import core as zotero


def json_response(rows, *, total=None, header_name="Total-Results"):
    headers = {"Content-Type": "application/json"}
    if total is not None:
        headers[header_name] = str(total)
    return zotero.Response(status=200, headers=headers, text=json.dumps(rows))


class ApiGetAllTests(unittest.TestCase):
    def test_reads_every_page_and_preserves_filters(self):
        pages = [
            json_response([{"key": "A"}, {"key": "B"}], total=3),
            json_response([{"key": "C"}], total=3),
        ]

        with mock.patch.object(zotero, "api_response", side_effect=pages) as request:
            rows = zotero.api_get_all("/api/users/0/items/top", {"q": "attention"})

        self.assertEqual([row["key"] for row in rows], ["A", "B", "C"])
        self.assertEqual(request.call_count, 2)
        first_query = parse_qs(urlsplit(request.call_args_list[0].args[0]).query)
        second_query = parse_qs(urlsplit(request.call_args_list[1].args[0]).query)
        self.assertEqual(first_query, {"q": ["attention"], "limit": ["100"], "start": ["0"]})
        self.assertEqual(second_query, {"q": ["attention"], "limit": ["100"], "start": ["2"]})

    def test_stops_on_short_page_without_total_header(self):
        page = [{"key": str(index)} for index in range(zotero.API_PAGE_LIMIT)]
        pages = [json_response(page), json_response([{"key": "last"}])]

        with mock.patch.object(zotero, "api_response", side_effect=pages) as request:
            rows = zotero.api_get_all("/api/users/0/tags")

        self.assertEqual(len(rows), zotero.API_PAGE_LIMIT + 1)
        second_query = parse_qs(urlsplit(request.call_args_list[1].args[0]).query)
        self.assertEqual(second_query["start"], [str(zotero.API_PAGE_LIMIT)])

    def test_total_results_header_is_case_insensitive(self):
        response = json_response([], total=12, header_name="total-results")

        self.assertEqual(zotero.total_results(response), 12)

    def test_rejects_non_list_response(self):
        response = zotero.Response(
            status=200,
            headers={"Content-Type": "application/json"},
            text=json.dumps({"key": "A"}),
        )

        with mock.patch.object(zotero, "api_response", return_value=response):
            with self.assertRaisesRegex(SystemExit, "Expected a list response"):
                zotero.api_get_all("/api/users/0/items")


if __name__ == "__main__":
    unittest.main()
