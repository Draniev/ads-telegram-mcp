"""Validate local media bytes before uploading them to a resolved account."""

from dataclasses import dataclass
from fractions import Fraction
from io import BytesIO
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Literal
import warnings

from PIL import Image, UnidentifiedImageError
from telead import Client
from telead.models import Account, AdPhoto, AdVideo, WebsitePhoto

from ..errors import OperationError
from .accounts import resolve_account

MediaKind = Literal["ad_photo", "ad_video", "website_photo"]


@dataclass(frozen=True)
class MediaInfo:
    format: str
    size_bytes: int
    width: int
    height: int
    duration: float | None = None


@dataclass(frozen=True)
class MediaUpload:
    account: Account
    kind: MediaKind
    media: AdPhoto | AdVideo | WebsitePhoto
    info: MediaInfo


def _image_info(content: bytes, kind: MediaKind) -> MediaInfo:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content), formats=["JPEG", "PNG"]) as image:
                image.load()
                width, height = image.size
                format_name = image.format
    except (OSError, ValueError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise OperationError("The file is not a readable JPEG or PNG image.") from None
    if kind == "website_photo":
        if width < 150 or height < 150:
            raise OperationError("Website photos must be at least 150 by 150 pixels.")
    elif width < 640 or width * 9 != height * 16:
        raise OperationError("Ad photos must be at least 640 pixels wide with a 16:9 ratio.")
    return MediaInfo(format_name, len(content), width, height)


def _video_info(content: bytes) -> MediaInfo:
    if content[4:8] != b"ftyp" or content[8:12] == b"qt  ":
        raise OperationError("Ad videos must be MP4 files.")
    probe = shutil.which("ffprobe")
    if probe is None:
        raise OperationError("Video validation requires ffprobe from FFmpeg on the server PATH.")
    try:
        with tempfile.TemporaryDirectory(prefix="telegram-ad-video-") as directory:
            path = Path(directory) / "video.mp4"
            path.write_bytes(content)
            result = subprocess.run(
                [probe, "-v", "error", "-protocol_whitelist", "file",
                 "-select_streams", "v:0", "-show_entries",
                 "stream=width,height,duration,sample_aspect_ratio:stream_tags=rotate:"
                 "stream_side_data=rotation:format=duration,format_name",
                 "-of", "json", str(path)],
                check=True, capture_output=True, text=True, timeout=20,
            )
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        container = data.get("format", {})
        if "mp4" not in container.get("format_name", "").split(","):
            raise ValueError("Not an MP4 container")
        width, height = int(stream["width"]), int(stream["height"])
        duration = float(container.get("duration") or stream["duration"])
        sar_text = stream.get("sample_aspect_ratio", "1:1")
        sar = Fraction(sar_text.replace(":", "/")) if sar_text not in {"N/A", "0:1"} else Fraction(1)
        ratio = Fraction(width, height) * sar
        rotation = stream.get("tags", {}).get("rotate", 0)
        for side_data in stream.get("side_data_list", []):
            if "rotation" in side_data:
                rotation = side_data["rotation"]
        angle = float(rotation) % 360
        if angle not in {0, 90, 180, 270}:
            raise ValueError("Unsupported video rotation")
        if angle in {90, 270}:
            width, height = height, width
            ratio = 1 / ratio
    except (OSError, subprocess.SubprocessError, ValueError, KeyError,
            IndexError, TypeError, ZeroDivisionError):
        raise OperationError("ffprobe could not read valid MP4 video metadata.") from None
    if width < 640 or ratio != Fraction(16, 9):
        raise OperationError("Ad videos must be at least 640 pixels wide with a 16:9 ratio.")
    if not math.isfinite(duration) or not 3 <= duration <= 60:
        raise OperationError("Ad videos must be between 3 and 60 seconds long.")
    return MediaInfo("MP4", len(content), width, height, duration)


def upload_media(
    client: Client, *, file_path: str, kind: MediaKind,
) -> MediaUpload:
    """Read and validate a file, then upload exactly those bytes to one account."""
    path = Path(file_path)
    if not path.is_absolute():
        raise OperationError("file_path must be an absolute local file path.")
    max_bytes = {"ad_photo": 5, "ad_video": 20, "website_photo": 1}[kind] * 1024 * 1024
    try:
        if not path.is_file():
            raise OperationError("file_path must point to a readable regular file.")
        if not 0 < path.stat().st_size <= max_bytes:
            raise OperationError(f"The {kind} file must contain 1 to {max_bytes} bytes.")
        with path.open("rb") as source:
            content = source.read(max_bytes + 1)
    except OSError:
        raise OperationError("Cannot read the local media file.") from None
    if not 0 < len(content) <= max_bytes:
        raise OperationError(f"The {kind} file must contain 1 to {max_bytes} bytes.")
    info = _video_info(content) if kind == "ad_video" else _image_info(content, kind)
    account = resolve_account(client)
    if kind == "ad_photo":
        media = client.upload_ad_photo(content, filename=path.name, account_id=account.account_id)
    elif kind == "ad_video":
        media = client.upload_ad_video(content, filename=path.name, account_id=account.account_id)
    else:
        media = client.upload_website_photo(content, filename=path.name, account_id=account.account_id)
    reference = media.raw.get("video_id" if kind == "ad_video" else "photo_id")
    if not isinstance(reference, str) or not reference:
        raise OperationError("The upload response contained no media ID; its outcome is unknown.")
    return MediaUpload(account, kind, media, info)
