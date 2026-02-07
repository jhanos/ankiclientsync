# Anki Sync Client

A Python implementation of the Anki sync protocol. Supports both AnkiWeb and custom sync servers.

## Features

- **Collection Sync**: Full upload/download and incremental (partial) sync
- **Media Sync**: Download and upload media files (images, audio, etc.)
- **Export to .apkg**: Export collections to Anki package files with optional media
- **Import from .apkg**: Import Anki packages to create or merge collections

## Installation

```bash
pip install "git+https://github.com/jhanos/ankiclientsync.git"
```

## Usage

### Login and Sync

```python
from ankiclientsync import SyncClient, SyncableCollection, SyncActionRequired

# Login to get authentication credentials
auth = SyncClient.login("username", "password", endpoint="http://localhost:8080/")

# Create sync client with your collection
col = SyncableCollection("/path/to/collection.anki2")
client = SyncClient(col, auth)

# Perform sync
result = client.sync()

# Handle full sync if required
if result.required == SyncActionRequired.FULL_SYNC:
    client.full_upload()   # Upload local to server
    # or
    client.full_download() # Download server to local

col.close()
client.close()
```

### Media Sync

```python
from ankiclientsync import SyncClient, MediaSyncClient
from pathlib import Path

# Login
auth = SyncClient.login("username", "password", endpoint="http://localhost:8080/")

# Sync media files
media_folder = Path("/path/to/collection.media")
media = MediaSyncClient(media_folder, auth)

# Download all media from server
stats = media.sync()
print(f"Downloaded: {stats['downloaded']}, Uploaded: {stats['uploaded']}")

# To upload local changes, first register them
media.register_local_changes()
stats = media.sync()

media.close()
```

### Export to .apkg

Export your collection to an Anki package file that can be imported into Anki:

```python
from ankiclientsync import SyncableCollection

col = SyncableCollection("/path/to/collection.anki2")

# Basic export (without media)
col.export_anki_package("/path/to/output.apkg")

# Export with scheduling data (review history, intervals, etc.)
col.export_anki_package("/path/to/output.apkg", with_scheduling=True)

# Export without scheduling (cards reset to new)
col.export_anki_package("/path/to/output.apkg", with_scheduling=False)

# Export with media files
col.export_anki_package("/path/to/output.apkg", with_media=True)

# Export a specific deck only
deck_id = 1234567890  # Get deck ID from the database
col.export_anki_package("/path/to/deck.apkg", deck_id=deck_id)

# Export in legacy format (for older Anki versions)
col.export_anki_package("/path/to/output.apkg", legacy=True)

col.close()
```

### Import from .apkg

Import an Anki package file to create a new collection or merge into an existing one:

```python
from ankiclientsync import SyncClient, SyncableCollection

# Method 1: Create a new collection from .apkg
col = SyncableCollection.from_apkg("/path/to/deck.apkg", "/path/to/output/")
print(f"Imported {col.count('notes')} notes")

# Upload to sync server
auth = SyncClient.login("user", "pass", endpoint="http://localhost:8080/")
client = SyncClient(col, auth)
client.full_upload()

col.close()
client.close()
```

```python
# Method 2: Merge .apkg into existing collection
col = SyncableCollection("/path/to/existing/collection.anki2")

stats = col.import_apkg("/path/to/deck.apkg")
print(f"Imported: {stats['notes']} notes, {stats['cards']} cards")
print(f"Added: {stats['notetypes']} notetypes, {stats['decks']} decks")

# Sync changes to server
client = SyncClient(col, auth)
client.sync()  # or client.full_upload()

col.close()
```

### Full Example: Download and Export

```python
from ankiclientsync import SyncClient, SyncableCollection, MediaSyncClient
from pathlib import Path
import tempfile

# Login
auth = SyncClient.login("user", "pass", endpoint="http://localhost:8080/")

# Setup paths
work_dir = Path(tempfile.mkdtemp())
col_path = work_dir / "collection.anki2"
media_folder = work_dir / "collection.media"
media_folder.mkdir()

# Create empty collection and download from server
# (You need to create the initial database schema first)
col = SyncableCollection(col_path, media_folder=media_folder)
client = SyncClient(col, auth)
client.full_download()

# Download media
media = MediaSyncClient(media_folder, auth)
media.sync()
media.close()

# Export to .apkg with media
output_path = work_dir / "my_collection.apkg"
notes_exported = col.export_anki_package(output_path, with_media=True)
print(f"Exported {notes_exported} notes to {output_path}")

col.close()
client.close()
```

## Running Tests

### Requirement: Start a local Anki sync server

The test suite requires a running Anki sync server:
- Sync server running on `localhost:8080`
- Credentials: `user` / `pass`

```
mkdir ankiserversync
cd ankiserversync
uv init .
uv add anki
echo "SYNC_USER1=user:pass" > .env
uv run --env-file .env python -m anki.syncserver
```

### Run tests

```bash
# Run upload tests (upload local collection to server)
uv run --env-file tests/.env python -m ankiclientsync.tests.test_upload

# Run download and export tests
uv run --env-file tests/.env python -m ankiclientsync.tests.test_download

# Run partial sync tests (sync with server, modify, and re-sync)
uv run --env-file tests/.env python -m ankiclientsync.tests.test_partial_sync

# Run media sync tests
uv run --env-file tests/.env python -m ankiclientsync.tests.test_media_sync

# Run import tests
uv run --env-file tests/.env python -m ankiclientsync.tests.test_import
```

You can customize the test configuration by editing `tests/.env`:

```bash
ANKI_ENDPOINT=http://localhost:8080/
ANKI_USERNAME=user
ANKI_PASSWORD=pass
```

## API Reference

### SyncableCollection

| Method | Description |
|--------|-------------|
| `from_apkg(apkg_path, output_dir, extract_media=True)` | Class method: Create collection from .apkg |
| `import_apkg(apkg_path, import_media=True, merge_notetypes=True)` | Merge .apkg into existing collection |
| `export_anki_package(out_path, deck_id=None, with_scheduling=True, with_media=False, legacy=False)` | Export to .apkg file |
| `sync_meta()` | Get sync metadata |
| `count(table)` | Count rows in a table |
| `add_note(front, back, notetype="Basic")` | Add a note |
| `close()` | Close the database connection |

### MediaSyncClient

| Method | Description |
|--------|-------------|
| `sync(full_download=False)` | Sync media with server |
| `register_local_changes()` | Scan folder for local changes |
| `list_media_files()` | List tracked media files |
| `close()` | Close connections |

## License

GNU AGPL, version 3 or later - http://www.gnu.org/licenses/agpl.html
