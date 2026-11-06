"""Settings source precedence with synthetic credentials and temporary files."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ads_telegram_mcp.config import Settings


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.env_file = Path(directory.name) / ".env"
        self.env_file.write_text(
            'TELEGRAM_ADS_TOKEN=" file-token "\n'
            'TELEGRAM_ADS_ACCOUNT_ID=" кабинет "\n'
            'UNRELATED_SETTING=ignored\n',
            encoding="utf-8",
        )

    def test_dotenv_loading_and_secret_representation(self) -> None:
        settings = Settings(_env_file=self.env_file)
        self.assertEqual(settings.token, "file-token")
        self.assertEqual(settings.account_id, "кабинет")
        self.assertNotIn("file-token", repr(settings))
        self.assertNotIn("token", settings.model_dump())

    def test_explicit_arguments_then_environment_then_dotenv(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_ADS_TOKEN": " env-token "}):
            settings = Settings(_env_file=self.env_file)
            self.assertEqual(settings.token, "env-token")
            self.assertEqual(settings.account_id, "кабинет")
            explicit = Settings(token="explicit-token", _env_file=self.env_file)
            self.assertEqual(explicit.token, "explicit-token")

    def test_empty_environment_overrides_dotenv(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_ADS_TOKEN": "", "TELEGRAM_ADS_ACCOUNT_ID": "  "}):
            settings = Settings(_env_file=self.env_file)
            self.assertEqual(settings.token, "")
            self.assertIsNone(settings.account_id)

    def test_missing_file_uses_defaults(self) -> None:
        settings = Settings(_env_file=self.env_file.with_name("missing.env"))
        self.assertEqual(settings.token, "")
        self.assertIsNone(settings.account_id)

    def test_default_env_file_is_anchored_to_project(self) -> None:
        project = Path(__file__).resolve().parents[1]
        self.assertEqual(Settings.model_config["env_file"], project / ".env")


if __name__ == "__main__":
    unittest.main()
