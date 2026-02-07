#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""
Shared test utilities and configuration for sync client tests.
"""

import os
import random
import shutil
import sqlite3
import string
import tempfile
import time
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from .. import (
    Chunk,
    CollectionSyncInterface,
    Graves,
    HttpSyncClient,
    SanityCheckCounts,
    SyncAuth,
    SyncClient,
    SyncMeta,
    UnchunkedChanges,
)

# Configuration (can be overridden via environment variables)
ENDPOINT = os.getenv("ANKI_ENDPOINT", "http://localhost:8080/")
COLLECTION_PATH = os.getenv(
    "ANKI_COLLECTION", str(Path(__file__).parent / "collection.anki2")
)
USERNAME = os.getenv("ANKI_USERNAME", "user")
PASSWORD = os.getenv("ANKI_PASSWORD", "pass")

# Unicase collation for Anki compatibility
_unicase = lambda x, y: (x.lower() > y.lower()) - (x.lower() < y.lower())


def _connect_db(path: Path) -> sqlite3.Connection:
    """Connect to collection DB with required collation."""
    db = sqlite3.connect(str(path))
    db.create_collation("unicase", _unicase)
    return db


class TestCollection(CollectionSyncInterface):
    """Minimal collection wrapper for full sync testing."""

    def __init__(self, col_path: str):
        self.db_path = Path(tempfile.mkdtemp()) / "collection.anki2"
        shutil.copy(col_path, self.db_path)
        self.db = _connect_db(self.db_path)

    def sync_meta(self) -> SyncMeta:
        c = self.db.cursor()
        c.execute("SELECT mod, scm, usn FROM col WHERE id = 1")
        mod, scm, usn = c.fetchone() or (0, 0, 0)
        c.execute("SELECT 1 FROM cards LIMIT 1")
        return SyncMeta(modified=mod, schema=scm, usn=usn, empty=c.fetchone() is None)

    def close_for_full_upload(self) -> bytes:
        self.db.close()
        return self.db_path.read_bytes()

    def replace_with_full_download(self, data: bytes) -> None:
        self.db.close()
        self.db_path.write_bytes(data)
        self.db = _connect_db(self.db_path)

    def close(self):
        try:
            self.db.close()
        except:
            pass

    def count(self, table: str) -> int:
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    # Stub methods for full sync support
    def get_pending_graves(self, pending_usn: int) -> Graves:
        return Graves()

    def update_pending_grave_usns(self, server_usn: int) -> None:
        pass

    def apply_graves(self, graves: Graves, latest_usn: int) -> None:
        pass

    def get_local_unchunked_changes(
        self, pending_usn: int, server_usn: int, local_is_newer: bool
    ) -> UnchunkedChanges:
        return UnchunkedChanges()

    def apply_unchunked_changes(
        self, changes: UnchunkedChanges, latest_usn: int
    ) -> None:
        pass

    def get_chunkable_ids(self, pending_usn: int) -> dict:
        return {"revlog": [], "cards": [], "notes": []}

    def get_chunk(self, ids: dict, server_usn: int | None) -> Chunk:
        return Chunk(done=True)

    def apply_chunk(self, chunk: Chunk, pending_usn: int) -> None:
        pass

    def get_sanity_check_counts(self) -> SanityCheckCounts:
        return SanityCheckCounts()

    def finalize_sync(self, server_usn: int, new_mtime: int) -> None:
        pass

    def set_schema_modified(self) -> None:
        pass

    def begin_transaction(self) -> None:
        pass

    def commit_transaction(self) -> None:
        pass

    def rollback_transaction(self) -> None:
        pass

    def get_collection_path(self) -> Path:
        return self.db_path


@contextmanager
def sync_client(auth: SyncAuth):
    """Context manager for TestCollection + SyncClient."""
    col = TestCollection(COLLECTION_PATH)
    client = SyncClient(col, auth)
    try:
        yield col, client
    finally:
        col.close()
        client.close()


def add_note(db: sqlite3.Connection, front: str, back: str) -> int:
    """Add a note and card to collection. Returns note id."""
    note_id = int(time.time() * 1000)
    mod = int(time.time())
    guid = "".join(random.choices(string.ascii_letters + string.digits, k=10))
    mid = db.execute("SELECT id FROM notetypes WHERE name='Basic' LIMIT 1").fetchone()[
        0
    ]
    csum = zlib.crc32(front.encode()) & 0xFFFFFFFF

    db.execute(
        "INSERT INTO notes (id,guid,mid,mod,usn,tags,flds,sfld,csum,flags,data) VALUES (?,?,?,?,-1,'',?,?,?,0,'')",
        (note_id, guid, mid, mod, f"{front}\x1f{back}", front, csum),
    )
    db.execute(
        "INSERT INTO cards (id,nid,did,ord,mod,usn,type,queue,due,ivl,factor,reps,lapses,left,odue,odid,flags,data) VALUES (?,?,1,0,?,-1,0,0,0,0,0,0,0,0,0,0,0,'')",
        (note_id + 1, note_id, mod),
    )
    db.execute("UPDATE col SET mod=? WHERE id=1", (mod * 1000,))
    db.commit()
    return note_id


def check_dependencies() -> bool:
    """Check if required dependencies are installed."""
    try:
        import requests, zstandard  # noqa: F401

        return True
    except ImportError as e:
        print(f"  Missing: {e.name} - run: pip install {e.name}")
        return False


def login() -> Optional[SyncAuth]:
    """Login and return auth credentials."""
    try:
        auth = SyncClient.login(USERNAME, PASSWORD, endpoint=ENDPOINT)
        print(f"  Logged in with host key: {auth.hkey[:20]}...")
        return auth
    except Exception as e:
        print(f"  Login failed: {type(e).__name__}: {e}")
        return None


class TestRunner:
    """Simple test runner with results tracking."""

    def __init__(self):
        self.results: list[tuple[str, bool]] = []

    def run(self, name: str, func) -> bool:
        print(f"\n{'=' * 60}\nTEST: {name}\n{'=' * 60}")
        try:
            passed = func()
            if passed:
                print("  SUCCESS!")
            self.results.append((name, passed))
            return passed
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            self.results.append((name, False))
            return False

    def summary(self) -> bool:
        print(f"\n{'=' * 60}\nTEST SUMMARY\n{'=' * 60}")
        for name, passed in self.results:
            print(f"  {name}: {'PASS' if passed else 'FAIL'}")
        passed_count = sum(p for _, p in self.results)
        total = len(self.results)
        print(f"\n  Total: {passed_count}/{total} tests passed")
        return passed_count == total
