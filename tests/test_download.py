#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""
Download collection from server and export to .apkg file.

Usage: uv run --env-file tests/.env python -m ankiclientsync.tests.test_download
"""

import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from .. import MediaSyncClient, SyncClient, SyncableCollection
from .conftest import (
    ENDPOINT,
    TestRunner,
    check_dependencies,
    login,
)


def main():
    print(f"{'=' * 60}\nANKI SYNC CLIENT - DOWNLOAD & EXPORT TESTS\n{'=' * 60}")
    print(f"Endpoint: {ENDPOINT}")

    if not check_dependencies():
        return False

    # Login
    print("\nLogging in...")
    auth = login()
    if not auth:
        print("ERROR: Login failed")
        return False

    runner = TestRunner()
    runner.run("Download collection", lambda: test_download_collection(auth))
    runner.run("Export to .apkg (basic)", lambda: test_export_basic(auth))
    runner.run("Export to .apkg (with media)", lambda: test_export_with_media(auth))
    runner.run("Verify .apkg structure", lambda: test_verify_apkg_structure(auth))

    return runner.summary()


def test_download_collection(auth):
    """Test downloading collection from server."""
    col_path = Path(tempfile.gettempdir()) / "test_collection.anki2"
    _create_empty_collection(col_path)

    col = SyncableCollection(col_path)
    client = SyncClient(col, auth)

    try:
        client.full_download()
        notes = col.count("notes")
        cards = col.count("cards")
        print(f"  Downloaded: {notes} notes, {cards} cards")

        if notes == 0:
            print("  WARNING: No notes downloaded (server may be empty)")

        return True
    finally:
        col.close()
        client.close()


def test_export_basic(auth):
    """Test basic export to .apkg without media."""
    col_path = Path(tempfile.gettempdir()) / "test_collection.anki2"
    _create_empty_collection(col_path)

    col = SyncableCollection(col_path)
    client = SyncClient(col, auth)

    try:
        client.full_download()
        notes_before = col.count("notes")

        # Export without media
        apkg_path = Path(tempfile.gettempdir()) / "test_export.apkg"
        exported_notes = col.export_anki_package(apkg_path, with_media=False)

        print(f"  Exported: {exported_notes} notes to {apkg_path}")
        print(f"  File size: {apkg_path.stat().st_size} bytes")

        if exported_notes != notes_before:
            print(f"  ERROR: Expected {notes_before} notes, got {exported_notes}")
            return False

        if not apkg_path.exists():
            print("  ERROR: Export file not created")
            return False

        return True
    finally:
        col.close()
        client.close()


def test_export_with_media(auth):
    """Test export to .apkg with media files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        col_path = tmpdir / "collection.anki2"
        media_folder = tmpdir / "collection.media"
        media_folder.mkdir()

        _create_empty_collection(col_path)

        col = SyncableCollection(col_path, media_folder=media_folder)
        client = SyncClient(col, auth)

        try:
            # Download collection
            client.full_download()
            notes = col.count("notes")
            print(f"  Downloaded: {notes} notes")

            # Download media
            media_client = MediaSyncClient(media_folder, auth)
            try:
                stats = media_client.sync()
                print(f"  Downloaded: {stats['downloaded']} media files")
            finally:
                media_client.close()

            # Export with media
            apkg_path = tmpdir / "export_with_media.apkg"
            exported_notes = col.export_anki_package(apkg_path, with_media=True)

            print(f"  Exported: {exported_notes} notes")
            print(f"  File size: {apkg_path.stat().st_size} bytes")

            # Verify media is in the package
            with zipfile.ZipFile(apkg_path, "r") as zf:
                files = zf.namelist()
                # Count media files (numeric names)
                media_count = sum(1 for f in files if f.isdigit())
                print(f"  Media files in package: {media_count}")

            return True
        finally:
            col.close()
            client.close()


def test_verify_apkg_structure(auth):
    """Verify the .apkg file structure is correct."""
    col_path = Path(tempfile.gettempdir()) / "test_collection.anki2"
    _create_empty_collection(col_path)

    col = SyncableCollection(col_path)
    client = SyncClient(col, auth)

    try:
        client.full_download()

        # Export
        apkg_path = Path(tempfile.gettempdir()) / "test_structure.apkg"
        col.export_anki_package(apkg_path)

        # Verify structure
        with zipfile.ZipFile(apkg_path, "r") as zf:
            files = zf.namelist()
            print(f"  Files in package: {files}")

            # Required files
            required = ["meta", "collection.anki21b", "collection.anki2", "media"]
            for req in required:
                if req not in files:
                    print(f"  ERROR: Missing required file: {req}")
                    return False

            # Verify meta file (protobuf with version)
            meta_data = zf.read("meta")
            if len(meta_data) < 2:
                print("  ERROR: meta file too small")
                return False
            print(f"  meta file: {len(meta_data)} bytes")

            # Verify collection.anki21b is zstd compressed
            col_data = zf.read("collection.anki21b")
            # zstd magic number: 0x28 0xB5 0x2F 0xFD
            if col_data[:4] == b"\x28\xb5\x2f\xfd":
                print("  collection.anki21b: zstd compressed")
            else:
                print("  WARNING: collection.anki21b may not be zstd compressed")

            # Verify collection.anki2 (legacy dummy)
            legacy_data = zf.read("collection.anki2")
            print(f"  collection.anki2 (legacy): {len(legacy_data)} bytes")

            # Verify media file exists
            media_data = zf.read("media")
            print(f"  media: {len(media_data)} bytes")

        return True
    finally:
        col.close()
        client.close()


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
