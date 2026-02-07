# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Sync client implementation."""

from __future__ import annotations

import json
import random
import string
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import requests
    import zstandard as zstd
else:
    try:
        import requests
    except ImportError:
        requests = None
    try:
        import zstandard as zstd
    except ImportError:
        zstd = None

SYNC_VERSION = 11
CHUNK_SIZE = 250
DEFAULT_ENDPOINT = "https://sync.ankiweb.net/"


# --- Data Classes ---

@dataclass
class SyncAuth:
    """Authentication credentials for sync."""
    hkey: str = ""
    endpoint: Optional[str] = None
    io_timeout_secs: int = 30

    @classmethod
    def with_endpoint(cls, endpoint: str, hkey: str = "", io_timeout_secs: int = 30) -> SyncAuth:
        if endpoint and not endpoint.endswith("/"):
            endpoint += "/"
        return cls(hkey=hkey, endpoint=endpoint, io_timeout_secs=io_timeout_secs)


class SyncActionRequired(Enum):
    NO_CHANGES = "no_changes"
    NORMAL_SYNC = "normal_sync"
    FULL_SYNC = "full_sync"


@dataclass
class SyncMeta:
    """Sync metadata."""
    modified: int = 0
    schema: int = 0
    usn: int = 0
    current_time: int = 0
    server_message: str = ""
    should_continue: bool = True
    host_number: int = 0
    empty: bool = False
    media_usn: int = 0


@dataclass
class SyncOutput:
    """Result of a sync operation."""
    required: SyncActionRequired
    server_message: str = ""
    host_number: int = 0
    new_endpoint: Optional[str] = None


@dataclass
class Graves:
    """Deleted items to sync."""
    cards: list[int] = field(default_factory=list)
    decks: list[int] = field(default_factory=list)
    notes: list[int] = field(default_factory=list)

    def take_chunk(self) -> Optional[Graves]:
        out, limit = Graves(), CHUNK_SIZE
        for lst, out_lst in [(self.cards, out.cards), (self.notes, out.notes), (self.decks, out.decks)]:
            while limit > 0 and lst:
                out_lst.append(lst.pop())
                limit -= 1
        return None if limit == CHUNK_SIZE else out

    def to_dict(self) -> dict:
        return {"cards": self.cards, "notes": self.notes, "decks": self.decks}

    @classmethod
    def from_dict(cls, d: dict) -> Graves:
        return cls(cards=d.get("cards", []), decks=d.get("decks", []), notes=d.get("notes", []))


@dataclass
class Chunk:
    """Chunk of sync data."""
    done: bool = False
    revlog: list[dict] = field(default_factory=list)
    cards: list[list] = field(default_factory=list)
    notes: list[list] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict = {"done": self.done}
        if self.revlog: d["revlog"] = self.revlog
        if self.cards: d["cards"] = self.cards
        if self.notes: d["notes"] = self.notes
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Chunk:
        return cls(done=d.get("done", False), revlog=d.get("revlog", []),
                   cards=d.get("cards", []), notes=d.get("notes", []))


@dataclass
class UnchunkedChanges:
    """Non-chunked changes (notetypes, decks, tags, config)."""
    notetypes: list[dict] = field(default_factory=list)
    decks: list[dict] = field(default_factory=list)
    deck_config: list[dict] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    config: Optional[dict] = None
    creation_stamp: Optional[int] = None

    def to_dict(self) -> dict:
        d: dict = {"models": self.notetypes, "decks": [self.decks, self.deck_config], "tags": self.tags}
        if self.config is not None: d["conf"] = self.config
        if self.creation_stamp is not None: d["crt"] = self.creation_stamp
        return d

    @classmethod
    def from_dict(cls, d: dict) -> UnchunkedChanges:
        decks = d.get("decks", [[], []])
        return cls(notetypes=d.get("models", []), decks=decks[0] if decks else [],
                   deck_config=decks[1] if len(decks) > 1 else [], tags=d.get("tags", []),
                   config=d.get("conf"), creation_stamp=d.get("crt"))


