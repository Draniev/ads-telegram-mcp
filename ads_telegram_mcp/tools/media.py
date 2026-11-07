"""Local media uploads for use in Telegram Ads creation requests."""

from dataclasses import asdict
from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field

from ..execution import TeleAdRunner
from ..operations.media import MediaKind, upload_media as upload_media_operation
from .common import UPLOAD_MEDIA, AccountID


def register(server: MCPServer, runner: TeleAdRunner) -> None:
    @server.tool(annotations=UPLOAD_MEDIA)
    async def upload_media(
        file_path: Annotated[str, Field(min_length=1)],
        kind: MediaKind,
        account_id: AccountID | None = None,
    ) -> dict[str, Any]:
        """Upload a local photo, MP4 video, or website photo to Telegram Ads.

        file_path must be an absolute path on the server machine. The file's
        bytes are transmitted to Telegram. Images are checked with Pillow;
        video metadata validation requires ffprobe from FFmpeg on PATH.

        Returns account_id, kind, photo_id/photo_url or video_id/video_url,
        and validated media metadata. Reuse the ID only in the same account.
        Upload retries may create a new media ID; no idempotency key is available.

        Omitted account_id uses the configured default or the token owner.
        """
        result = await runner.run(lambda client: upload_media_operation(
            client, file_path=file_path, kind=kind, account_id=account_id,
        ))
        return {
            **result.media.raw,
            "account_id": result.account.account_id, "kind": result.kind,
            "metadata": asdict(result.info),
        }
