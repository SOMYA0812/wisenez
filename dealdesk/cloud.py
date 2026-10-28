"""Private SQLite snapshots with conditional writes for the small hosted demo.

Each request loads fresh state. A stale writer cannot overwrite a later approval
or execution. This persistence adapter supports simulated business tools only.
"""
from __future__ import annotations

import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Callable, TypeVar
from urllib.parse import urlparse

import httpx

from .models import WorkflowError
from .storage import Store

T = TypeVar("T")
_lock = threading.RLock()
_API = "https://vercel.com/api/blob"
_OBJECT = "wisnez/workspace-v1.sqlite3"


class StorageConflict(WorkflowError):
    pass


class CloudUnavailable(WorkflowError):
    pass


class BlobSnapshot:
    def __init__(self, token: str):
        self.token = token
        match = re.fullmatch(r"vercel_blob_rw_([A-Za-z0-9]+)_.+", token)
        if not match:
            raise CloudUnavailable("Persistent storage credentials need attention.")
        self.host = match[1].lower() + ".private.blob.vercel-storage.com"

    def headers(self):
        return {"Authorization": "Bearer " + self.token, "x-api-version": "12"}

    def load(self):
        with httpx.Client(timeout=25, follow_redirects=False) as client:
            meta = client.get(_API, params={"url": _OBJECT}, headers=self.headers())
            if meta.status_code == 404:
                return None, None
            if not meta.is_success:
                raise CloudUnavailable("Persistent storage is temporarily unavailable. Please retry.")
            metadata = meta.json()
            url, etag = metadata["url"], metadata["etag"]
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != self.host:
                raise CloudUnavailable("Persistent storage returned an unexpected location.")
            response = client.get(url, params={"revision": etag}, headers={**self.headers(), "Cache-Control": "no-cache"})
            if not response.is_success:
                raise CloudUnavailable("Could not load saved workflows. Please retry.")
            return response.content, etag

    def save(self, data: bytes, etag: str | None):
        headers = {**self.headers(), "x-vercel-blob-access": "private", "x-add-random-suffix": "0",
                   "x-allow-overwrite": "1" if etag else "0", "x-content-type": "application/octet-stream",
                   "x-cache-control-max-age": "0"}
        if etag:
            headers["x-if-match"] = etag
        response = httpx.put(_API, params={"pathname": _OBJECT}, headers=headers, content=data, timeout=25)
        if response.status_code in {409, 412}:
            raise StorageConflict("The workspace changed in another session. Refresh and review the latest version before retrying.")
        if not response.is_success:
            raise CloudUnavailable("Could not save the workspace. Refresh to check saved progress before retrying.")


def operation(callback: Callable[[Store], T], *, write: bool = False) -> T:
    token = os.getenv("BLOB_READ_WRITE_TOKEN", "").strip()
    if not token:
        if os.getenv("VERCEL") == "1":
            raise CloudUnavailable("Persistent storage is not configured. No business changes can execute.")
        with _lock:
            return callback(Store(os.getenv("DEALDESK_DB", "data/wisnez-web.sqlite3")))
    blob = BlobSnapshot(token)
    try:
        data, etag = blob.load()
        with tempfile.TemporaryDirectory(prefix="wisnez-") as folder:
            path = Path(folder) / "workspace.sqlite3"
            if data is not None:
                path.write_bytes(data)
            store = Store(path)
            error = None
            try:
                result = callback(store)
            except WorkflowError as exc:
                error = exc
            if write:
                with store.connection() as con:
                    blob.save(con.serialize(), etag)
            if error:
                raise error
            return result
    except httpx.HTTPError:
        raise CloudUnavailable("The storage connection failed. Refresh to check saved progress before retrying.") from None