@dataclass
class SanityCheckCounts:
    """Counts for sanity check."""
    cards: int = 0
    notes: int = 0
    revlog: int = 0
    graves: int = 0
    notetypes: int = 0
    decks: int = 0
    deck_config: int = 0

    def to_list(self) -> list:
        return [[0, 0, 0], self.cards, self.notes, self.revlog, self.graves,
                self.notetypes, self.decks, self.deck_config]


# --- Exceptions ---

class SyncError(Exception):
    pass

class SyncRedirectError(SyncError):
    def __init__(self, new_endpoint: str):
        self.new_endpoint = new_endpoint
        super().__init__(f"Redirect to: {new_endpoint}")

class SanityCheckFailedError(SyncError):
    def __init__(self, client_counts: Any, server_counts: Any):
        self.client_counts, self.server_counts = client_counts, server_counts
        super().__init__("Sanity check failed")


# --- HTTP Client ---

def _check_deps():
    if requests is None:
        raise ImportError("requests required: pip install requests")
    if zstd is None:
        raise ImportError("zstandard required: pip install zstandard")


class HttpSyncClient:
    """HTTP client for sync protocol."""

    def __init__(self, auth: SyncAuth, session: Optional[requests.Session] = None):
        _check_deps()
        self.sync_key = auth.hkey
        self.session_key = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        self.endpoint = auth.endpoint or DEFAULT_ENDPOINT
        self.io_timeout = auth.io_timeout_secs
        self._session = session
        self._owns_session = session is None

    def close(self):
        if self._owns_session and self._session:
            self._session.close()
            self._session = None

    def _request(self, method: str, data: Any = None, raw_data: Optional[bytes] = None) -> bytes:
        if self._session is None:
            self._session = requests.Session()

        body = raw_data if raw_data else json.dumps(data or {}).encode()
        compressed = zstd.ZstdCompressor().compress(body)

        headers = {
            "anki-sync": json.dumps({"v": SYNC_VERSION, "k": self.sync_key,
                                     "c": "anki,python-sync-client,1.0", "s": self.session_key}),
            "Content-Type": "application/octet-stream",
        }

        resp = self._session.post(f"{self.endpoint.rstrip('/')}/sync/{method}",
                                  data=compressed, headers=headers, timeout=self.io_timeout)

        if resp.status_code == 308:
            raise SyncRedirectError(resp.headers.get("location", ""))
        resp.raise_for_status()

        # Decompress response
        content = resp.content
        if orig_size := resp.headers.get("anki-original-size"):
            content = zstd.ZstdDecompressor().decompress(content, max_output_size=int(orig_size))
        elif resp.headers.get("content-encoding") == "zstd":
            content = zstd.ZstdDecompressor().decompress(content, max_output_size=100*1024*1024)
        elif resp.headers.get("content-encoding") == "gzip":
            content = zlib.decompress(content, 16 + zlib.MAX_WBITS)
        return content

    def _json(self, method: str, data: Any = None) -> Any:
        resp = self._request(method, data)
        return json.loads(resp) if resp else None

    # Protocol methods
    def host_key(self, username: str, password: str) -> str:
        return self._json("hostKey", {"u": username, "p": password})["key"]

    def meta(self) -> SyncMeta:
        r = self._json("meta", {"v": SYNC_VERSION, "cv": "python-sync-client,1.0"})
        return SyncMeta(modified=r.get("mod", 0), schema=r.get("scm", 0), usn=r.get("usn", 0),
                        current_time=r.get("ts", 0), server_message=r.get("msg", ""),
                        should_continue=r.get("cont", True), host_number=r.get("hostNum", 0),
                        empty=r.get("empty", False), media_usn=r.get("media_usn", 0))

    def start(self, client_usn: int, local_is_newer: bool) -> Graves:
        return Graves.from_dict(self._json("start", {"minUsn": client_usn, "lnewer": local_is_newer}))

    def apply_graves(self, graves: Graves):
        self._json("applyGraves", {"chunk": graves.to_dict()})

    def apply_changes(self, changes: UnchunkedChanges) -> UnchunkedChanges:
        return UnchunkedChanges.from_dict(self._json("applyChanges", {"changes": changes.to_dict()}))

    def chunk(self) -> Chunk:
        return Chunk.from_dict(self._json("chunk", {}))

    def apply_chunk(self, chunk: Chunk):
        self._json("applyChunk", {"chunk": chunk.to_dict()})

    def sanity_check(self, counts: SanityCheckCounts) -> dict:
        return self._json("sanityCheck2", {"client": counts.to_list()})

    def finish(self) -> int:
        return self._json("finish", {})

    def abort(self):
        try: self._json("abort", {})
        except: pass

    def upload(self, data: bytes) -> str:
        return self._request("upload", raw_data=data).decode()

    def download(self) -> bytes:
        return self._request("download", {})


