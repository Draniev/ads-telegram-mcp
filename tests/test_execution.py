"""Typed composed operations, worker execution and client lifetime without HTTP."""

import threading
import unittest
from unittest.mock import create_autospec, patch

import anyio
from mcp.server.mcpserver.exceptions import ToolError
from telead import Client
from telead.errors import TransportError
from telead.models import Account, Ad, AdList

from ads_telegram_mcp.config import Settings
from ads_telegram_mcp.execution import TeleAdRunner


class ExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        guard = patch("requests.Session.request", side_effect=AssertionError("Network forbidden"))
        guard.start()
        self.addCleanup(guard.stop)
        self.client = create_autospec(Client, instance=True)
        self.client.__enter__.return_value = self.client
        factory = patch("ads_telegram_mcp.execution.Client", return_value=self.client)
        self.factory = factory.start()
        self.addCleanup(factory.stop)
        self.runner = TeleAdRunner(Settings(token="offline-test-token", _env_file=None))

    def test_composed_operation_preserves_models_and_uses_one_client_in_worker(self) -> None:
        self.client.get_current_account.return_value = Account.from_dict({"account_id": "owner"})
        page = AdList.from_dict({"ads": [
            {"ad_id": 1, "status": "active", "future_field": "preserved"},
            {"ad_id": 2, "status": "stopped"},
        ]})
        self.client.get_ads_list.return_value = page
        caller_thread = threading.get_ident()

        def select_active(client: Client) -> list[Ad]:
            self.assertNotEqual(threading.get_ident(), caller_thread)
            account = client.get_current_account()
            ads = client.get_ads_list(account_id=account.account_id)
            return [ad for ad in ads.ads if ad.status == "active"]

        result = anyio.run(self.runner.run, select_active)
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], page.ads[0])
        self.assertIsInstance(result[0], Ad)
        self.assertEqual(result[0].raw["future_field"], "preserved")
        self.client.get_ads_list.assert_called_once_with(account_id="owner")
        self.factory.assert_called_once()
        self.client.__enter__.assert_called_once()
        self.client.__exit__.assert_called_once_with(None, None, None)

    def test_failure_in_second_call_closes_client_and_redacts_transport_error(self) -> None:
        self.client.get_ads_list.side_effect = TransportError("offline-test-token details")

        def load(client: Client) -> AdList:
            client.get_current_account()
            return client.get_ads_list()

        with self.assertRaises(ToolError) as raised:
            anyio.run(self.runner.run, load)
        self.assertNotIn("offline-test-token", str(raised.exception))
        self.client.get_current_account.assert_called_once()
        self.client.__exit__.assert_called_once()
        self.assertIs(self.client.__exit__.call_args.args[0], TransportError)

    def test_explicit_tool_error_from_operation_is_preserved(self) -> None:
        error = ToolError("The selected ad is unavailable.")

        def reject(client: Client) -> None:
            raise error

        with self.assertRaises(ToolError) as raised:
            anyio.run(self.runner.run, reject)
        self.assertIs(raised.exception, error)
        self.client.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
