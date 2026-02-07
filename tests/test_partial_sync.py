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

import sys
import time

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


def test_partial_sync_no_changes(auth) -> bool:
    """Test partial sync when there are no local changes."""
    print("  Testing partial sync with no local changes...")

    # First do a full upload to ensure server has our collection
    col = SyncableCollection(COLLECTION_PATH)
    client = SyncClient(col, auth)

    try:
        result = client.sync()
        print(f"  Initial sync result: {result.required}")

        if result.required == SyncActionRequired.FULL_SYNC:
            print("  Full sync required, uploading...")
            client.full_upload()

            # Reopen and sync again
            col = SyncableCollection(COLLECTION_PATH)
            client = SyncClient(col, auth)
            result = client.sync()
            print(f"  Post-upload sync result: {result.required}")

        # Now sync again - should be NO_CHANGES
        col.close()
        col = SyncableCollection(COLLECTION_PATH)
        client = SyncClient(col, auth)
        result = client.sync()
        print(f"  Second sync result: {result.required}")

        return result.required == SyncActionRequired.NO_CHANGES

    finally:
        col.close()
        client.close()


def test_partial_sync_with_local_changes(auth) -> bool:
    """Test partial sync after adding a local note."""
    print("  Testing partial sync with local changes...")

    col = SyncableCollection(COLLECTION_PATH)
    client = SyncClient(col, auth)

    try:
        # First sync to get current state
        result = client.sync()
        print(f"  Initial sync result: {result.required}")

        if result.required == SyncActionRequired.FULL_SYNC:
            print("  Full sync required, uploading...")
            client.full_upload()

            # Reopen
            col = SyncableCollection(COLLECTION_PATH)
            client = SyncClient(col, auth)

        # Add a new note locally
        timestamp = int(time.time())
        front = f"Partial sync test {timestamp}"
        back = f"Added at {timestamp}"
        note_id = col.add_note(front, back)
        print(f"  Added note {note_id}: {front}")

        # Count pending items
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
        col.close()
        client.close()


def test_partial_sync_roundtrip(auth) -> bool:
    """Test that changes sync correctly in both directions."""
    print("  Testing partial sync roundtrip...")

    # First, sync collection to server
    col1 = SyncableCollection(COLLECTION_PATH)
    client1 = SyncClient(col1, auth)

    try:
        result = client1.sync()
        print(f"  Initial sync: {result.required}")

        if result.required == SyncActionRequired.FULL_SYNC:
            print("  Full sync required, uploading...")
            client1.full_upload()
            col1 = SyncableCollection(COLLECTION_PATH)
            client1 = SyncClient(col1, auth)

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

        # Now download from server and verify
        col2 = SyncableCollection(COLLECTION_PATH)
        client2 = SyncClient(col2, auth)

        result = client2.sync()
        print(f"  Second client sync: {result.required}")

        # Check if the note exists
        row = col2.db.execute(
            "SELECT id, flds FROM notes WHERE id = ?", (note_id,)
        ).fetchone()

        if row:
            print(f"  Found synced note: {row['flds'][:50]}...")
            col2.close()
            client2.close()
            return True
        else:
            print("  ERROR: Synced note not found in second collection")
            col2.close()
            client2.close()
            return False

    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        try:
            col1.close()
            client1.close()
        except:
            pass


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
