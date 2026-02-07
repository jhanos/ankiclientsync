# Anki Sync Client

A Python implementation of the Anki sync protocol. Supports both AnkiWeb and custom sync servers.

## Installation

```bash
pip install requests zstandard
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
# Create virtual environment and install dependencies
uv venv .venv
uv pip install requests zstandard

# Run tests (from parent directory)
PYTHONPATH=/path/to/git .venv/bin/python -m ankiclientsync.tests.test_sync_client
```

## License

GNU AGPL, version 3 or later - http://www.gnu.org/licenses/agpl.html
