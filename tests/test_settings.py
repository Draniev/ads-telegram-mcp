"""Settings source precedence with synthetic credentials and temporary files."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

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

    def test_lists_load_from_dotenv_and_environment_overrides_tokens(self) -> None:
        self.env_file.write_text(
            'TELEGRAM_ADS_TOKENS=[" file-team-a ", "file-team-b", "file-team-c"]\n'
            'TELEGRAM_ADS_TOKEN_NAMES=["Личный", "Agency", "Тестовый"]\n',
            encoding="utf-8",
        )
        settings = Settings(_env_file=self.env_file)
        self.assertEqual(settings.configured_tokens, ("file-team-a", "file-team-b", "file-team-c"))
        with patch.dict(os.environ, {
            "TELEGRAM_ADS_TOKENS": '["env-team-a", "env-team-b", "env-team-c"]',
        }):
            settings = Settings(_env_file=self.env_file)
        self.assertEqual(settings.configured_tokens, ("env-team-a", "env-team-b", "env-team-c"))
        self.assertEqual(settings.profile_names, ("Личный", "Agency", "Тестовый"))
        for rendered in (repr(settings), settings.model_dump_json()):
            self.assertNotIn("env-team-", rendered)

    def test_empty_list_takes_precedence_over_legacy_token(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_ADS_TOKENS": "[]"}):
            settings = Settings(_env_file=self.env_file)
        self.assertEqual(settings.configured_tokens, ())
        self.assertEqual(settings.profile_names, ())

    def test_invalid_lists_do_not_include_tokens_in_error_text(self) -> None:
        cases = [
            (["profile-secret"], ["A", "B"], "one name per token"),
            (["profile-secret", "other-secret"], ["A", " A "], "unique names"),
            (["profile-secret"], [" "], "at least 1 character"),
            (["profile-secret", " "], None, "at least 1 character"),
        ]
        for tokens, names, message in cases:
            with self.subTest(message=message), self.assertRaises(ValidationError) as raised:
                Settings(
                    token="legacy-secret", tokens=tokens, token_names=names,
                    _env_file=None,
                )
            self.assertIn(message, str(raised.exception))
            self.assertNotIn("profile-secret", str(raised.exception))
            self.assertNotIn("legacy-secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
