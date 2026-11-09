"""Profile selection through MCP with no real API requests."""

import unittest
from unittest.mock import Mock, patch

import anyio
from mcp.server.mcpserver.exceptions import ToolError

from ads_telegram_mcp.config import Settings
from ads_telegram_mcp.server import create_server


class ProfileRoutingTests(unittest.TestCase):
    def setUp(self):
        self.server = self.make_server()
        self.requests = []
        self.error_code = None

        def request(session, verb, url, **kwargs):
            method = url.rsplit("/", 1)[-1]
            auth = kwargs["headers"]["Authorization"]
            params = kwargs["json"]
            self.requests.append((method, auth, params))
            if method == "getAccountsById":
                result = [{"account_id": params["account_ids"][0], "currency": "TON"}]
            elif self.error_code is not None:
                body = {"ok": False, "error": self.error_code}
                return Mock(status_code=400, headers={}, json=lambda: body)
            elif method == "getCurrentAccount":
                result = {"account_id": "token-owner", "currency": "EUR"}
            elif method == "getAdsList":
                result = {"ads": [], "total_count": 0}
            elif method == "increaseAdBudget":
                result = {"ad_id": params["ad_id"], "remaining_budget": 10}
            else:
                raise AssertionError("Unexpected API method")
            return Mock(status_code=200, headers={}, json=lambda: {"ok": True, "result": result})

        http = patch("requests.Session.request", autospec=True, side_effect=request)
        http.start()
        self.addCleanup(http.stop)

    @staticmethod
    def make_server(*, single=False, named=True):
        tokens = ["agency-secret"] if single else ["agency-secret", "personal-secret", "test-secret"]
        names = ["agency"] if single else ["agency", "Личный", "test"]
        return create_server(Settings(
            token="legacy-secret", account_id="legacy-related", tokens=tokens,
            token_names=names if named else None, _env_file=None,
        ))

    def call(self, tool, **arguments):
        return anyio.run(self.server.call_tool, tool, arguments).structured_content

    def test_discovery_lists_only_profile_names_and_effective_default(self):
        self.assertEqual(self.call("list_profiles"), {
            "profiles": ["agency", "Личный", "test"], "default_profile": None,
        })
        self.assertEqual(self.requests, [])

    def test_profile_and_related_account_scope_are_selected_independently(self):
        self.call("list_ads", profile="agency")
        self.call("get_current_account", profile="agency")
        self.call("list_ads", profile="Личный")
        self.call("list_ads", profile="Личный", account_id="explicit-related")
        self.call("list_ads", profile="test")
        self.assertEqual(self.requests, [
            ("getAdsList", "Bearer agency-secret", {
                "limit": 20, "return_target": False,
            }),
            ("getCurrentAccount", "Bearer agency-secret", {}),
            ("getAdsList", "Bearer personal-secret", {"limit": 20, "return_target": False}),
            ("getAdsList", "Bearer personal-secret", {
                "account_id": "explicit-related", "limit": 20, "return_target": False,
            }),
            ("getAdsList", "Bearer test-secret", {"limit": 20, "return_target": False}),
        ])

    def test_unnamed_third_token_is_selected_by_position(self):
        self.server = self.make_server(named=False)
        self.assertEqual(self.call("list_profiles")["profiles"], ["1", "2", "3"])
        self.call("get_current_account", profile="3")
        self.assertEqual(self.requests, [("getCurrentAccount", "Bearer test-secret", {})])

    def test_single_profile_is_selected_for_account_lookup_and_write(self):
        self.server = self.make_server(single=True)
        self.assertEqual(self.call("list_profiles")["default_profile"], "agency")
        result = self.call("increase_ad_budget", ad_id=42, amount=5, idempotency_key="top-up")
        self.assertEqual(result["outcome"], "succeeded")
        self.assertEqual(result["account_id"], "legacy-related")
        self.assertEqual(self.requests, [
            ("getAccountsById", "Bearer agency-secret", {"account_ids": ["legacy-related"]}),
            ("increaseAdBudget", "Bearer agency-secret", {
                "account_id": "legacy-related", "ad_id": 42, "amount": 5,
                "return_target": False,
            }),
        ])

    def test_ambiguous_or_unknown_profile_fails_before_http(self):
        args = {"ad_id": 42, "amount": 5, "idempotency_key": "top-up"}
        with self.assertRaisesRegex(ToolError, "Unknown Telegram Ads profile"):
            self.call("increase_ad_budget", profile="unknown", **args)
        self.assertIsNone(self.call("list_profiles")["default_profile"])
        with self.assertRaisesRegex(ToolError, "Specify a profile"):
            self.call("increase_ad_budget", **args)
        self.assertEqual(self.requests, [])

    def test_creation_preview_uses_profile_scope_without_api_calls(self):
        ads = [{
            "title": "Preview", "text": "Example", "promote_url": "https://t.me/example",
            "cpm": 0.3, "placement": "channel_post",
            "target": {"type": "channels", "channel_ids": ["@example"]},
            "idempotency_key": "preview",
        }]
        preview = self.call("create_ads", ads=ads, dry_run=True, profile="Личный")
        self.assertIsNone(preview["account_id"])
        self.server = self.make_server(single=True)
        self.assertEqual(self.call("create_ads", ads=ads, dry_run=True)["account_id"], "legacy-related")
        with self.assertRaisesRegex(ToolError, "Unknown Telegram Ads profile"):
            self.call("create_ads", ads=ads, dry_run=True, profile="unknown", account_id="explicit")
        self.assertEqual(self.requests, [])

    def test_api_errors_hide_tokens_in_read_errors_and_write_results(self):
        self.error_code = "BAD_agency-secret_personal-secret_legacy-secret"
        with self.assertRaisesRegex(ToolError, r"BAD_\[redacted\]_\[redacted\]_\[redacted\]"):
            self.call("list_ads", profile="Личный")
        result = self.call(
            "increase_ad_budget", profile="agency", account_id="explicit-related",
            ad_id=42, amount=5, idempotency_key="top-up",
        )
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["error"]["code"], "BAD_[redacted]_[redacted]_[redacted]")
        self.assertNotIn("secret", result["error"]["message"])
