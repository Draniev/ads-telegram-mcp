"""Offline MCP-to-TeleAd integration for composed per-ad statistics."""

import unittest
from unittest.mock import Mock, patch

import anyio
from mcp.server.mcpserver.exceptions import ToolError
from telead.errors import TransportError

from ads_telegram_mcp.config import Settings
from ads_telegram_mcp.server import create_server

DAY = 86400


def point(spent: float, *, currency: str = "TON", **fields) -> dict:
    return {
        "from_time": 0, "to_time": DAY, "currency": currency,
        "views": 10, "opens": 2, "clicks": 3, "actions": 1,
        "spent_budget": spent, **fields,
    }


class AdsStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = create_server(Settings(
            token="offline-test-token", account_id="default-related", _env_file=None,
        ))
        self.requests = []
        self.route = None

        def request(session, verb, url, **kwargs):
            method = url.rsplit("/", 1)[-1]
            params = kwargs["json"]
            self.requests.append((session, method, params))
            if self.route is None:
                raise AssertionError("Network forbidden: no HTTP fixture configured")
            body = self.route(method, params)
            return Mock(status_code=200, headers={}, json=lambda: body)

        http = patch("requests.Session.request", autospec=True, side_effect=request)
        http.start()
        self.addCleanup(http.stop)

    def call(self, **arguments) -> dict:
        args = {"from_time": 0, "to_time": 2 * DAY, **arguments}
        result = anyio.run(self.server.call_tool, "get_ads_stats", args)
        return result.structured_content

    def test_selected_ids_skip_listing_deduplicate_and_sum_with_one_session(self) -> None:
        self.route = lambda method, params: {"ok": True, "result": [point(0.1), point(0.2)]}
        result = self.call(ad_ids=[7, 8, 7], account_id="explicit")
        self.assertEqual([call[1] for call in self.requests], ["getAdStats", "getAdStats"])
        self.assertEqual([call[2]["ad_id"] for call in self.requests], [7, 8])
        self.assertEqual({id(call[0]) for call in self.requests}, {id(self.requests[0][0])})
        self.assertTrue(all(call[2]["account_id"] == "explicit" for call in self.requests))
        self.assertEqual(result["total_count"], 2)
        self.assertEqual(result["succeeded_count"], 2)
        self.assertTrue(result["complete"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["ads"][0]["totals"], {
            "currency": "TON", "views": 20, "opens": 4,
            "clicks": 6, "actions": 2, "spent_budget": 0.3,
        })
        self.assertEqual(result["ads"][0]["data_points"], 2)
        self.assertNotIn("stats", result["ads"][0])

    def test_empty_or_omitted_ids_traverse_all_pages_and_keep_stopped_ads(self) -> None:
        def route(method, params):
            if method == "getAdsList":
                page = (
                    {"ads": [{"ad_id": 1, "status": "active"}, {"ad_id": 2, "status": "stopped"}],
                     "next_offset": "opaque:+/=="}
                    if "offset" not in params else
                    {"ads": [{"ad_id": 2}, {"ad_id": 3}], "total_count": 3}
                )
                return {"ok": True, "result": page}
            return {"ok": True, "result": [point(1)]}

        self.route = route
        for arguments in ({"ad_ids": []}, {}, {"ad_ids": None}):
            with self.subTest(arguments=arguments):
                self.requests.clear()
                result = self.call(**arguments)
                self.assertEqual([row["ad_id"] for row in result["ads"]], [1, 2, 3])
                self.assertEqual(result["total_count"], 3)
                self.assertTrue(result["complete"])
                self.assertEqual([call[1] for call in self.requests],
                                 ["getAdsList", "getAdsList", "getAdStats", "getAdStats", "getAdStats"])
                self.assertEqual(self.requests[1][2]["offset"], "opaque:+/==")
                self.assertEqual(self.requests[0][2]["limit"], 100)
                self.assertTrue(all(call[2]["account_id"] == "default-related" for call in self.requests))

    def test_timeseries_is_opt_in_and_period_bounds_are_rounded(self) -> None:
        raw = point(0.5, future_field="preserved")
        self.route = lambda method, params: {"ok": True, "result": [raw]}
        result = self.call(ad_ids=[1], from_time=123, to_time=DAY + 123, include_timeseries=True)
        self.assertEqual((result["from_time"], result["to_time"]), (0, DAY))
        self.assertEqual(self.requests[0][2]["from_time"], 0)
        self.assertEqual(self.requests[0][2]["to_time"], DAY)
        self.assertEqual(result["ads"][0]["stats"], [raw])

    def test_per_ad_api_error_is_visible_and_does_not_drop_other_ads(self) -> None:
        def route(method, params):
            if params["ad_id"] == 2:
                return {"ok": False, "error": "AD_ID_INVALID", "description": "offline-test-token secret"}
            return {"ok": True, "result": [point(1)]}

        self.route = route
        result = self.call(ad_ids=[1, 2, 3])
        self.assertFalse(result["complete"])
        self.assertEqual((result["total_count"], result["succeeded_count"], result["failed_count"]), (3, 2, 1))
        self.assertEqual([row["ad_id"] for row in result["ads"]], [1, 3])
        self.assertEqual(result["errors"][0]["ad_id"], 2)
        self.assertIn("AD_ID_INVALID", result["errors"][0]["error"])
        self.assertNotIn("offline-test-token", str(result))

    def test_transport_failure_is_sanitized_and_other_ads_continue(self) -> None:
        def route(method, params):
            if params["ad_id"] == 2:
                raise TransportError("offline-test-token transport details")
            return {"ok": True, "result": [point(1)]}

        self.route = route
        with patch("telead.client.Client._sleep_backoff"):
            result = self.call(ad_ids=[1, 2, 3])
        self.assertFalse(result["complete"])
        self.assertEqual(result["succeeded_count"], 2)
        self.assertEqual(result["errors"][0]["ad_id"], 2)
        self.assertNotIn("offline-test-token", str(result))

    def test_auth_permission_and_rate_limit_failures_stop_the_operation(self) -> None:
        for code in ("ACCESS_TOKEN_INVALID", "ACCESS_DENIED", "TOO_MANY_REQUESTS"):
            with self.subTest(code=code):
                self.requests.clear()
                self.route = lambda method, params: {"ok": False, "error": code}
                with patch("telead.client.Client._sleep_backoff"), self.assertRaises(ToolError) as raised:
                    self.call(ad_ids=[1, 2, 3])
                self.assertIn(code, str(raised.exception))
                self.assertEqual({call[2]["ad_id"] for call in self.requests}, {1})

    def test_empty_account_and_empty_statistics_are_distinct(self) -> None:
        self.route = lambda method, params: {"ok": True, "result": {"ads": [], "total_count": 0}}
        result = self.call(ad_ids=[])
        self.assertTrue(result["complete"])
        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["ads"], [])
        self.assertEqual(len(self.requests), 1)
        self.route = lambda method, params: {"ok": True, "result": []}
        result = self.call(ad_ids=[7], include_timeseries=True)
        self.assertEqual(result["ads"], [{"ad_id": 7, "data_points": 0, "totals": None, "stats": []}])
        self.assertEqual(result["succeeded_count"], 1)

    def test_broken_pagination_does_not_return_an_incomplete_success(self) -> None:
        for ads in ([{"ad_id": 1}], []):
            with self.subTest(ads=ads):
                self.requests.clear()
                self.route = lambda method, params: {"ok": True, "result": {"ads": ads, "next_offset": "cycle"}}
                with self.assertRaises(ToolError) as raised:
                    self.call()
                self.assertIn("Cannot get all ads", str(raised.exception))
                self.assertTrue(all(call[1] == "getAdsList" for call in self.requests))
                self.assertLessEqual(len(self.requests), 2)

    def test_invalid_parameters_are_rejected_before_api_calls(self) -> None:
        for arguments in (
            {"from_time": DAY, "to_time": 0},
            {"from_time": 0, "to_time": DAY, "interval": 60},
            {"from_time": 0, "to_time": 1001 * DAY},
            {"from_time": 1, "to_time": 2},
            {"ad_ids": ["invalid-id"]},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ToolError):
                self.call(**arguments)
        self.assertEqual(self.requests, [])

    def test_different_currencies_are_never_added_together(self) -> None:
        self.route = lambda method, params: {"ok": True, "result": [point(1, currency="TON"), point(2, currency="EUR")]}
        with self.assertRaises(ToolError):
            self.call(ad_ids=[1])


if __name__ == "__main__":
    unittest.main()
