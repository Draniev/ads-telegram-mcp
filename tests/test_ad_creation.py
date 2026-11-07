"""Offline validation and wire-level creation checks with no real cabinet writes."""

from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

import anyio
from mcp.server.mcpserver.exceptions import ToolError
from telead.errors import TransportError

from ads_telegram_mcp.config import Settings
from ads_telegram_mcp.server import create_server


def new_ad(key="one", **fields):
    return {
        "title": "Example", "text": "Hello", "promote_url": "https://t.me/example",
        "cpm": 0.3, "placement": "channel_post",
        "target": {"type": "channels", "channel_ids": ["@example", "@example"]},
        "idempotency_key": key, **fields,
    }


class CreationTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(Settings(
            token="offline-test-token", account_id="default-related", _env_file=None,
        ))
        self.requests = []
        self.route = None

        def request(session, verb, url, **kwargs):
            method = url.rsplit("/", 1)[-1]
            self.requests.append((session, method, kwargs))
            params = kwargs["json"]
            body = self.route(method, params) if self.route else self.default_route(method, params)
            status, body = body if isinstance(body, tuple) else (200, body)
            return Mock(status_code=status, headers={}, json=lambda: body)

        http = patch("requests.Session.request", autospec=True, side_effect=request)
        http.start()
        self.addCleanup(http.stop)

    def default_route(self, method, params):
        if method == "getCurrentAccount":
            return {"ok": True, "result": {"account_id": "owner", "currency": "TON"}}
        if method == "getAccountsById":
            return {"ok": True, "result": [
                {"account_id": params["account_ids"][0], "currency": "TON"},
            ]}
        if method == "createAd":
            return {"ok": True, "result": {
                "ad_id": 42, "title": params["title"], "currency": "TON",
                "status": "ready_for_review", "is_paused": params["is_paused"],
                "cpm": 0.35, "remaining_budget": params["initial_budget"],
            }}
        raise AssertionError("Unexpected API method")

    def call(self, ads=None, **arguments):
        result = anyio.run(self.server.call_tool, "create_ads", {
            "ads": [new_ad()] if ads is None else ads, **arguments,
        })
        return result.structured_content

    def writes(self):
        return [call[2] for call in self.requests if call[1] == "createAd"]

    def test_defaults_order_duplicate_keys_and_actual_api_values(self):
        result = self.call([new_ad(), new_ad()])
        self.assertEqual([call[1] for call in self.requests],
                         ["getAccountsById", "createAd", "createAd"])
        self.assertEqual(len({id(call[0]) for call in self.requests}), 1)
        self.assertEqual(result["account_id"], "default-related")
        self.assertTrue(result["complete"])
        self.assertEqual(result["succeeded_count"], 2)
        self.assertEqual([item["index"] for item in result["results"]], [0, 1])
        for write in self.writes():
            self.assertEqual(write["headers"]["Idempotency-Key"], "one")
            self.assertEqual(write["json"]["initial_budget"], 0)
            self.assertTrue(write["json"]["is_paused"])
            self.assertEqual(write["json"]["account_id"], "default-related")
            self.assertEqual(write["json"]["target"]["channel_ids"], ["@example", "@example"])
        self.assertEqual(result["results"][0]["ad"]["cpm"], 0.35)

    def test_account_override_and_token_owner(self):
        self.call(account_id="explicit")
        self.assertEqual(self.requests[0][2]["json"], {"account_ids": ["explicit"]})
        self.assertEqual(self.writes()[0]["json"]["account_id"], "explicit")
        self.requests.clear()
        self.server = create_server(Settings(token="offline-test-token", account_id=None, _env_file=None))
        result = self.call()
        self.assertEqual(self.requests[0][1], "getCurrentAccount")
        self.assertEqual(self.writes()[0]["json"]["account_id"], "owner")
        self.assertEqual(result["account_id"], "owner")

    def test_all_optional_fields_are_forwarded_without_losing_false_or_zero(self):
        item = new_ad(
            promote_url="https://example.org", website_name="Example", website_photo_id="logo",
            placement="channel_post", target={"type": "users", "country_codes": ["US"]},
            photo_id="photo", show_userpic=False, impression_frequency=4,
            initial_budget=5, is_paused=False, daily_budget_limit=0,
            button="", conversion_event_id="event", additional_info="",
            activate_date=123, deactivate_date=456,
            schedule={"week_hours_mask": [1] * 7, "use_viewer_timezone": True},
        )
        self.call([item])
        params = self.writes()[0]["json"]
        for field in ("website_name", "website_photo_id", "photo_id", "show_userpic",
                      "impression_frequency", "initial_budget", "is_paused", "daily_budget_limit",
                      "button", "conversion_event_id", "additional_info", "activate_date", "deactivate_date"):
            self.assertEqual(params[field], item[field])
        self.assertEqual(params["schedule"], item["schedule"])
        self.assertEqual(params["target"], item["target"])

    def test_dry_run_without_token_or_http_for_all_target_types(self):
        self.server = create_server(Settings(token="", account_id=None, _env_file=None))
        for target, placement, text in (
            ({"type": "channels", "language_codes": ["en"]}, "channel_post", "Hello"),
            ({"type": "users", "country_codes": ["US"]}, "video_banner", "Hello"),
            ({"type": "bots", "bot_ids": ["@example_bot"]}, "bot_banner", "Hello"),
            ({"type": "search", "search_queries": ["example"]}, "search_result", None),
        ):
            with self.subTest(target=target):
                result = self.call([new_ad(target=target, placement=placement, text=text)], dry_run=True)
                self.assertTrue(result["dry_run"])
                self.assertEqual(result["validated_count"], 1)
                self.assertIsNone(result["currency"])
                self.assertEqual(result["ads"][0]["target"]["type"], target["type"])
        self.assertEqual(self.requests, [])

    def test_invalid_batch_is_rejected_before_even_account_lookup(self):
        invalid = [
            {"cpm": -1}, {"cpm": float("nan")}, {"initial_budget": -1},
            {"title": "я" * 65}, {"text": "x" * 161}, {"text": None},
            {"typo": True}, {"idempotency_key": " "}, {"placement": "search_result"},
            {"photo_id": "p", "video_id": "v"},
            {"target": {"type": "channels", "topic_ids": [1]}},
            {"target": {"type": "channels", "channel_ids": ["@a"], "language_codes": ["en"]}},
            {"target": {"type": "channels", "channel_ids": ["@a"] * 100, "exclude_channel_ids": ["@b"]}},
            {"target": {"type": "users", "country_codes": ["US", "GB"], "location_ids": [1]}},
            {"target": {"type": "users", "audience_ids": [1, 2, 3, 4, 5]}},
            {"target": {"type": "users", "exclude_political_channels": True, "political_channels_only": True}},
            {"target": {"type": "bots", "bot_ids": ["@bot"]}, "placement": "bot_banner", "photo_id": "p"},
            {"schedule": {"week_hours_mask": [1] * 6, "timezone": 0}},
            {"schedule": {"week_hours_mask": [1] * 7, "timezone": 1}},
            {"schedule": {"week_hours_mask": [1] * 7, "use_viewer_timezone": True}},
            {"promote_url": "https://example.org"},
            {"promote_url": "https://t.me@evil.example"},
            {"promote_url": "relative/path"}, {"website_name": "irrelevant"},
        ]
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ToolError):
                self.call([new_ad("valid"), new_ad("invalid", **fields)])
        with self.assertRaises(ToolError):
            self.call([])
        self.assertEqual(self.requests, [])

    def test_error_in_middle_respects_stop_on_error(self):
        def route(method, params):
            if method == "createAd" and params["title"] == "bad":
                return {"ok": False, "error": "AD_TITLE_INVALID", "description": "offline-test-token private"}
            return self.default_route(method, params)

        self.route = route
        for stop, expected in ((True, ["succeeded", "failed", "not_attempted"]),
                               (False, ["succeeded", "failed", "succeeded"])):
            with self.subTest(stop=stop):
                self.requests.clear()
                result = self.call([new_ad("one"), new_ad("two", title="bad"), new_ad("three")], stop_on_error=stop)
                self.assertEqual([item["outcome"] for item in result["results"]], expected)
                self.assertFalse(result["complete"])
                self.assertEqual(result["failed_count"], 1)
                self.assertEqual(result["results"][1]["error"]["code"], "AD_TITLE_INVALID")
                self.assertNotIn("offline-test-token", str(result))
                self.assertNotIn("deleteAd", [call[1] for call in self.requests])

    def test_global_creation_errors_stop_even_when_continuation_requested(self):
        for code in ("ACCESS_TOKEN_INVALID", "ACCESS_DENIED", "TOO_MANY_REQUESTS"):
            with self.subTest(code=code):
                self.requests.clear()
                self.route = lambda method, params: ({"ok": False, "error": code}
                    if method == "createAd" else self.default_route(method, params))
                with patch("telead.client.Client._sleep_backoff"):
                    result = self.call([new_ad(), new_ad("two")], stop_on_error=False)
                self.assertEqual([item["outcome"] for item in result["results"]], ["failed", "not_attempted"])

    def test_uncertain_outcomes_preserve_key_and_do_not_claim_rejection(self):
        for failure in ("transport", "server", "in_progress", "malformed"):
            with self.subTest(failure=failure):
                self.requests.clear()

                def route(method, params):
                    if method != "createAd":
                        return self.default_route(method, params)
                    if failure == "transport":
                        raise TransportError("offline-test-token details")
                    if failure == "server":
                        return 500, {"ok": False, "error": "SERVER_ERROR"}
                    if failure == "in_progress":
                        return {"ok": False, "error": "IDEMPOTENT_REQUEST_IN_PROGRESS"}
                    return {"ok": True, "result": {}}

                self.route = route
                with patch("telead.client.Client._sleep_backoff"):
                    result = self.call([new_ad("stable"), new_ad("two")])
                self.assertEqual([item["outcome"] for item in result["results"]], ["unknown", "not_attempted"])
                self.assertEqual(result["unknown_count"], 1)
                self.assertEqual(result["failed_count"], 0)
                self.assertTrue(all(write["headers"]["Idempotency-Key"] == "stable" for write in self.writes()))
                self.assertNotIn("offline-test-token", str(result))

    def test_idempotent_replay_keeps_identical_wire_parameters(self):
        saved = {}

        def route(method, params):
            if method != "createAd":
                return self.default_route(method, params)
            key = self.writes()[-1]["headers"]["Idempotency-Key"]
            if key not in saved:
                saved[key] = (deepcopy(params), self.default_route(method, params))
            self.assertEqual(params, saved[key][0])
            return saved[key][1]

        self.route = route
        first = self.call([new_ad("stable", activate_date=123)])
        second = self.call([new_ad("stable", activate_date=123)])
        self.assertEqual(first, second)
        self.assertEqual(len(saved), 1)

    def test_continuation_keeps_an_uncertain_outcome_without_losing_next_result(self):
        def route(method, params):
            if method == "createAd" and params["title"] == "lost-response":
                raise TransportError("offline-test-token details")
            return self.default_route(method, params)

        self.route = route
        with patch("telead.client.Client._sleep_backoff"):
            result = self.call([
                new_ad("uncertain", title="lost-response"), new_ad("next"),
            ], stop_on_error=False)
        self.assertEqual([item["outcome"] for item in result["results"]], ["unknown", "succeeded"])
        self.assertEqual(result["unknown_count"], 1)
        self.assertEqual(result["succeeded_count"], 1)
        self.assertFalse(result["complete"])

    def test_unresolved_account_does_not_attempt_creation(self):
        self.route = lambda method, params: {"ok": True, "result": []}
        with self.assertRaises(ToolError) as raised:
            self.call(account_id="missing")
        self.assertIn("not accessible", str(raised.exception))
        self.assertEqual(self.writes(), [])


if __name__ == "__main__":
    unittest.main()
