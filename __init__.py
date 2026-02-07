# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""
Anki Sync Client - Python implementation of the Anki sync protocol.

Supports both AnkiWeb and custom sync servers.

Usage:
    from anki_sync_client import SyncClient, SyncAuth, SyncActionRequired

    # Login and sync
    auth = SyncClient.login("user", "pass", endpoint="http://localhost:8080/")
    client = SyncClient(collection, auth)
    result = client.sync()

    # Full upload/download if needed
    if result.required == SyncActionRequired.FULL_SYNC:
        client.full_upload()  # or client.full_download()
"""

from .client import (
    # Auth & Config
    SyncAuth,
    DEFAULT_ENDPOINT,
    # Results
    SyncActionRequired,
    SyncOutput,
    SyncMeta,
    # Data structures
    Graves,
    Chunk,
    UnchunkedChanges,
    SanityCheckCounts,
    # Media sync
    MediaEntry,
    MediaChange,
    MediaAction,
    MediaSyncClient,
    # Exceptions
    SyncError,
    SyncRedirectError,
    SanityCheckFailedError,
    # Clients
    HttpSyncClient,
    SyncClient,
    # Interface
    CollectionSyncInterface,
)
from .collection import SyncableCollection

__all__ = [
    "SyncAuth",
    "DEFAULT_ENDPOINT",
    "SyncActionRequired",
    "SyncOutput",
    "SyncMeta",
    "Graves",
    "Chunk",
    "UnchunkedChanges",
    "SanityCheckCounts",
    "MediaEntry",
    "MediaChange",
    "MediaAction",
    "MediaSyncClient",
    "SyncError",
    "SyncRedirectError",
    "SanityCheckFailedError",
    "HttpSyncClient",
    "SyncClient",
    "CollectionSyncInterface",
    "SyncableCollection",
]

__version__ = "1.0.0"
