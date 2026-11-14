"""Offline file validation and multipart upload checks."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import anyio
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image
from telead.errors import TransportError

from ads_telegram_mcp.config import Settings
from ads_telegram_mcp.server import create_server


class MediaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.server = create_server(Settings(
            token="offline-test-token", account_id="default-related", _env_file=None,
        ))
        self.requests = []
        self.upload_error = None
        self.empty_upload_response = False

        def request(session, verb, url, **kwargs):
            method = url.rsplit("/", 1)[-1]
            self.requests.append((method, kwargs))
            if method == "getAccountsById":
                result = [{"account_id": kwargs["json"]["account_ids"][0], "currency": "TON"}]
            elif method == "getCurrentAccount":
                result = {"account_id": "owner", "currency": "EUR"}
            elif method.startswith("upload"):
                if self.upload_error:
                    raise self.upload_error
                result = {"video_id": "video", "video_url": "https://example.org/video"} if method == "uploadAdVideo" else {
                    "photo_id": "photo", "photo_url": "https://example.org/photo",
                }
                if self.empty_upload_response:
                    result = {}
            else:
                raise AssertionError("Unexpected API method")
            return Mock(status_code=200, headers={}, json=lambda: {"ok": True, "result": result})

        http = patch("requests.Session.request", autospec=True, side_effect=request)
        http.start()
        self.addCleanup(http.stop)

    def image(self, size=(640, 360), format="PNG", name="image.png"):
        path = self.directory / name
        Image.new("RGB", size, (12, 34, 56)).save(path, format=format)
        return path

    def video(self):
        path = self.directory / "video.mp4"
        path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 32)
        return path

    def call(self, path, kind="ad_photo", **arguments):
        result = anyio.run(self.server.call_tool, "upload_media", {
            "file_path": str(path), "kind": kind, **arguments,
        })
        return result.structured_content

    def test_ad_photo_uploads_exact_validated_bytes_to_explicit_account(self):
        path = self.image()
        result = self.call(path, account_id="explicit")
        self.assertEqual([method for method, _ in self.requests], [
            "getCurrentAccount", "getAccountsById", "uploadAdPhoto",
        ])
        upload = self.requests[2][1]
        self.assertEqual(upload["data"], {"account_id": "explicit"})
        self.assertEqual(upload["files"]["file"], (path.name, path.read_bytes(), "image/png"))
        self.assertNotIn("Idempotency-Key", upload["headers"])
        self.assertEqual(result["account_id"], "explicit")
        self.assertEqual(result["photo_id"], "photo")
        self.assertEqual(result["metadata"]["width"], 640)
        self.assertEqual(result["metadata"]["height"], 360)
        self.assertEqual(result["kind"], "ad_photo")

    def test_website_photo_accepts_square_jpeg_and_token_owner(self):
        self.server = create_server(Settings(token="offline-test-token", account_id=None, _env_file=None))
        path = self.image((150, 150), format="JPEG", name="logo.jpg")
        result = self.call(path, "website_photo")
        self.assertEqual([method for method, _ in self.requests], ["getCurrentAccount", "uploadWebsitePhoto"])
        self.assertEqual(result["metadata"]["format"], "JPEG")
        self.assertEqual(result["account_id"], "owner")

    def test_invalid_paths_formats_dimensions_and_sizes_never_reach_api(self):
        bad_format = self.image(format="GIF", name="misleading.png")
        small_ad = self.image((320, 180), name="small.png")
        wrong_ratio = self.image((640, 640), name="square.png")
        small_site = self.image((149, 150), name="small-site.png")
        empty = self.directory / "empty.png"
        empty.write_bytes(b"")
        oversize = self.directory / "large.png"
        with oversize.open("wb") as file:
            file.truncate(5 * 1024 * 1024 + 1)
        for path, kind in (
            ("relative.png", "ad_photo"), (self.directory / "missing.png", "ad_photo"),
            (self.directory, "ad_photo"), (bad_format, "ad_photo"),
            (small_ad, "ad_photo"), (wrong_ratio, "ad_photo"),
            (small_site, "website_photo"), (empty, "ad_photo"),
            (oversize, "ad_photo"), (oversize, "website_photo"),
        ):
            with self.subTest(path=path, kind=kind), self.assertRaises(ToolError):
                self.call(path, kind)
        self.assertEqual(self.requests, [])

    def metadata(self, **overrides):
        stream = {"width": 1280, "height": 720, "sample_aspect_ratio": "1:1", **overrides}
        return {"streams": [stream], "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "10"}}

    def test_video_probe_and_upload_use_the_same_bytes(self):
        path = self.video()
        content = path.read_bytes()

        def probe(args, **kwargs):
            self.assertEqual(Path(args[-1]).read_bytes(), content)
            self.assertEqual(args[args.index("-protocol_whitelist") + 1], "file")
            self.assertTrue(kwargs["check"])
            self.assertEqual(kwargs["timeout"], 20)
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(self.metadata()), stderr="")

        with patch("ads_telegram_mcp.operations.media.shutil.which", return_value="/test/ffprobe"), \
             patch("ads_telegram_mcp.operations.media.subprocess.run", side_effect=probe):
            result = self.call(path, "ad_video")
        self.assertEqual(result["video_id"], "video")
        self.assertEqual(result["metadata"]["duration"], 10)
        self.assertEqual(self.requests[-1][0], "uploadAdVideo")
        self.assertEqual(self.requests[-1][1]["files"]["file"][1], content)

    def test_missing_ffprobe_is_reported_before_any_api_call(self):
        with patch("ads_telegram_mcp.operations.media.shutil.which", return_value=None):
            with self.assertRaises(ToolError) as raised:
                self.call(self.video(), "ad_video")
        self.assertIn("ffprobe", str(raised.exception))
        self.assertEqual(self.requests, [])

    def test_invalid_video_metadata_does_not_upload(self):
        path = self.video()
        wrong_duration = self.metadata()
        wrong_duration["format"]["duration"] = "61"
        short_duration = self.metadata()
        short_duration["format"]["duration"] = "2.9"
        for metadata in (
            self.metadata(width=320, height=180), self.metadata(width=640, height=640),
            self.metadata(side_data_list=[{"rotation": 90}]), wrong_duration, short_duration,
            {"streams": [], "format": {}},
        ):
            with self.subTest(metadata=metadata), \
                 patch("ads_telegram_mcp.operations.media.shutil.which", return_value="/test/ffprobe"), \
                 patch("ads_telegram_mcp.operations.media.subprocess.run", return_value=Mock(stdout=json.dumps(metadata))), \
                 self.assertRaises(ToolError):
                self.call(path, "ad_video")
        self.assertEqual(self.requests, [])

    def test_probe_timeout_is_sanitized(self):
        with patch("ads_telegram_mcp.operations.media.shutil.which", return_value="/test/ffprobe"), \
             patch("ads_telegram_mcp.operations.media.subprocess.run", side_effect=subprocess.TimeoutExpired("probe", 20, stderr="private details")), \
             self.assertRaises(ToolError) as raised:
            self.call(self.video(), "ad_video")
        self.assertNotIn("private details", str(raised.exception))
        self.assertEqual(self.requests, [])

    def test_unknown_upload_outcome_is_not_retried_automatically(self):
        self.upload_error = TransportError("offline-test-token details")
        with self.assertRaises(ToolError) as raised:
            self.call(self.image())
        self.assertNotIn("offline-test-token", str(raised.exception))
        self.assertEqual([method for method, _ in self.requests], [
            "getCurrentAccount", "getAccountsById", "uploadAdPhoto",
        ])

    def test_missing_media_id_does_not_report_success(self):
        self.empty_upload_response = True
        with self.assertRaises(ToolError) as raised:
            self.call(self.image())
        self.assertIn("outcome is unknown", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
