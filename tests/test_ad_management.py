"""Single-ad writes through MCP and TeleAd, with every HTTP request mocked."""

from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

import anyio
from mcp.server.mcpserver.exceptions import ToolError
from telead.errors import TransportError

from ads_telegram_mcp.config import Settings
from ads_telegram_mcp.server import create_server

BUDGET_TOOLS = ("increase_ad_budget", "decrease_ad_budget")
WRITE_METHODS = {"increaseAdBudget", "decreaseAdBudget", "editAd", "submitAdForReview", "deleteAd"}


class AdManagementTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(Settings(
            token="offline-test-token", account_id="default-related", _env_file=None,
        ))
        self.requests = []
        self.route = self.default_route

        def request(session, verb, url, **kwargs):
            method = url.rsplit("/", 1)[-1]
            self.requests.append((session, method, kwargs))
            body = self.route(method, kwargs["json"])
            status, body = body if isinstance(body, tuple) else (200, body)
            return Mock(status_code=status, headers={}, json=lambda: body)

        http = patch("requests.Session.request", autospec=True, side_effect=request)
        http.start()
        self.addCleanup(http.stop)

    def default_route(self, method, params):
        if method == "getAccountsById":
            return {"ok": True, "result": [{
                "account_id": params["account_ids"][0], "currency": "TON",
            }]}
        if method == "getCurrentAccount":
            return {"ok": True, "result": {"account_id": "owner", "currency": "EUR"}}
        if method == "deleteAd":
            return {"ok": True, "result": True}
        if method in WRITE_METHODS:
            return {"ok": True, "result": {
                "ad_id": params["ad_id"], "remaining_budget": 12.5,
                "status": "in_review", "future_field": {"preserved": True},
                **({"text": params["text"]} if "text" in params else {}),
            }}
        raise AssertionError("Unexpected HTTP call; real network forbidden")

    def call(self, tool="increase_ad_budget", **arguments):
        arguments = {"ad_id": 42, **arguments}
        if tool in BUDGET_TOOLS:
            arguments = {"amount": 5, "idempotency_key": "stable", **arguments}
        return anyio.run(self.server.call_tool, tool, arguments).structured_content

    def writes(self):
        return [request for request in self.requests if request[1] in WRITE_METHODS]

    def test_budget_transfers_use_the_amount_scope_and_caller_key(self):
        for tool, method in (
            ("increase_ad_budget", "increaseAdBudget"),
            ("decrease_ad_budget", "decreaseAdBudget"),
        ):
            with self.subTest(tool=tool):
                self.requests.clear()
                result = self.call(tool, return_target=True)
                self.assertEqual([item[1] for item in self.requests], ["getAccountsById", method])
                self.assertEqual(len({id(item[0]) for item in self.requests}), 1)
                write = self.writes()[0][2]
                self.assertEqual(write["json"], {
                    "account_id": "default-related", "ad_id": 42, "amount": 5,
                    "return_target": True,
                })
                self.assertEqual(write["headers"]["Idempotency-Key"], "stable")
                self.assertEqual(result["outcome"], "succeeded")
                self.assertEqual(result["currency"], "TON")
                self.assertEqual(result["idempotency_key"], "stable")
                self.assertEqual(result["ad"]["remaining_budget"], 12.5)
                self.assertEqual(result["ad"]["future_field"], {"preserved": True})

    def test_all_tools_resolve_explicit_default_or_token_owner_scope(self):
        for tool, method, extra in (
            ("increase_ad_budget", "increaseAdBudget", {}),
            ("decrease_ad_budget", "decreaseAdBudget", {}),
            ("edit_ad", "editAd", {"changes": {"is_paused": False}}),
            ("submit_ad_for_review", "submitAdForReview", {}),
            ("delete_ad", "deleteAd", {}),
        ):
            for configured, explicit, expected in (
                ("default-related", None, "default-related"),
                ("default-related", "explicit", "explicit"),
                (None, None, "owner"),
            ):
                with self.subTest(tool=tool, configured=configured, explicit=explicit):
                    self.requests.clear()
                    self.server = create_server(Settings(
                        token="offline-test-token", account_id=configured, _env_file=None,
                    ))
                    result = self.call(tool, account_id=explicit, **extra)
                    self.assertEqual(result["account_id"], expected)
                    self.assertEqual(result["currency"], "EUR" if expected == "owner" else "TON")
                    self.assertEqual(self.writes()[0][1], method)
                    self.assertEqual(self.writes()[0][2]["json"]["account_id"], expected)
                    self.assertEqual(len(self.writes()), 1)

    def test_partial_edit_only_sends_supplied_fields_including_false_zero_and_empty(self):
        changes = {
            "is_paused": False, "daily_budget_limit": 0, "show_userpic": False,
            "schedule": False, "button": "", "additional_info": "", "text": None,
        }
        result = self.call("edit_ad", changes=changes)
        self.assertEqual(result["outcome"], "succeeded")
        expected = {key: value for key, value in changes.items() if value is not None}
        self.assertEqual(self.writes()[0][2]["json"], {
            "account_id": "default-related", "ad_id": 42,
            "return_target": False, **expected,
        })
        self.assertNotIn("Idempotency-Key", self.writes()[0][2]["headers"])
        self.assertNotIn("idempotency_key", result)

    def test_edit_passes_all_supported_fields_and_serializes_schedule(self):
        changes = {
            "title": "Updated", "text": "New text", "promote_url": "https://example.org",
            "cpm": 1.25, "photo_id": "photo", "impression_frequency": 4,
            "website_name": "Example", "website_photo_id": "logo", "button": "read",
            "conversion_event_id": "event", "additional_info": "Info", "show_userpic": True,
            "daily_budget_limit": 20, "is_paused": True,
            "activate_date": 123, "deactivate_date": 456,
            "schedule": {"week_hours_mask": [1] * 7, "timezone": 0,
                         "use_viewer_timezone": False},
        }
        self.call("edit_ad", changes=changes, return_target=True)
        expected = {**changes, "schedule": {"week_hours_mask": [1] * 7, "timezone": 0}}
        self.assertEqual(self.writes()[0][2]["json"], {
            "account_id": "default-related", "ad_id": 42,
            "return_target": True, **expected,
        })
        self.requests.clear()
        self.call("edit_ad", changes={"video_id": "video"})
        self.assertEqual(self.writes()[0][2]["json"]["video_id"], "video")
        self.assertNotIn("photo_id", self.writes()[0][2]["json"])
        self.requests.clear()
        viewer_schedule = {"week_hours_mask": [1] * 7, "use_viewer_timezone": True}
        self.call("edit_ad", changes={"schedule": viewer_schedule})
        self.assertEqual(self.writes()[0][2]["json"]["schedule"], viewer_schedule)

    def test_review_is_one_write_without_an_extra_status_read_or_idempotency_key(self):
        result = self.call("submit_ad_for_review", return_target=True)
        self.assertEqual([item[1] for item in self.requests], [
            "getAccountsById", "submitAdForReview",
        ])
        self.assertEqual(self.writes()[0][2]["json"], {
            "account_id": "default-related", "ad_id": 42, "return_target": True,
        })
        self.assertNotIn("Idempotency-Key", self.writes()[0][2]["headers"])
        self.assertEqual(result["ad"]["status"], "in_review")

    def test_invalid_inputs_fail_before_account_lookup(self):
        invalid_budget = [
            {"amount": 0}, {"amount": -1}, {"amount": float("nan")}, {"amount": float("inf")},
            {"amount": True}, {"amount": "5"}, {"idempotency_key": " "},
            {"idempotency_key": "x" * 129}, {"idempotency_key": None},
        ]
        cases = [(tool, arguments) for tool in BUDGET_TOOLS for arguments in invalid_budget]
        invalid_changes = [
            {}, {"text": None}, {"typo": 1}, {"target": {"type": "channels"}},
            {"placement": "channel_post"}, {"initial_budget": 5},
            {"title": "я" * 65}, {"title": " "}, {"text": ""}, {"text": "x" * 161},
            {"text": " "}, {"cpm": 0}, {"cpm": float("inf")},
            {"photo_id": "p", "video_id": "v"}, {"impression_frequency": 5},
            {"is_paused": 0}, {"show_userpic": "false"}, {"daily_budget_limit": -1},
            {"schedule": True}, {"schedule": 0}, {"schedule": "false"},
            {"schedule": {"week_hours_mask": [1] * 6, "timezone": 0}},
            {"activate_date": -1}, {"website_name": "x" * 41}, {"button": "typo"},
            {"promote_url": "relative/path"},
        ]
        cases.extend(("edit_ad", {"changes": changes}) for changes in invalid_changes)
        for tool in (*BUDGET_TOOLS, "edit_ad", "submit_ad_for_review", "delete_ad"):
            for value in (True, 1.5, "42", [42]):
                cases.append((tool, {"ad_id": value, **({"changes": {"is_paused": False}}
                                                        if tool == "edit_ad" else {})}))
        for tool, arguments in cases:
            with self.subTest(tool=tool, arguments=arguments), self.assertRaises(ToolError):
                self.call(tool, **arguments)
        for tool in BUDGET_TOOLS:
            with self.subTest(tool=tool), self.assertRaises(ToolError):
                anyio.run(self.server.call_tool, tool, {"ad_id": 42, "amount": 5})
        self.assertEqual(self.requests, [])

    def test_inaccessible_or_invalid_account_prevents_writes(self):
        for accounts in ([], [{"account_id": "other", "currency": "TON"}],
                         [{"account_id": "default-related", "currency": "UNKNOWN"}]):
            with self.subTest(accounts=accounts):
                self.requests.clear()
                self.route = lambda method, params: {"ok": True, "result": accounts}
                with self.assertRaises(ToolError):
                    self.call()
                self.assertEqual(self.writes(), [])

    def test_api_rejection_is_failed_and_keeps_only_the_safe_code(self):
        for tool, extra in (
            ("increase_ad_budget", {}), ("decrease_ad_budget", {}),
            ("edit_ad", {"changes": {"is_paused": False}}),
            ("submit_ad_for_review", {}), ("delete_ad", {}),
        ):
            with self.subTest(tool=tool):
                self.requests.clear()
                self.route = lambda method, params: ({
                    "ok": False, "error": "AD_STATUS_INVALID", "description": "private details",
                } if method in WRITE_METHODS else self.default_route(method, params))
                result = self.call(tool, **extra)
                self.assertEqual(result["outcome"], "failed")
                self.assertEqual(result["error"]["code"], "AD_STATUS_INVALID")
                self.assertNotIn("private details", str(result))
                self.assertEqual(len(self.writes()), 1)

    def test_uncertain_outcomes_do_not_claim_failure_or_leak_details(self):
        for tool, extra in (
            ("increase_ad_budget", {}), ("decrease_ad_budget", {}),
            ("edit_ad", {"changes": {"is_paused": False}}),
            ("submit_ad_for_review", {}),
        ):
            for failure in ("transport", "server", "in_progress", "malformed", "wrong_id"):
                with self.subTest(tool=tool, failure=failure):
                    self.requests.clear()

                    def route(method, params):
                        if method not in WRITE_METHODS:
                            return self.default_route(method, params)
                        if failure == "transport":
                            raise TransportError("offline-test-token private details")
                        if failure == "server":
                            return 500, {"ok": False, "error": "SERVER_ERROR"}
                        if failure == "in_progress":
                            return {"ok": False, "error": "IDEMPOTENT_REQUEST_IN_PROGRESS"}
                        return {"ok": True, "result": {} if failure == "malformed" else {"ad_id": 99}}

                    self.route = route
                    with patch("telead.client.Client._sleep_backoff"):
                        result = self.call(tool, **extra)
                    self.assertEqual(result["outcome"], "unknown")
                    self.assertNotIn("ad", result)
                    self.assertNotIn("offline-test-token", str(result))
                    self.assertNotIn("private details", str(result))
                    if tool in BUDGET_TOOLS:
                        self.assertEqual(result["idempotency_key"], "stable")
                        self.assertTrue(all(
                            item[2]["headers"]["Idempotency-Key"] == "stable"
                            for item in self.writes()
                        ))
                    if tool == "submit_ad_for_review" and failure in ("transport", "server"):
                        self.assertEqual(len(self.writes()), 1)

    def test_idempotent_top_up_replay_preserves_parameters_and_result(self):
        saved = {}

        def route(method, params):
            if method != "increaseAdBudget":
                return self.default_route(method, params)
            key = self.writes()[-1][2]["headers"]["Idempotency-Key"]
            if key not in saved:
                saved[key] = (deepcopy(params), self.default_route(method, params))
            self.assertEqual(params, saved[key][0])
            return saved[key][1]

        self.route = route
        first = self.call()
        second = self.call()
        self.assertEqual(first, second)
        self.assertEqual(len(saved), 1)

    def test_write_tools_are_marked_as_mutating(self):
        tools = {tool.name: tool for tool in anyio.run(self.server.list_tools)}
        for name in BUDGET_TOOLS:
            self.assertEqual(set(tools[name].input_schema["required"]), {
                "ad_id", "amount", "idempotency_key",
            })
        for name in (*BUDGET_TOOLS, "edit_ad", "submit_ad_for_review", "delete_ad"):
            annotations = tools[name].annotations
            self.assertFalse(annotations.read_only_hint)
            self.assertTrue(annotations.destructive_hint)
            self.assertFalse(annotations.idempotent_hint)

    def test_text_edit_is_verified_against_the_returned_ad(self):
        result = self.call("edit_ad", changes={"text": "Updated text"})
        self.assertEqual(result["outcome"], "succeeded")
        self.assertEqual(result["ad"]["text"], "Updated text")
        self.assertEqual(self.writes()[0][2]["json"], {
            "account_id": "default-related", "ad_id": 42,
            "text": "Updated text", "return_target": False,
        })

        for old_text in ("Original text", None):
            with self.subTest(old_text=old_text):
                self.requests.clear()
                def route(method, params):
                    if method == "editAd":
                        return {"ok": True, "result": {"ad_id": 42, "text": old_text}}
                    return self.default_route(method, params)

                self.route = route
                result = self.call("edit_ad", changes={"text": "Updated text"})
                self.assertEqual(result["outcome"], "unknown")
                self.assertEqual(result["ad"]["text"], old_text)
                self.assertIn("text does not match", result["error"]["message"])
                self.assertEqual(len(self.writes()), 1)

    def test_delete_requires_api_confirmation_and_reports_uncertain_transport_once(self):
        result = self.call("delete_ad")
        self.assertEqual(result, {
            "account_id": "default-related", "ad_id": 42, "currency": "TON",
            "outcome": "succeeded", "deleted": True,
        })
        self.assertEqual(self.writes()[0][2]["json"], {
            "account_id": "default-related", "ad_id": 42,
        })
        self.assertNotIn("Idempotency-Key", self.writes()[0][2]["headers"])

        for failure in ("transport", "server", "false", "missing"):
            with self.subTest(failure=failure):
                self.requests.clear()
                def route(method, params):
                    if method != "deleteAd":
                        return self.default_route(method, params)
                    if failure == "transport":
                        raise TransportError("offline-test-token private details")
                    if failure == "server":
                        return 500, {"ok": False, "error": "SERVER_ERROR"}
                    return {"ok": True, "result": False if failure == "false" else None}

                self.route = route
                with patch("telead.client.Client._sleep_backoff"):
                    result = self.call("delete_ad")
                self.assertEqual(result["outcome"], "unknown")
                self.assertIsNone(result["deleted"])
                self.assertNotIn("offline-test-token", str(result))
                self.assertEqual(len(self.writes()), 1)


if __name__ == "__main__":
    unittest.main()
