#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""
Upload the local collection to the sync server.

Usage: uv run --env-file tests/.env python -m ankiclientsync.tests.test_upload
"""

import sqlite3
from pathlib import Path

from .conftest import (
    COLLECTION_PATH,
    ENDPOINT,
    check_dependencies,
    login,
    sync_client,
)


def main():
    print(f"{'=' * 60}\nANKI SYNC CLIENT - UPLOAD\n{'=' * 60}")
    print(f"Endpoint: {ENDPOINT}")
    print(f"Collection: {COLLECTION_PATH}")

    if not check_dependencies():
        return False

    if not Path(COLLECTION_PATH).exists():
        print(f"ERROR: Collection not found at {COLLECTION_PATH}")
        return False

    # Login
    print("\n[1/3] Logging in...")
    auth = login()
    if not auth:
        print("ERROR: Login failed")
        return False

    # Inspect local collection
    print("\n[2/3] Inspecting local collection...")
    with sqlite3.connect(COLLECTION_PATH) as db:
        notes = db.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        cards = db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    print(f"  Local collection: {notes} notes, {cards} cards")

    # Upload
    print("\n[3/3] Uploading to server...")
    with sync_client(auth) as (col, client):
        result = client.full_upload()

    print(f"  Upload complete: {result.required.value}")
    print(f"\nSUCCESS: Collection uploaded to {ENDPOINT}")
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
