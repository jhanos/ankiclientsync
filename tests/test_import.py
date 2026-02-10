#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""
Test importing .apkg files and uploading to server.

Usage: uv run --env-file tests/.env python -m ankiclientsync.tests.test_import
"""

import tempfile
from pathlib import Path

from .. import SyncClient, SyncableCollection, MediaSyncClient
from .conftest import (
    ENDPOINT,
    TestRunner,
    check_dependencies,
    login,
)


def main():
    print(f"{'=' * 60}\nANKI SYNC CLIENT - IMPORT TESTS\n{'=' * 60}")
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
    runner.run(
        "Export then import roundtrip", lambda: test_export_import_roundtrip(auth)
    )
    runner.run("Import from .apkg (from_apkg)", lambda: test_from_apkg(auth))
    runner.run("Merge import (import_apkg)", lambda: test_merge_import(auth))
    runner.run("Import and upload to server", lambda: test_import_and_upload(auth))
    runner.run(
        "Import Android .apkg and upload",
        lambda: test_import_android_apkg_and_upload(auth),
    )

    return runner.summary()


def test_export_import_roundtrip(auth):
    """Test exporting a collection and importing it back."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Download collection from server
        col_path = tmpdir / "original.anki2"
        _create_empty_collection(col_path)

        col = SyncableCollection(col_path)
        client = SyncClient(col, auth)

        try:
            client.full_download()
            original_notes = col.count("notes")
            original_cards = col.count("cards")
            print(f"  Downloaded: {original_notes} notes, {original_cards} cards")

            # Export to .apkg
            apkg_path = tmpdir / "export.apkg"
            col.export_anki_package(apkg_path)
            print(f"  Exported to: {apkg_path}")

        finally:
            col.close()
            client.close()

        # Import from .apkg into new collection
        import_dir = tmpdir / "imported"
        imported_col = SyncableCollection.from_apkg(apkg_path, import_dir)

        try:
            imported_notes = imported_col.count("notes")
            imported_cards = imported_col.count("cards")
            print(f"  Imported: {imported_notes} notes, {imported_cards} cards")

            if imported_notes != original_notes:
                print(
                    f"  ERROR: Note count mismatch: {imported_notes} != {original_notes}"
                )
                return False

            if imported_cards != original_cards:
                print(
                    f"  ERROR: Card count mismatch: {imported_cards} != {original_cards}"
                )
                return False

        finally:
            imported_col.close()

    return True


def test_from_apkg(auth):
    """Test creating a collection from .apkg using class method."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # First, create an .apkg to import
        col_path = tmpdir / "source.anki2"
        _create_empty_collection(col_path)

        col = SyncableCollection(col_path)
        client = SyncClient(col, auth)

        try:
            client.full_download()
            apkg_path = tmpdir / "source.apkg"
            col.export_anki_package(apkg_path)
        finally:
            col.close()
            client.close()

        # Use from_apkg to create new collection
        output_dir = tmpdir / "from_apkg"
        new_col = SyncableCollection.from_apkg(apkg_path, output_dir)

        try:
            notes = new_col.count("notes")
            cards = new_col.count("cards")
            print(f"  Created collection with: {notes} notes, {cards} cards")

            # Verify files exist
            if not (output_dir / "collection.anki2").exists():
                print("  ERROR: collection.anki2 not created")
                return False

            print(f"  Collection path: {new_col.db_path}")
            print(f"  Media folder: {new_col.media_folder}")

        finally:
            new_col.close()

    return True


def test_merge_import(auth):
    """Test merging an .apkg into an existing collection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create source .apkg
        source_path = tmpdir / "source.anki2"
        _create_empty_collection(source_path)

        source_col = SyncableCollection(source_path)
        source_client = SyncClient(source_col, auth)

        try:
            source_client.full_download()
            source_notes = source_col.count("notes")
            apkg_path = tmpdir / "to_merge.apkg"
            source_col.export_anki_package(apkg_path)
            print(f"  Source .apkg has: {source_notes} notes")
        finally:
            source_col.close()
            source_client.close()

        # Create target collection and import
        target_path = tmpdir / "target.anki2"
        _create_empty_collection(target_path)

        target_col = SyncableCollection(target_path, media_folder=tmpdir / "media")

        try:
            initial_notes = target_col.count("notes")
            print(f"  Target before import: {initial_notes} notes")

            # Import
            stats = target_col.import_apkg(apkg_path)
            print(f"  Import stats: {stats}")

            final_notes = target_col.count("notes")
            print(f"  Target after import: {final_notes} notes")

            if final_notes != source_notes:
                print(f"  ERROR: Expected {source_notes} notes, got {final_notes}")
                return False

        finally:
            target_col.close()

    return True


