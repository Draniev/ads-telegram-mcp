"""Offline full catalogue retrieval and peer resolution through MCP and TeleAd."""

import unittest
from unittest.mock import Mock, patch

import anyio
from mcp.server.mcpserver.exceptions import ToolError
from telead.errors import TransportError

from ads_telegram_mcp.config import Settings
from ads_telegram_mcp.server import create_server


class TargetingTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(Settings(
            token="offline-test-token", account_id="default-related", _env_file=None,
        ))
        self.requests = []
        self.route = None

        def request(session, verb, url, **kwargs):
            method = url.rsplit("/", 1)[-1]
            self.requests.append((method, kwargs["json"]))
            if self.route is None:
                raise AssertionError("No HTTP fixture configured; real network forbidden")
            body = self.route(method, kwargs["json"])
            return Mock(status_code=200, headers={}, json=lambda: body)

        http = patch("requests.Session.request", autospec=True, side_effect=request)
        http.start()
        self.addCleanup(http.stop)

    def call(self, tool="get_targeting_options", **arguments):
        result = anyio.run(self.server.call_tool, tool, arguments)
        return result.structured_content

    def test_catalogues_return_full_lists_from_the_correct_methods(self):
        cases = [
            ("languages", "getTargetLanguagesList",
             [{"language_code": "ru", "name": "Russian"},
              {"language_code": "en", "name": "English"}]),
            ("topics", "getTargetTopicsList",
             [{"topic_id": 42, "name": "Travel"},
              {"topic_id": 7, "name": "Education"}]),
            ("countries", "getTargetCountriesList",
             [{"country_code": "TR", "name": "Turkey"},
              {"country_code": "US", "name": "United States"}]),
        ]
        for catalog, method, source in cases:
            with self.subTest(catalog=catalog):
                self.requests.clear()
                self.route = lambda name, params: {"ok": True, "result": source}
                result = self.call(catalog=catalog)
                self.assertEqual(self.requests, [(method, {})])
                self.assertEqual(result, {
                    "catalog": catalog, "options": source, "total_count": len(source),
                })

    def test_large_catalogue_preserves_all_entries_order_duplicates_and_raw_fields(self):
        source = [
            {"topic_id": value, "name": "Travel", "future_field": value}
            for value in [5, 3, 3, *range(205)]
        ]
        self.route = lambda name, params: {"ok": True, "result": source}
        result = self.call(catalog="topics")
        self.assertEqual(result["options"], source)
        self.assertEqual(result["total_count"], len(source))
        self.assertEqual(self.requests, [("getTargetTopicsList", {})])

    def test_repeated_calls_fetch_current_data_without_caching(self):
        source = [{"language_code": "de", "name": "Straße"}]
        self.route = lambda name, params: {"ok": True, "result": source}
        self.assertEqual(self.call(catalog="languages")["options"], source)
        source = []
        self.assertEqual(self.call(catalog="languages"), {
            "catalog": "languages", "options": [], "total_count": 0,
        })
        self.assertEqual(self.requests, [("getTargetLanguagesList", {})] * 2)

    def test_locations_fetch_all_pages_with_opaque_cursors_and_preserve_duplicates(self):
        first = [{"location_id": 123, "name": "Стамбул", "region": "Istanbul"}]
        last = [first[0], {"location_id": 456, "name": "Istanbul district"}]

        def route(name, params):
            if "offset" not in params:
                return {"ok": True, "result": {
                    "locations": first, "total_count": 41, "next_offset": "opaque:+/==",
                }}
            return {"ok": True, "result": {"locations": last, "total_count": 41}}

        self.route = route
        result = self.call("get_target_locations", country_code="TR", query="Istanbul")
        self.assertEqual(result, {
            "locations": first + last, "total_count": 3,
        })
        self.assertEqual(self.requests, [
            ("getTargetLocationsList", {
                "country_code": "TR", "query": "Istanbul", "limit": 100,
            }),
            ("getTargetLocationsList", {
                "country_code": "TR", "query": "Istanbul",
                "offset": "opaque:+/==", "limit": 100,
            }),
        ])

    def test_empty_location_search_returns_an_empty_complete_result(self):
        self.route = lambda name, params: {"ok": True, "result": {"locations": [], "total_count": 0}}
        result = self.call("get_target_locations", country_code="TR", query="missing")
        self.assertEqual(result, {
            "locations": [], "total_count": 0,
        })

    def test_broken_location_pagination_fails_instead_of_returning_partial_data(self):
        for locations, expected_calls in (([], 1), ([{"location_id": 1, "name": "City"}], 2)):
            with self.subTest(locations=locations):
                self.requests.clear()
                self.route = lambda name, params: {"ok": True, "result": {
                    "locations": locations, "next_offset": "repeated-cursor",
                }}
                with self.assertRaises(ToolError) as raised:
                    self.call("get_target_locations", country_code="TR", query="city")
                self.assertIn("Cannot retrieve all locations", str(raised.exception))
                self.assertEqual(len(self.requests), expected_calls)

    def test_catalogue_and_location_tools_have_separate_schemas(self):
        tools = anyio.run(self.server.list_tools)
        tool = next(tool for tool in tools if tool.name == "get_targeting_options")
        self.assertEqual(set(tool.input_schema["properties"]), {"catalog", "profile"})
        self.assertEqual(tool.input_schema["properties"]["catalog"]["enum"], [
            "languages", "topics", "countries",
        ])
        locations = next(tool for tool in tools if tool.name == "get_target_locations")
        self.assertEqual(set(locations.input_schema["properties"]), {
            "query", "country_code", "profile",
        })
        self.assertEqual(set(locations.input_schema["required"]), {
            "query", "country_code",
        })

    def test_invalid_catalogue_requests_fail_before_http(self):
        cases = [
            {"catalog": "unknown"}, {"catalog": "locations"},
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(ToolError):
                self.call(**arguments)
        self.assertEqual(self.requests, [])

    def test_invalid_location_requests_fail_before_http(self):
        cases = [
            {}, {"country_code": "TR"}, {"query": "Istanbul"},
            {"country_code": "TR", "query": ""},
            {"country_code": "TR", "query": "  "},
            {"country_code": "TUR", "query": "Istanbul"},
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaises(ToolError):
                self.call("get_target_locations", **arguments)
        self.assertEqual(self.requests, [])

    def test_channel_resolution_preserves_fields_and_exclusion_flag(self):
        channel = {"channel_id": 2**40, "title": "Example", "username": "example", "photo_url": "https://example.org/p", "future_field": 1}
        self.route = lambda name, params: {"ok": True, "result": channel}
        result = self.call("get_target_channel", channel_id="@example", for_excluding=True)
        self.assertEqual(result, channel)
        self.assertEqual(self.requests, [("getTargetChannel", {"channel_id": "@example", "for_excluding": True})])

    def test_bot_numeric_id_and_missing_optional_metadata(self):
        bot = {"bot_id": 2**40}
        self.route = lambda name, params: {"ok": True, "result": bot}
        self.assertEqual(self.call("get_target_bot", bot_id=2**40), bot)
        self.assertEqual(self.requests, [("getTargetBot", {"bot_id": 2**40})])

    def test_invalid_peer_types_do_not_reach_http(self):
        for tool, field in (("get_target_channel", "channel_id"), ("get_target_bot", "bot_id")):
            for value in (True, 1.5, None, ""):
                with self.subTest(tool=tool, value=value), self.assertRaises(ToolError):
                    self.call(tool, **{field: value})
        self.assertEqual(self.requests, [])

    def test_api_errors_keep_codes_and_hide_response_details(self):
        self.route = lambda name, params: {
            "ok": False, "error": "CHANNEL_ID_UNKNOWN",
            "description": "offline-test-token private details",
        }
        with self.assertRaises(ToolError) as raised:
            self.call("get_target_channel", channel_id=123)
        self.assertIn("CHANNEL_ID_UNKNOWN", str(raised.exception))
        self.assertNotIn("offline-test-token", str(raised.exception))
        self.assertNotIn("private details", str(raised.exception))

    def test_transport_errors_are_sanitized(self):
        def route(name, params):
            raise TransportError("offline-test-token private details")

        self.route = route
        with patch("telead.client.Client._sleep_backoff"), self.assertRaises(ToolError) as raised:
            self.call("get_target_bot", bot_id="@example_bot")
        self.assertIn("failed or timed out", str(raised.exception))
        self.assertNotIn("offline-test-token", str(raised.exception))
        self.assertNotIn("private details", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
