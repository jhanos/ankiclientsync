# AGENTS.md - Guide for AI Coding Agents

Guide for AI agents working on ankiclientsync - a Python implementation of the Anki sync protocol.

## Build and Environment

This project uses `uv` for dependency management (Python 3.10+).

```bash
uv sync                    # Install dependencies
uv pip install -e .        # Install in development mode
```

## Running Tests

All tests require environment variables from `tests/.env`:

```bash
# Run a single test file
uv run --env-file tests/.env python -m ankiclientsync.tests.test_upload

# Available test files:
uv run --env-file tests/.env python -m ankiclientsync.tests.test_upload
uv run --env-file tests/.env python -m ankiclientsync.tests.test_download
uv run --env-file tests/.env python -m ankiclientsync.tests.test_partial_sync
uv run --env-file tests/.env python -m ankiclientsync.tests.test_media_sync
```

Tests use a `TestRunner` class from `conftest.py` and each test file has a `main()` function.

## Code Style Guidelines

### License Header

Every Python file must start with:
```python
# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
```

### Imports

1. `from __future__ import annotations` (always first)
2. Standard library imports
3. Third-party imports (requests, zstandard)
4. Local imports using relative syntax

Use TYPE_CHECKING pattern for optional imports:
```python
if TYPE_CHECKING:
    import requests
else:
    try:
        import requests
    except ImportError:
        requests = None
```

### Type Hints

Use modern Python 3.10+ syntax: `str | Path`, `list[int]`, `Optional[dict]`

### Naming Conventions

- Variables/functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private: `_prefix`

### Classes

Use `@dataclass` for data-only classes, regular classes for behavior-heavy objects.

### Error Handling

Define custom exceptions inheriting from a base error:
```python
class SyncError(Exception):
    pass

class SyncRedirectError(SyncError):
    def __init__(self, new_endpoint: str):
        self.new_endpoint = new_endpoint
        super().__init__(f"Redirect to: {new_endpoint}")
```

### Resource Management

Classes holding resources must have a `close()` method.

### Database Patterns

Use sqlite3 with `Row` factory and handle transactions explicitly:
```python
db = sqlite3.connect(str(path))
db.row_factory = sqlite3.Row

def begin_transaction(self) -> None:
    self.db.execute("BEGIN IMMEDIATE")
```

### Test Structure

```python
#!/usr/bin/env python3
# [license header]
"""Description of what tests cover."""

from . import conftest

def test_feature_name() -> bool:
    """Test description."""
    return True  # or False

def main():
    runner = conftest.TestRunner()
    runner.run("Feature Name", test_feature_name)
    return runner.summary()

if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
```

## Project Structure

```
ankiclientsync/
├── __init__.py          # Package exports
├── client.py            # HTTP client, SyncClient, MediaSyncClient
├── collection.py        # SyncableCollection implementation
├── main.py              # CLI entry point
└── tests/
    ├── .env             # Server credentials (not committed)
    ├── collection.anki2 # Test fixture
    ├── conftest.py      # Shared utilities, TestRunner
    └── test_*.py        # Individual test files
```

## Key Abstractions

- `CollectionSyncInterface`: Abstract base for sync operations
- `SyncClient`: Orchestrates collection sync with server
- `MediaSyncClient`: Handles media file sync separately
- `SyncableCollection`: Concrete implementation of collection interface

## Common Patterns

### Creating a sync client
```python
from ankiclientsync import SyncClient, SyncableCollection, SyncActionRequired

auth = SyncClient.login("user", "pass", endpoint="http://localhost:8080/")
col = SyncableCollection("/path/to/collection.anki2")
client = SyncClient(col, auth)
result = client.sync()

if result.required == SyncActionRequired.FULL_SYNC:
    client.full_upload()  # or client.full_download()
```

### Adding test notes
```python
col.add_note("Front text", "Back text")
col.add_note("Question", "Answer", deck="MyDeck", front_image="/path/to/img.png")
```