# --- Collection Interface ---

class CollectionSyncInterface(ABC):
    """Interface for collection sync operations. Implement for your collection."""

    @abstractmethod
    def sync_meta(self) -> SyncMeta: ...
    @abstractmethod
    def get_pending_graves(self, pending_usn: int) -> Graves: ...
    @abstractmethod
    def update_pending_grave_usns(self, server_usn: int) -> None: ...
    @abstractmethod
    def apply_graves(self, graves: Graves, latest_usn: int) -> None: ...
    @abstractmethod
    def get_local_unchunked_changes(self, pending_usn: int, server_usn: int, local_is_newer: bool) -> UnchunkedChanges: ...
    @abstractmethod
    def apply_unchunked_changes(self, changes: UnchunkedChanges, latest_usn: int) -> None: ...
    @abstractmethod
    def get_chunkable_ids(self, pending_usn: int) -> dict: ...
    @abstractmethod
    def get_chunk(self, ids: dict, server_usn: Optional[int]) -> Chunk: ...
    @abstractmethod
    def apply_chunk(self, chunk: Chunk, pending_usn: int) -> None: ...
    @abstractmethod
    def get_sanity_check_counts(self) -> SanityCheckCounts: ...
    @abstractmethod
    def finalize_sync(self, server_usn: int, new_mtime: int) -> None: ...
    @abstractmethod
    def set_schema_modified(self) -> None: ...
    @abstractmethod
    def begin_transaction(self) -> None: ...
    @abstractmethod
    def commit_transaction(self) -> None: ...
    @abstractmethod
    def rollback_transaction(self) -> None: ...
    @abstractmethod
    def get_collection_path(self) -> Path: ...
    @abstractmethod
    def close_for_full_upload(self) -> bytes: ...
    @abstractmethod
    def replace_with_full_download(self, data: bytes) -> None: ...


# --- Sync Client ---

@dataclass
class _SyncState:
    required: SyncActionRequired = SyncActionRequired.NO_CHANGES
    server_message: str = ""
    host_number: int = 0
    new_endpoint: Optional[str] = None
    local_is_newer: bool = False
    usn_at_last_sync: int = 0
    server_usn: int = 0
    pending_usn: int = -1


