# Anki Sync Client

A Python implementation of the Anki sync protocol. Supports both AnkiWeb and custom sync servers.

## Installation

```bash
pip install "git+https://github.com/jhanos/ankiclientsync.git"
```

## Usage

### Login and Sync

```python
from ankiclientsync import SyncClient, SyncActionRequired

# Login to get authentication credentials
auth = SyncClient.login("username", "password", endpoint="http://localhost:8080/")

# Create sync client with your collection
client = SyncClient(collection, auth)

# Perform sync
result = client.sync()

# Handle full sync if required
if result.required == SyncActionRequired.FULL_SYNC:
    client.full_upload()   # Upload local to server
    # or
    client.full_download() # Download server to local
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

# Run download tests (download, modify, and re-upload)
uv run --env-file tests/.env python -m ankiclientsync.tests.test_download

# Run partial sync tests (sync with server, modify, and re-sync)
uv run --env-file tests/.env python -m ankiclientsync.tests.test_partial_sync
```

You can customize the test configuration by editing `tests/.env`:

```bash
ANKI_ENDPOINT=http://localhost:8080/
ANKI_USERNAME=user
ANKI_PASSWORD=pass
```

## License

GNU AGPL, version 3 or later - http://www.gnu.org/licenses/agpl.html
