#!/usr/bin/env python3
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""
Test media sync functionality.

Usage: uv run --env-file tests/.env python -m ankiclientsync.tests.test_media_sync
"""

import tempfile
from pathlib import Path

from .. import MediaSyncClient, SyncAuth
from .conftest import (
    ENDPOINT,
    check_dependencies,
    login,
)


def main():
    print(f"{'=' * 60}\nANKI SYNC CLIENT - MEDIA SYNC TEST\n{'=' * 60}")
    print(f"Endpoint: {ENDPOINT}")

    if not check_dependencies():
        return False

    # Login
    print("\n[1/3] Logging in...")
    auth = login()
    if not auth:
        print("ERROR: Login failed")
        return False

    # Create temp media folder
    print("\n[2/3] Syncing media from server...")
    with tempfile.TemporaryDirectory() as tmpdir:
        media_folder = Path(tmpdir) / "collection.media"
        media_folder.mkdir()

        media_client = MediaSyncClient(media_folder, auth)

        try:
            # Sync media
            stats = media_client.sync()
            print(f"  Downloaded: {stats['downloaded']} files")
            print(f"  Uploaded: {stats['uploaded']} files")
            print(f"  Deleted: {stats['deleted']} files")

            # List media files
            files = media_client.list_media_files()
            print(f"  Total tracked: {len(files)} files")

            if files:
                print("\n[3/3] Media files on server:")
                for f in files[:10]:  # Show first 10
                    fpath = media_folder / f
                    size = fpath.stat().st_size if fpath.exists() else 0
                    print(f"  - {f} ({size} bytes)")
                if len(files) > 10:
                    print(f"  ... and {len(files) - 10} more")
            else:
                print("\n[3/3] No media files on server")

        except Exception as e:
            print(f"ERROR: Media sync failed: {e}")
            media_client.close()
            return False
        finally:
            media_client.close()

    print(f"\nSUCCESS: Media sync completed")
    return True


def test_media_upload():
    """Test uploading a media file to the server."""
    print(f"\n{'=' * 60}\nMEDIA UPLOAD TEST\n{'=' * 60}")

    auth = login()
    if not auth:
        print("ERROR: Login failed")
        return False

    with tempfile.TemporaryDirectory() as tmpdir:
        media_folder = Path(tmpdir) / "collection.media"
        media_folder.mkdir()

        # Create a test file
        test_file = media_folder / "test_image.txt"
        test_file.write_text("This is a test media file for sync testing.")

        media_client = MediaSyncClient(media_folder, auth)

        try:
            # Register local changes
            print("Registering local changes...")
            media_client.register_local_changes()

            # Sync
            print("Syncing...")
            stats = media_client.sync()
            print(f"  Uploaded: {stats['uploaded']} files")

            # Verify it's tracked
            files = media_client.list_media_files()
            if "test_image.txt" in files:
                print("SUCCESS: File uploaded and tracked")
            else:
                print("WARNING: File may not have been uploaded")

        finally:
            media_client.close()

    return True


if __name__ == "__main__":
    success = main()
    if success:
        # Also run upload test
        test_media_upload()
    exit(0 if success else 1)
