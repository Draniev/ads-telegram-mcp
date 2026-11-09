"""Offline checks only: HTTP is mocked; the stdio subprocess has no token."""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.mcpserver.exceptions import ToolError
from telead.errors import TransportError
from telead import Client

from ads_telegram_mcp.config import Settings
from ads_telegram_mcp.errors import ErrorMessages
from ads_telegram_mcp.execution import ClientConnection, TeleAdRunner
from ads_telegram_mcp.server import create_server


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        # A forgotten fixture must never turn a local test into a real API call.
        guard = patch("requests.Session.request", side_effect=AssertionError("Network forbidden"))
        self.http = guard.start()
        self.addCleanup(guard.stop)
        self.server = create_server(Settings(
            token="offline-test-token", account_id="default-related", _env_file=None,
        ))

    def test_paging_scope_and_raw_payload(self) -> None:
        payload = {"total_count": 2, "ads": [{"ad_id": 1, "currency": "XTR", "future_field": 3}],
                   "next_offset": "opaque:+/=="}
        self.http.side_effect = None
        self.http.return_value = Mock(status_code=200, headers={}, json=lambda: {"ok": True, "result": payload})
        result = anyio.run(self.server.call_tool, "list_ads", {"offset": "previous:==", "limit": 1})
        self.assertEqual(result.structured_content, payload)
        self.assertEqual(self.http.call_count, 1)
        request = self.http.call_args.kwargs["json"]
        self.assertEqual(request["account_id"], "default-related")
        self.assertEqual(request["offset"], "previous:==")
        self.assertFalse(request["return_target"])
        self.assertNotIn("raw", result.structured_content)

    def test_explicit_scope_and_token_owner(self) -> None:
        self.http.side_effect = None
        self.http.return_value = Mock(status_code=200, headers={}, json=lambda: {"ok": True, "result": []})
        anyio.run(self.server.call_tool, "get_ads_by_id", {"ad_ids": [7], "account_id": "explicit"})
        self.assertEqual(self.http.call_args.kwargs["json"]["account_id"], "explicit")
        self.http.return_value = Mock(status_code=200, headers={}, json=lambda: {"ok": True, "result": {"account_id": "owner"}})
        result = anyio.run(self.server.call_tool, "get_current_account", {})
        self.assertEqual(result.structured_content["account_id"], "owner")
        self.assertEqual(self.http.call_args.kwargs["json"], {})

    def test_invalid_arguments_do_not_reach_http(self) -> None:
        cases = [
            ("list_ads", {"limit": 101}),
            ("get_ads_by_id", {"ad_ids": []}),
            ("get_account_report", {"year": 2026, "month": 13}),
            ("get_account_stats", {"from_time": 10, "to_time": 9}),
            ("get_account_stats", {"from_time": 0, "to_time": 300001, "interval": 300}),
            ("get_account_stats", {"from_time": 0, "to_time": 10, "interval": 60}),
        ]
        for tool, args in cases:
            with self.subTest(tool=tool, args=args), self.assertRaises(ToolError):
                anyio.run(self.server.call_tool, tool, args)
        self.http.assert_not_called()

    def test_public_errors_do_not_contain_transport_secrets(self) -> None:
        connection = ClientConnection(token="private-token")
        runner = TeleAdRunner(ErrorMessages(("private-token",)))
        with patch("ads_telegram_mcp.execution.Client", side_effect=TransportError("private-token request contents")):
            with self.assertRaises(ToolError) as raised:
                anyio.run(runner.run, connection, Client.get_current_account)
        self.assertNotIn("private-token", str(raised.exception))
        self.assertNotIn("private-token", repr(connection))

    def test_stdio_discovery_and_missing_token(self) -> None:
        async def check() -> None:
            params = StdioServerParameters(
                command=sys.executable,
                args=["-B", "-c", (
                    "from ads_telegram_mcp.config import Settings; "
                    "from ads_telegram_mcp.server import create_server; "
                    "settings = Settings(token='', account_id=None, tokens=[], "
                    "token_names=None, _env_file=None); "
                    "create_server(settings).run(transport='stdio')"
                )],
                cwd=str(Path(__file__).resolve().parents[1]),
            )
            with anyio.fail_after(15):
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = (await session.list_tools()).tools
                        self.assertEqual(len(tools), 19)
                        self.assertIn("get_ads_stats", {tool.name for tool in tools})
                        self.assertTrue({
                            "get_targeting_options", "get_target_locations",
                            "get_target_channel", "get_target_bot",
                            "increase_ad_budget", "edit_ad", "submit_ad_for_review",
                            "list_profiles",
                        }.issubset({tool.name for tool in tools}))
                        for tool in tools:
                            if tool.name != "list_profiles":
                                self.assertIn("profile", tool.input_schema["properties"])
                                self.assertNotIn("profile", tool.input_schema.get("required", []))
                            self.assertEqual(
                                tool.annotations.read_only_hint,
                                tool.name not in {
                                    "create_ads", "upload_media", "increase_ad_budget",
                                    "edit_ad", "submit_ad_for_review",
                                },
                            )
                        result = await session.call_tool("get_current_account", {})
                        self.assertTrue(result.is_error)
                        self.assertIn("TELEGRAM_ADS_TOKENS", result.content[0].text)
                        preview = await session.call_tool("create_ads", {
                            "dry_run": True,
                            "ads": [{
                                "title": "Preview", "text": "Example",
                                "promote_url": "https://t.me/example", "cpm": 0.3,
                                "placement": "channel_post",
                                "target": {"type": "channels", "channel_ids": ["@example"]},
                                "idempotency_key": "offline-preview",
                            }],
                        })
                        self.assertFalse(preview.is_error)
                        self.assertEqual(preview.structured_content["validated_count"], 1)
                        self.assertTrue(preview.structured_content["ads"][0]["is_paused"])

        anyio.run(check)


if __name__ == "__main__":
    unittest.main()
