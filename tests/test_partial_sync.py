#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""
Test partial (incremental) sync using SyncableCollection.

This test uses the full SyncableCollection implementation that supports
partial sync, unlike the TestCollection stub that only supports full sync.

Usage:
    uv run --env-file tests/.env python -m ankiclientsync.tests.test_partial_sync
"""

import shutil
import sys
import tempfile
import time
from pathlib import Path

from .. import SyncActionRequired, SyncClient, SyncableCollection
from .conftest import (
    COLLECTION_PATH,
    ENDPOINT,
    PASSWORD,
    USERNAME,
    TestRunner,
    check_dependencies,
    login,
)


def _create_temp_collection() -> tuple[Path, Path]:
    """Create a temporary copy of the test collection.

    Returns (work_dir, collection_path) where collection_path is the copy.
    """
    work_dir = Path(tempfile.mkdtemp())
    col_copy = work_dir / "collection.anki2"
    shutil.copy(COLLECTION_PATH, col_copy)
    return work_dir, col_copy


def _reset_server_and_sync(
    auth, col_path: Path
) -> tuple[SyncableCollection, SyncClient]:
    """Reset server with a full upload and return a synced collection.

    This ensures each test starts with a clean, synchronized state.
    """
    col = SyncableCollection(col_path)
    client = SyncClient(col, auth)

    # Always do a full upload to reset server state
    print("  Resetting server with full upload...")
    client.full_upload()

    # Reopen the collection (it was closed during upload)
    col = SyncableCollection(col_path)
    client = SyncClient(col, auth)

    return col, client


def test_partial_sync_no_changes(auth) -> bool:
    """Test partial sync when there are no local changes."""
    print("  Testing partial sync with no local changes...")

    work_dir, col_path = _create_temp_collection()
    col = None
    client = None

    try:
        # Reset server and get synced collection
        col, client = _reset_server_and_sync(auth, col_path)

        # Now sync again - should be NO_CHANGES
        result = client.sync()
        print(f"  Sync result: {result.required}")

        return result.required == SyncActionRequired.NO_CHANGES

    finally:
        if col:
            col.close()
        if client:
            client.close()
        shutil.rmtree(work_dir, ignore_errors=True)


def test_partial_sync_with_local_changes(auth) -> bool:
    """Test partial sync after adding a local note."""
    print("  Testing partial sync with local changes...")

    work_dir, col_path = _create_temp_collection()
    col = None
    client = None

    try:
        # Reset server and get synced collection
        col, client = _reset_server_and_sync(auth, col_path)

        # Add a new note locally
        timestamp = int(time.time())
        front = f"Partial sync test {timestamp}"
        back = f"Added at {timestamp}"
        note_id = col.add_note(front, back)
        print(f"  Added note {note_id}: {front}")

        # Count pending items (should only be 1 note and 1 card)
        pending_notes = col.db.execute(
            "SELECT COUNT(*) FROM notes WHERE usn = -1"
        ).fetchone()[0]
        pending_cards = col.db.execute(
            "SELECT COUNT(*) FROM cards WHERE usn = -1"
        ).fetchone()[0]
        print(f"  Pending: {pending_notes} notes, {pending_cards} cards")

        # Sync - should do normal sync, not full sync
        result = client.sync()
        print(f"  Sync after changes result: {result.required}")

        # Verify note was synced (USN should no longer be -1)
        note_usn = col.db.execute(
            "SELECT usn FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if note_usn:
            print(f"  Note USN after sync: {note_usn[0]}")
            if note_usn[0] == -1:
                print("  ERROR: Note USN still -1 after sync")
                return False
        else:
            print("  ERROR: Note not found after sync")
            return False

        return result.required == SyncActionRequired.NO_CHANGES

    finally:
        if col:
            col.close()
        if client:
            client.close()
        shutil.rmtree(work_dir, ignore_errors=True)


def test_partial_sync_roundtrip(auth) -> bool:
    """Test that changes sync correctly in both directions."""
    print("  Testing partial sync roundtrip...")

    work_dir, col_path = _create_temp_collection()
    col1 = None
    client1 = None
    col2 = None
    client2 = None

    try:
        # Reset server and get synced collection
        col1, client1 = _reset_server_and_sync(auth, col_path)

        # Add a note
        timestamp = int(time.time())
        front = f"Roundtrip test {timestamp}"
        back = f"Test value {timestamp}"
        note_id = col1.add_note(front, back)
        print(f"  Added note {note_id}")

        # Sync to send changes to server
        result = client1.sync()
        print(f"  Sync after adding note: {result.required}")

        # Get final counts
        note_count = col1.count("notes")
        card_count = col1.count("cards")
        print(f"  Final counts: {note_count} notes, {card_count} cards")

        col1.close()
        client1.close()
        col1 = None
        client1 = None

        # Now reopen and sync again to verify the note persisted
        col2 = SyncableCollection(col_path)
        client2 = SyncClient(col2, auth)

        result = client2.sync()
        print(f"  Second client sync: {result.required}")

        # Check if the note exists
        row = col2.db.execute(
            "SELECT id, flds FROM notes WHERE id = ?", (note_id,)
        ).fetchone()

        if row:
            print(f"  Found synced note: {row['flds'][:50]}...")
            return True
        else:
            print("  ERROR: Synced note not found in second collection")
            return False

    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        if col1:
            col1.close()
        if client1:
            client1.close()
        if col2:
            col2.close()
        if client2:
            client2.close()
        shutil.rmtree(work_dir, ignore_errors=True)


def main():
    print("=" * 60)
    print("PARTIAL SYNC TEST")
    print("=" * 60)
    print(f"Endpoint: {ENDPOINT}")
    print(f"Collection: {COLLECTION_PATH}")
    print()

    # Check dependencies
    print("Checking dependencies...")
    if not check_dependencies():
        print("Missing dependencies!")
        return 1
    print("  All dependencies OK")

    # Login
    print("\nLogging in...")
    auth = login()
    if not auth:
        print("Login failed!")
        return 1

    # Run tests
    runner = TestRunner()

    runner.run("Partial sync - no changes", lambda: test_partial_sync_no_changes(auth))
    runner.run(
        "Partial sync - with local changes",
        lambda: test_partial_sync_with_local_changes(auth),
    )
    runner.run("Partial sync - roundtrip", lambda: test_partial_sync_roundtrip(auth))

    # Summary
    return 0 if runner.summary() else 1


if __name__ == "__main__":
    sys.exit(main())