class SyncClient:
    """Main sync client."""

    def __init__(self, col: CollectionSyncInterface, auth: SyncAuth,
                 session: Optional[requests.Session] = None):
        self.col = col
        self.http = HttpSyncClient(auth, session)
        self._state: Optional[_SyncState] = None

    def close(self):
        self.http.close()

    @classmethod
    def login(cls, username: str, password: str, endpoint: Optional[str] = None) -> SyncAuth:
        """Login to server and return auth credentials."""
        auth = SyncAuth.with_endpoint(endpoint or DEFAULT_ENDPOINT)
        http = HttpSyncClient(auth)
        try:
            hkey = http.host_key(username, password)
            return SyncAuth(hkey=hkey, endpoint=endpoint)
        finally:
            http.close()

    def sync(self) -> SyncOutput:
        """Sync with server. Returns action required."""
        local = self.col.sync_meta()
        remote, new_ep = self._fetch_meta()
        if new_ep:
            self.http.endpoint = new_ep

        self._state = self._compare(local, remote, new_ep)

        if self._state.required != SyncActionRequired.NORMAL_SYNC:
            return SyncOutput(self._state.required, self._state.server_message,
                              self._state.host_number, self._state.new_endpoint)

        self.col.begin_transaction()
        try:
            self._normal_sync()
            self.col.commit_transaction()
            return SyncOutput(SyncActionRequired.NO_CHANGES, self._state.server_message,
                              self._state.host_number, self._state.new_endpoint)
        except Exception as e:
            self.col.rollback_transaction()
            self.http.abort()
            if isinstance(e, SanityCheckFailedError):
                self.col.set_schema_modified()
            raise

    def _fetch_meta(self) -> tuple[SyncMeta, Optional[str]]:
        try:
            return self.http.meta(), None
        except SyncRedirectError as e:
            self.http.endpoint = e.new_endpoint
            return self.http.meta(), e.new_endpoint

    def _compare(self, local: SyncMeta, remote: SyncMeta, new_ep: Optional[str]) -> _SyncState:
        if remote.modified == local.modified:
            req = SyncActionRequired.NO_CHANGES
        elif remote.schema != local.schema:
            req = SyncActionRequired.FULL_SYNC
        else:
            req = SyncActionRequired.NORMAL_SYNC

        return _SyncState(required=req, local_is_newer=local.modified > remote.modified,
                          usn_at_last_sync=local.usn, server_usn=remote.usn,
                          server_message=remote.server_message, host_number=remote.host_number,
                          new_endpoint=new_ep)

    def _normal_sync(self):
        s = self._state
        # Deletions
        remote_graves = self.http.start(s.usn_at_last_sync, s.local_is_newer)
        local_graves = self.col.get_pending_graves(s.pending_usn)
        self.col.update_pending_grave_usns(s.server_usn)
        while chunk := local_graves.take_chunk():
            self.http.apply_graves(chunk)
        self.col.apply_graves(remote_graves, s.server_usn)

        # Unchunked changes
        local_changes = self.col.get_local_unchunked_changes(s.pending_usn, s.server_usn, s.local_is_newer)
        remote_changes = self.http.apply_changes(local_changes)
        self.col.apply_unchunked_changes(remote_changes, s.server_usn)

        # Receive chunks
        while True:
            chunk = self.http.chunk()
            self.col.apply_chunk(chunk, s.pending_usn)
            if chunk.done: break

        # Send chunks
        ids = self.col.get_chunkable_ids(s.pending_usn)
        while True:
            chunk = self.col.get_chunk(ids, s.server_usn)
            self.http.apply_chunk(chunk)
            if chunk.done: break

        # Sanity check
        resp = self.http.sanity_check(self.col.get_sanity_check_counts())
        if resp.get("status") != "ok":
            raise SanityCheckFailedError(resp.get("c"), resp.get("s"))

        # Finalize
        self.col.finalize_sync(s.server_usn, self.http.finish())

    def full_upload(self) -> SyncOutput:
        """Upload entire collection to server."""
        resp = self.http.upload(self.col.close_for_full_upload())
        if resp != "OK":
            raise SyncError(f"Upload failed: {resp}")
        return SyncOutput(SyncActionRequired.NO_CHANGES,
                          self._state.server_message if self._state else "")

    def full_download(self) -> SyncOutput:
        """Download entire collection from server."""
        self.col.replace_with_full_download(self.http.download())
        return SyncOutput(SyncActionRequired.NO_CHANGES,
                          self._state.server_message if self._state else "")