def test_import_and_upload(auth):
    """Test importing an .apkg and uploading to server."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # First, get current server state
        check_path = tmpdir / "check.anki2"
        _create_empty_collection(check_path)

        check_col = SyncableCollection(check_path)
        check_client = SyncClient(check_col, auth)

        try:
            check_client.full_download()
            server_notes = check_col.count("notes")
            print(f"  Server currently has: {server_notes} notes")

            # Export to .apkg
            apkg_path = tmpdir / "server_export.apkg"
            check_col.export_anki_package(apkg_path)
        finally:
            check_col.close()
            check_client.close()

        # Import .apkg into new collection
        import_dir = tmpdir / "to_upload"
        col = SyncableCollection.from_apkg(apkg_path, import_dir)
        client = SyncClient(col, auth)

        try:
            notes_before = col.count("notes")
            print(f"  Imported collection: {notes_before} notes")

            # Upload to server
            client.full_upload()
            print("  Uploaded to server successfully")

        finally:
            col.close()
            client.close()

        # Verify by downloading again
        verify_path = tmpdir / "verify.anki2"
        _create_empty_collection(verify_path)

        verify_col = SyncableCollection(verify_path)
        verify_client = SyncClient(verify_col, auth)

        try:
            verify_client.full_download()
            verified_notes = verify_col.count("notes")
            print(f"  Verified server has: {verified_notes} notes")

            if verified_notes != server_notes:
                print(
                    f"  WARNING: Note count changed: {server_notes} -> {verified_notes}"
                )

        finally:
            verify_col.close()
            verify_client.close()

    return True


def test_import_android_apkg_and_upload(auth):
    """Test importing an Android-exported .apkg and uploading to server."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Use the Android-exported .apkg from test fixtures
        android_apkg = Path(__file__).parent / "collection_android.apkg"
        if not android_apkg.exists():
            print(f"  SKIP: {android_apkg} not found")
            return True

        print(f"  Importing: {android_apkg}")

        # Import .apkg into new collection
        import_dir = tmpdir / "android_import"
        col = SyncableCollection.from_apkg(android_apkg, import_dir)

        try:
            notes = col.count("notes")
            cards = col.count("cards")
            notetypes = col.count("notetypes")
            decks = col.count("decks")
            print(f"  Imported: {notes} notes, {cards} cards")
            print(f"  Notetypes: {notetypes}, Decks: {decks}")

            # Verify collection has required structure
            if notes == 0:
                print("  WARNING: No notes in Android .apkg")

            # Upload to server
            client = SyncClient(col, auth)
            try:
                client.full_upload()
                print("  Uploaded to server successfully")
            finally:
                client.close()

        finally:
            col.close()

        # Verify by downloading and checking
        verify_path = tmpdir / "verify.anki2"
        _create_empty_collection(verify_path)

        verify_col = SyncableCollection(verify_path)
        verify_client = SyncClient(verify_col, auth)

        try:
            verify_client.full_download()
            verified_notes = verify_col.count("notes")
            verified_cards = verify_col.count("cards")
            print(f"  Verified server: {verified_notes} notes, {verified_cards} cards")

            if verified_notes != notes:
                print(
                    f"  ERROR: Note count mismatch: expected {notes}, got {verified_notes}"
                )
                return False

            if verified_cards != cards:
                print(
                    f"  ERROR: Card count mismatch: expected {cards}, got {verified_cards}"
                )
                return False

        finally:
            verify_col.close()
            verify_client.close()

    return True


def _create_empty_collection(path: Path) -> None:
    """Create a minimal empty Anki collection database."""
    import sqlite3

    if path.exists():
        path.unlink()

    db = sqlite3.connect(str(path))
    db.executescript("""
        CREATE TABLE col (
            id INTEGER PRIMARY KEY, crt INTEGER, mod INTEGER, scm INTEGER,
            ver INTEGER, dty INTEGER, usn INTEGER, ls INTEGER,
            conf TEXT, models TEXT, decks TEXT, dconf TEXT, tags TEXT
        );
        INSERT INTO col VALUES(1, 0, 0, 0, 11, 0, 0, 0, '{}', '{}', '{}', '{}', '{}');
        
        CREATE TABLE notes (
            id INTEGER PRIMARY KEY, guid TEXT, mid INTEGER, mod INTEGER,
            usn INTEGER, tags TEXT, flds TEXT, sfld TEXT, csum INTEGER,
            flags INTEGER, data TEXT
        );
        CREATE TABLE cards (
            id INTEGER PRIMARY KEY, nid INTEGER, did INTEGER, ord INTEGER,
            mod INTEGER, usn INTEGER, type INTEGER, queue INTEGER,
            due INTEGER, ivl INTEGER, factor INTEGER, reps INTEGER,
            lapses INTEGER, left INTEGER, odue INTEGER, odid INTEGER,
            flags INTEGER, data TEXT
        );
        CREATE TABLE revlog (
            id INTEGER PRIMARY KEY, cid INTEGER, usn INTEGER, ease INTEGER,
            ivl INTEGER, lastIvl INTEGER, factor INTEGER, time INTEGER,
            type INTEGER
        );
        CREATE TABLE graves (usn INTEGER, oid INTEGER, type INTEGER);
        CREATE TABLE notetypes (
            id INTEGER PRIMARY KEY, name TEXT, mtime_secs INTEGER,
            usn INTEGER, config BLOB
        );
        CREATE TABLE fields (
            ntid INTEGER, ord INTEGER, name TEXT, config BLOB,
            PRIMARY KEY (ntid, ord)
        );
        CREATE TABLE templates (
            ntid INTEGER, ord INTEGER, name TEXT, mtime_secs INTEGER,
            usn INTEGER, config BLOB, PRIMARY KEY (ntid, ord)
        );
        CREATE TABLE decks (
            id INTEGER PRIMARY KEY, name TEXT, mtime_secs INTEGER,
            usn INTEGER, common BLOB, kind BLOB
        );
        CREATE TABLE deck_config (
            id INTEGER PRIMARY KEY, name TEXT, mtime_secs INTEGER,
            usn INTEGER, config BLOB
        );
        CREATE TABLE tags (tag TEXT PRIMARY KEY, usn INTEGER);
    """)
    db.commit()
    db.close()


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
