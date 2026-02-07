#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""
Download collection from server, modify it (add a note), and upload it back.

Usage: uv run --env-file tests/.env python -m ankiclientsync.tests.test_download
"""

import time
from pathlib import Path

from .conftest import (
    COLLECTION_PATH,
    ENDPOINT,
    add_note,
    check_dependencies,
    login,
    sync_client,
)


def main():
    print(f"{'=' * 60}\nANKI SYNC CLIENT - DOWNLOAD, MODIFY, UPLOAD\n{'=' * 60}")
    print(f"Endpoint: {ENDPOINT}")
    print(f"Collection: {COLLECTION_PATH}")

    if not check_dependencies():
        return False

    if not Path(COLLECTION_PATH).exists():
        print(f"ERROR: Collection not found at {COLLECTION_PATH}")
        return False

    # Login
    print("\n[1/4] Logging in...")
    auth = login()
    if not auth:
        print("ERROR: Login failed")
        return False

    # Download
    print("\n[2/4] Downloading collection from server...")
    with sync_client(auth) as (col, client):
        client.full_download()
        notes_before = col.count("notes")
        cards = col.count("cards")
        print(f"  Downloaded: {notes_before} notes, {cards} cards")

        # Modify
        print("\n[3/4] Adding a new note...")
        ts = int(time.time())
        note_id = add_note(
            col.db,
            f"Test Note {ts}",
            f"This note was added at {ts}",
        )
        notes_after = col.count("notes")
        print(f"  Added note {note_id}")
        print(f"  Notes: {notes_before} -> {notes_after}")

        # Upload
        print("\n[4/4] Uploading modified collection...")
        result = client.full_upload()
        print(f"  Upload complete: {result.required.value}")

    print(f"\nSUCCESS: Downloaded, added 1 note, and uploaded to {ENDPOINT}")
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
