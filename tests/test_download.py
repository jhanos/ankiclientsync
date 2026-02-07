#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""
Download collection from server and export to .apkg file.

Usage: uv run --env-file tests/.env python -m ankiclientsync.tests.test_download
"""

import sqlite3
import tempfile
from pathlib import Path

from .. import SyncClient, SyncableCollection
from .conftest import (
    ENDPOINT,
    check_dependencies,
    login,
)


def main():
    print(f"{'=' * 60}\nANKI SYNC CLIENT - DOWNLOAD & EXPORT\n{'=' * 60}")
    print(f"Endpoint: {ENDPOINT}")

    if not check_dependencies():
        return False

    # Login
    print("\n[1/3] Logging in...")
    auth = login()
    if not auth:
        print("ERROR: Login failed")
        return False

    # Create empty collection in /tmp/
    print("\n[2/3] Downloading collection from server...")
    col_path = Path(tempfile.gettempdir()) / "collection.anki2"

    # Create a minimal empty collection database for download
    _create_empty_collection(col_path)

    col = SyncableCollection(col_path)
    client = SyncClient(col, auth)

    try:
        client.full_download()
        notes = col.count("notes")
        cards = col.count("cards")
        print(f"  Downloaded: {notes} notes, {cards} cards")
        print(f"  Saved to: {col_path}")

        # Export to .apkg
        print("\n[3/3] Exporting to .apkg...")
        apkg_path = Path(tempfile.gettempdir()) / "collection.apkg"
        exported_notes = col.export_anki_package(apkg_path)
        print(f"  Exported: {exported_notes} notes")
        print(f"  Saved to: {apkg_path}")

    finally:
        col.close()
        client.close()

    print(f"\nSUCCESS: Downloaded and exported to {apkg_path}")
    return True


def _create_empty_collection(path: Path) -> None:
    """Create a minimal empty Anki collection database."""
    if path.exists():
        path.unlink()

    db = sqlite3.connect(str(path))
    db.executescript("""
        -- Collection metadata
        CREATE TABLE col (
            id INTEGER PRIMARY KEY,
            crt INTEGER NOT NULL,
            mod INTEGER NOT NULL,
            scm INTEGER NOT NULL,
            ver INTEGER NOT NULL,
            dty INTEGER NOT NULL,
            usn INTEGER NOT NULL,
            ls INTEGER NOT NULL,
            conf TEXT NOT NULL,
            models TEXT NOT NULL,
            decks TEXT NOT NULL,
            dconf TEXT NOT NULL,
            tags TEXT NOT NULL
        );
        INSERT INTO col VALUES(1, 0, 0, 0, 11, 0, 0, 0, '{}', '{}', '{}', '{}', '{}');
        
        -- Notes
        CREATE TABLE notes (
            id INTEGER PRIMARY KEY,
            guid TEXT NOT NULL,
            mid INTEGER NOT NULL,
            mod INTEGER NOT NULL,
            usn INTEGER NOT NULL,
            tags TEXT NOT NULL,
            flds TEXT NOT NULL,
            sfld TEXT NOT NULL,
            csum INTEGER NOT NULL,
            flags INTEGER NOT NULL,
            data TEXT NOT NULL
        );
        
        -- Cards
        CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            nid INTEGER NOT NULL,
            did INTEGER NOT NULL,
            ord INTEGER NOT NULL,
            mod INTEGER NOT NULL,
            usn INTEGER NOT NULL,
            type INTEGER NOT NULL,
            queue INTEGER NOT NULL,
            due INTEGER NOT NULL,
            ivl INTEGER NOT NULL,
            factor INTEGER NOT NULL,
            reps INTEGER NOT NULL,
            lapses INTEGER NOT NULL,
            left INTEGER NOT NULL,
            odue INTEGER NOT NULL,
            odid INTEGER NOT NULL,
            flags INTEGER NOT NULL,
            data TEXT NOT NULL
        );
        
        -- Review log
        CREATE TABLE revlog (
            id INTEGER PRIMARY KEY,
            cid INTEGER NOT NULL,
            usn INTEGER NOT NULL,
            ease INTEGER NOT NULL,
            ivl INTEGER NOT NULL,
            lastIvl INTEGER NOT NULL,
            factor INTEGER NOT NULL,
            time INTEGER NOT NULL,
            type INTEGER NOT NULL
        );
        
        -- Graves (deleted items)
        CREATE TABLE graves (
            usn INTEGER NOT NULL,
            oid INTEGER NOT NULL,
            type INTEGER NOT NULL
        );
        
        -- Notetypes (modern schema)
        CREATE TABLE notetypes (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            mtime_secs INTEGER NOT NULL,
            usn INTEGER NOT NULL,
            config BLOB NOT NULL
        );
        
        -- Fields
        CREATE TABLE fields (
            ntid INTEGER NOT NULL,
            ord INTEGER NOT NULL,
            name TEXT NOT NULL,
            config BLOB NOT NULL,
            PRIMARY KEY (ntid, ord)
        );
        
        -- Templates
        CREATE TABLE templates (
            ntid INTEGER NOT NULL,
            ord INTEGER NOT NULL,
            name TEXT NOT NULL,
            mtime_secs INTEGER NOT NULL,
            usn INTEGER NOT NULL,
            config BLOB NOT NULL,
            PRIMARY KEY (ntid, ord)
        );
        
        -- Decks (modern schema)
        CREATE TABLE decks (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            mtime_secs INTEGER NOT NULL,
            usn INTEGER NOT NULL,
            common BLOB NOT NULL,
            kind BLOB NOT NULL
        );
        
        -- Deck config
        CREATE TABLE deck_config (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            mtime_secs INTEGER NOT NULL,
            usn INTEGER NOT NULL,
            config BLOB NOT NULL
        );
        
        -- Tags
        CREATE TABLE tags (
            tag TEXT PRIMARY KEY,
            usn INTEGER NOT NULL
        );
    """)
    db.commit()
    db.close()


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
