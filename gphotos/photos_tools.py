"""
Google Photos Library API tools.

Mirrors the established pattern used by gmail/gmail_tools.py,
gdrive/drive_tools.py, etc.: each public function is wrapped by
@require_google_service(...) and exposed as an MCP tool via the
FastMCP server registered in core/.

Reference: https://developers.google.com/photos/library/reference/rest
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime
from typing import Any, Optional

import requests
from googleapiclient.errors import HttpError

from core.server import server
from core.service_helpers import require_google_service

logger = logging.getLogger(__name__)

PHOTOS_SERVICE_NAME = "photoslibrary"
PHOTOS_API_VERSION = "v1"

PHOTOS_READONLY_SCOPE = "https://www.googleapis.com/auth/photoslibrary.readonly"
PHOTOS_SHARING_SCOPE = "https://www.googleapis.com/auth/photoslibrary.sharing"

PHOTOS_DISCOVERY_URL = (
    "https://photoslibrary.googleapis.com/$discovery/rest?version=v1"
)


@server.tool()
@require_google_service(
    service_name=PHOTOS_SERVICE_NAME,
    version=PHOTOS_API_VERSION,
    scopes=[PHOTOS_READONLY_SCOPE],
    discovery_service_url=PHOTOS_DISCOVERY_URL,
)
async def list_photo_albums(
    service,
    page_size: int = 50,
    page_token: Optional[str] = None,
    exclude_non_app_created: bool = False,
) -> dict[str, Any]:
    """List the user's Google Photos albums."""
    try:
        response = (
            service.albums()
            .list(
                pageSize=min(page_size, 50),
                pageToken=page_token,
                excludeNonAppCreatedData=exclude_non_app_created,
            )
            .execute()
        )
        return {
            "albums": response.get("albums", []),
            "nextPageToken": response.get("nextPageToken"),
        }
    except HttpError as e:
        logger.error("list_photo_albums failed: %s", e)
        raise


@server.tool()
@require_google_service(
    service_name=PHOTOS_SERVICE_NAME,
    version=PHOTOS_API_VERSION,
    scopes=[PHOTOS_READONLY_SCOPE],
    discovery_service_url=PHOTOS_DISCOVERY_URL,
)
async def search_photos(
    service,
    album_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    content_categories: Optional[list[str]] = None,
    media_types: Optional[list[str]] = None,
    page_size: int = 25,
    page_token: Optional[str] = None,
) -> dict[str, Any]:
    """Search the user's photo library."""
    body: dict[str, Any] = {"pageSize": min(page_size, 100)}
    if page_token:
        body["pageToken"] = page_token

    if album_id:
        body["albumId"] = album_id
    else:
        filters: dict[str, Any] = {}

        if start_date or end_date:
            def _date_obj(s: str) -> dict[str, int]:
                d = datetime.strptime(s, "%Y-%m-%d")
                return {"year": d.year, "month": d.month, "day": d.day}

            date_range: dict[str, Any] = {}
            if start_date:
                date_range["startDate"] = _date_obj(start_date)
            if end_date:
                date_range["endDate"] = _date_obj(end_date)
            filters["dateFilter"] = {"ranges": [date_range]}

        if content_categories:
            filters["contentFilter"] = {
                "includedContentCategories": content_categories
            }

        if media_types:
            filters["mediaTypeFilter"] = {"mediaTypes": media_types}

        if filters:
            body["filters"] = filters

    try:
        response = service.mediaItems().search(body=body).execute()
        return {
            "mediaItems": response.get("mediaItems", []),
            "nextPageToken": response.get("nextPageToken"),
        }
    except HttpError as e:
        logger.error("search_photos failed: %s", e)
        raise


@server.tool()
@require_google_service(
    service_name=PHOTOS_SERVICE_NAME,
    version=PHOTOS_API_VERSION,
    scopes=[PHOTOS_READONLY_SCOPE],
    discovery_service_url=PHOTOS_DISCOVERY_URL,
)
async def get_photo_metadata(service, photo_id: str) -> dict[str, Any]:
    """Fetch full metadata for a single media item."""
    try:
        return service.mediaItems().get(mediaItemId=photo_id).execute()
    except HttpError as e:
        logger.error("get_photo_metadata failed for %s: %s", photo_id, e)
        raise


@server.tool()
@require_google_service(
    service_name=PHOTOS_SERVICE_NAME,
    version=PHOTOS_API_VERSION,
    scopes=[PHOTOS_READONLY_SCOPE],
    discovery_service_url=PHOTOS_DISCOVERY_URL,
)
async def get_photo_url(
    service,
    photo_id: str,
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
    download: bool = False,
) -> dict[str, Any]:
    """Return a fetchable URL for a photo or video."""
    try:
        item = service.mediaItems().get(mediaItemId=photo_id).execute()
    except HttpError as e:
        logger.error("get_photo_url metadata fetch failed: %s", e)
        raise

    base_url = item.get("baseUrl", "")
    mime_type = item.get("mimeType", "")
    is_video = mime_type.startswith("video/")

    if is_video:
        url = f"{base_url}=dv"
    elif download:
        url = f"{base_url}=d"
    elif max_width and max_height:
        url = f"{base_url}=w{max_width}-h{max_height}"
    elif max_width:
        url = f"{base_url}=w{max_width}"
    elif max_height:
        url = f"{base_url}=h{max_height}"
    else:
        url = base_url

    return {
        "url": url,
        "baseUrl": base_url,
        "mimeType": mime_type,
        "filename": item.get("filename"),
        "mediaMetadata": item.get("mediaMetadata", {}),
    }


@server.tool()
@require_google_service(
    service_name=PHOTOS_SERVICE_NAME,
    version=PHOTOS_API_VERSION,
    scopes=[PHOTOS_READONLY_SCOPE],
    discovery_service_url=PHOTOS_DISCOVERY_URL,
)
async def download_photo(
    service,
    photo_id: str,
    save_path: str,
    full_resolution: bool = True,
) -> dict[str, Any]:
    """Download a photo or video to a local path on the server."""
    try:
        item = service.mediaItems().get(mediaItemId=photo_id).execute()
    except HttpError as e:
        logger.error("download_photo metadata fetch failed: %s", e)
        raise

    base_url = item.get("baseUrl", "")
    mime_type = item.get("mimeType", "")
    original_filename = item.get("filename", f"{photo_id}.bin")
    is_video = mime_type.startswith("video/")

    if full_resolution:
        download_url = f"{base_url}={'dv' if is_video else 'd'}"
    else:
        download_url = base_url

    if not os.path.isabs(save_path):
        attachment_dir = os.environ.get(
            "WORKSPACE_ATTACHMENT_DIR",
            os.path.expanduser("~/.workspace-mcp/attachments"),
        )
        os.makedirs(attachment_dir, exist_ok=True)
        save_path = os.path.join(attachment_dir, save_path or original_filename)

    resp = requests.get(download_url, stream=True, timeout=60)
    resp.raise_for_status()

    bytes_written = 0
    with open(save_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if chunk:
                fh.write(chunk)
                bytes_written += len(chunk)

    return {
        "saved_path": save_path,
        "bytes_written": bytes_written,
        "mimeType": mime_type,
        "filename": original_filename,
    }
