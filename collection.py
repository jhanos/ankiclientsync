# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""
SyncableCollection - A collection implementation that supports partial sync.

This module provides a concrete implementation of CollectionSyncInterface
that can perform incremental (partial) syncs with an Anki sync server.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .client import (
    CHUNK_SIZE,
    Chunk,
    CollectionSyncInterface,
    Graves,
    SanityCheckCounts,
    SyncMeta,
    UnchunkedChanges,
)

# Unicase collation for Anki compatibility
_unicase = lambda x, y: (x.lower() > y.lower()) - (x.lower() < y.lower())


# -------------------------------------------------------------------------
# Protobuf Helpers (minimal parsing for Anki's protobuf format)
# -------------------------------------------------------------------------


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Read a varint from bytes, return (value, new_position)."""
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _parse_protobuf_fields(data: bytes) -> dict[int, list]:
    """
    Parse protobuf wire format into a dict of field_number -> list of values.
    Only handles LEN (type 2) and VARINT (type 0) wire types.
    """
    fields: dict[int, list] = {}
    pos = 0
    while pos < len(data):
        if pos >= len(data):
            break
        tag, pos = _read_varint(data, pos)
        field_num = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:  # VARINT
            val, pos = _read_varint(data, pos)
            fields.setdefault(field_num, []).append(val)
        elif wire_type == 2:  # LEN (length-delimited: string, bytes, embedded message)
            length, pos = _read_varint(data, pos)
            val = data[pos : pos + length]
            pos += length
            fields.setdefault(field_num, []).append(val)
        elif wire_type == 5:  # I32 (32-bit)
            val = int.from_bytes(data[pos : pos + 4], "little")
            pos += 4
            fields.setdefault(field_num, []).append(val)
        elif wire_type == 1:  # I64 (64-bit)
            val = int.from_bytes(data[pos : pos + 8], "little")
            pos += 8
            fields.setdefault(field_num, []).append(val)
        else:
            # Unknown wire type, skip rest
            break
    return fields


def _get_str(fields: dict, num: int, default: str = "") -> str:
    """Get string field from parsed protobuf."""
    vals = fields.get(num, [])
    if vals and isinstance(vals[0], bytes):
        return vals[0].decode("utf-8", errors="replace")
    return default


def _get_int(fields: dict, num: int, default: int = 0) -> int:
    """Get int field from parsed protobuf."""
    vals = fields.get(num, [])
    if vals and isinstance(vals[0], int):
        return vals[0]
    return default


# -------------------------------------------------------------------------
# Protobuf Encoding Helpers
# -------------------------------------------------------------------------


def _encode_varint(value: int) -> bytes:
    """Encode an integer as a varint."""
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value)
    return bytes(parts) if parts else b"\x00"


def _encode_field(field_num: int, wire_type: int, value: bytes) -> bytes:
    """Encode a protobuf field."""
    tag = (field_num << 3) | wire_type
    return _encode_varint(tag) + value


def _encode_string(field_num: int, value: str) -> bytes:
    """Encode a string field (LEN wire type = 2)."""
    encoded = value.encode("utf-8")
    return _encode_field(field_num, 2, _encode_varint(len(encoded)) + encoded)


def _encode_bytes(field_num: int, value: bytes) -> bytes:
    """Encode a bytes/message field (LEN wire type = 2)."""
    return _encode_field(field_num, 2, _encode_varint(len(value)) + value)


def _encode_varint_field(field_num: int, value: int) -> bytes:
    """Encode a varint field (wire type = 0)."""
    return _encode_field(field_num, 0, _encode_varint(value))


def _connect_db(path: Path) -> sqlite3.Connection:
    """Connect to collection DB with required collation."""
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    db.create_collation("unicase", _unicase)
    return db


class SyncableCollection(CollectionSyncInterface):
    """
    A collection implementation that supports both full and partial sync.

    This class wraps an Anki collection database and implements all the
    methods required for incremental syncing with a sync server.

    Usage:
        col = SyncableCollection("/path/to/collection.anki2")
        client = SyncClient(col, auth)
        result = client.sync()  # Performs partial sync if possible
    """

    def __init__(self, col_path: str | Path, work_dir: Optional[Path] = None):
        """
        Initialize the syncable collection.

        Args:
            col_path: Path to the collection.anki2 file
            work_dir: Optional working directory. If provided, the collection
                      is copied there for sync operations.
        """
        self.original_path = Path(col_path)

        if work_dir:
            self.db_path = work_dir / "collection.anki2"
            shutil.copy(self.original_path, self.db_path)
        else:
            self.db_path = self.original_path

        self.db = _connect_db(self.db_path)
        self._in_transaction = False

    def close(self):
        """Close the database connection."""
        try:
            self.db.close()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Sync Metadata
    # -------------------------------------------------------------------------

    def sync_meta(self) -> SyncMeta:
        """Get local sync metadata."""
        c = self.db.cursor()
        c.execute("SELECT mod, scm, usn FROM col WHERE id = 1")
        row = c.fetchone()
        mod, scm, usn = row if row else (0, 0, 0)

        c.execute("SELECT 1 FROM cards LIMIT 1")
        empty = c.fetchone() is None

        return SyncMeta(modified=mod, schema=scm, usn=usn, empty=empty)

    # -------------------------------------------------------------------------
    # Transaction Management
    # -------------------------------------------------------------------------

    def begin_transaction(self) -> None:
        """Begin a database transaction."""
        self.db.execute("BEGIN IMMEDIATE")
        self._in_transaction = True

    def commit_transaction(self) -> None:
        """Commit the current transaction."""
        self.db.commit()
        self._in_transaction = False

    def rollback_transaction(self) -> None:
        """Rollback the current transaction."""
        self.db.rollback()
        self._in_transaction = False

    # -------------------------------------------------------------------------
    # Graves (Deletions)
    # -------------------------------------------------------------------------

    def get_pending_graves(self, pending_usn: int) -> Graves:
        """Get items deleted locally that need to be synced to server."""
        graves = Graves()

        # Items with usn = -1 are pending sync
        for row in self.db.execute("SELECT oid, type FROM graves WHERE usn = -1"):
            oid, typ = row["oid"], row["type"]
            if typ == 0:  # Card
                graves.cards.append(oid)
            elif typ == 1:  # Note
                graves.notes.append(oid)
            elif typ == 2:  # Deck
                graves.decks.append(oid)

        return graves

    def update_pending_grave_usns(self, server_usn: int) -> None:
        """Update USN for pending graves after they've been sent to server."""
        self.db.execute("UPDATE graves SET usn = ? WHERE usn = -1", (server_usn,))

    def apply_graves(self, graves: Graves, latest_usn: int) -> None:
        """Apply deletions received from server."""
        # Delete cards
        for cid in graves.cards:
            self.db.execute("DELETE FROM cards WHERE id = ?", (cid,))

        # Delete notes (and their cards)
        for nid in graves.notes:
            self.db.execute("DELETE FROM cards WHERE nid = ?", (nid,))
            self.db.execute("DELETE FROM notes WHERE id = ?", (nid,))

        # Delete decks
        for did in graves.decks:
            self.db.execute("DELETE FROM decks WHERE id = ?", (did,))

    # -------------------------------------------------------------------------
    # Unchunked Changes (Notetypes, Decks, Tags, Config)
    # -------------------------------------------------------------------------

    def get_local_unchunked_changes(
        self, pending_usn: int, server_usn: int, local_is_newer: bool
    ) -> UnchunkedChanges:
        """Get local changes to notetypes, decks, tags, and config.

        Also updates USN in database to server_usn for items being sent.
        """
        changes = UnchunkedChanges()

        # Notetypes (models) with pending changes (usn = -1)
        pending_ntids = [
            row["id"]
            for row in self.db.execute("SELECT id FROM notetypes WHERE usn = -1")
        ]
        if pending_ntids:
            # Update USN in database
            self.db.execute(
                f"UPDATE notetypes SET usn = ? WHERE id IN ({','.join('?' * len(pending_ntids))})",
                [server_usn] + pending_ntids,
            )
            # Get data with updated USN
            for ntid in pending_ntids:
                nt = self._get_notetype_dict(ntid)
                if nt:
                    nt["usn"] = server_usn
                    changes.notetypes.append(nt)

        # Decks with pending changes
        pending_dids = [
            row["id"] for row in self.db.execute("SELECT id FROM decks WHERE usn = -1")
        ]
        if pending_dids:
            # Update USN in database
            self.db.execute(
                f"UPDATE decks SET usn = ? WHERE id IN ({','.join('?' * len(pending_dids))})",
                [server_usn] + pending_dids,
            )
            # Get data with updated USN
            for did in pending_dids:
                deck = self._get_deck_dict(did)
                if deck:
                    deck["usn"] = server_usn
                    changes.decks.append(deck)

        # Deck configs with pending changes
        pending_dcids = [
            row["id"]
            for row in self.db.execute("SELECT id FROM deck_config WHERE usn = -1")
        ]
        if pending_dcids:
            # Update USN in database
            self.db.execute(
                f"UPDATE deck_config SET usn = ? WHERE id IN ({','.join('?' * len(pending_dcids))})",
                [server_usn] + pending_dcids,
            )
            # Get data with updated USN
            for dcid in pending_dcids:
                dconf = self._get_deck_config_dict(dcid)
                if dconf:
                    dconf["usn"] = server_usn
                    changes.deck_config.append(dconf)

        # Tags with pending changes
        pending_tags = [
            row["tag"] for row in self.db.execute("SELECT tag FROM tags WHERE usn = -1")
        ]
        if pending_tags:
            # Update USN in database
            self.db.execute("UPDATE tags SET usn = ? WHERE usn = -1", (server_usn,))
            changes.tags = pending_tags

        # Config if modified
        if local_is_newer:
            row = self.db.execute("SELECT conf FROM col WHERE id = 1").fetchone()
            if row and row["conf"]:
                changes.config = json.loads(row["conf"])

        return changes

    def apply_unchunked_changes(
        self, changes: UnchunkedChanges, latest_usn: int
    ) -> None:
        """Apply unchunked changes received from server."""
        # Apply notetypes
        for nt in changes.notetypes:
            self._apply_notetype(nt, latest_usn)

        # Apply decks
        for deck in changes.decks:
            self._apply_deck(deck, latest_usn)

        # Apply deck configs
        for dconf in changes.deck_config:
            self._apply_deck_config(dconf, latest_usn)

        # Apply tags
        for tag in changes.tags:
            self._apply_tag(tag, latest_usn)

        # Apply config
        if changes.config is not None:
            self.db.execute(
                "UPDATE col SET conf = ? WHERE id = 1", (json.dumps(changes.config),)
            )

        # Update creation stamp if provided
        if changes.creation_stamp is not None:
            self.db.execute(
                "UPDATE col SET crt = ? WHERE id = 1", (changes.creation_stamp,)
            )

    # -------------------------------------------------------------------------
    # Chunked Changes (Notes, Cards, Revlog)
    # -------------------------------------------------------------------------

    def get_chunkable_ids(self, pending_usn: int) -> dict:
        """Get IDs of items with pending changes to send to server."""
        ids = {"notes": [], "cards": [], "revlog": []}

        # Notes with usn = -1
        for row in self.db.execute("SELECT id FROM notes WHERE usn = -1"):
            ids["notes"].append(row["id"])

        # Cards with usn = -1
        for row in self.db.execute("SELECT id FROM cards WHERE usn = -1"):
            ids["cards"].append(row["id"])

        # Revlog with usn = -1
        for row in self.db.execute("SELECT id FROM revlog WHERE usn = -1"):
            ids["revlog"].append(row["id"])

        return ids

    def get_chunk(self, ids: dict, server_usn: Optional[int]) -> Chunk:
        """Get a chunk of changes to send to server."""
        chunk = Chunk()
        remaining = CHUNK_SIZE

        # Process notes
        while ids["notes"] and remaining > 0:
            nid = ids["notes"].pop()
            note_data = self._get_note_for_sync(nid)
            if note_data:
                # Update USN in the data we send
                if server_usn is not None:
                    note_data[4] = server_usn  # USN is at index 4
                    self.db.execute(
                        "UPDATE notes SET usn = ? WHERE id = ?", (server_usn, nid)
                    )
                chunk.notes.append(note_data)
                remaining -= 1

        # Process cards
        while ids["cards"] and remaining > 0:
            cid = ids["cards"].pop()
            card_data = self._get_card_for_sync(cid)
            if card_data:
                # Update USN in the data we send
                if server_usn is not None:
                    card_data[5] = server_usn  # USN is at index 5
                    self.db.execute(
                        "UPDATE cards SET usn = ? WHERE id = ?", (server_usn, cid)
                    )
                chunk.cards.append(card_data)
                remaining -= 1

        # Process revlog
        while ids["revlog"] and remaining > 0:
            rid = ids["revlog"].pop()
            revlog_data = self._get_revlog_for_sync(rid)
            if revlog_data:
                # Update USN in the data we send
                if server_usn is not None:
                    revlog_data["usn"] = server_usn
                    self.db.execute(
                        "UPDATE revlog SET usn = ? WHERE id = ?", (server_usn, rid)
                    )
                chunk.revlog.append(revlog_data)
                remaining -= 1

        # Mark done if no more items
        chunk.done = not (ids["notes"] or ids["cards"] or ids["revlog"])

        return chunk

    def apply_chunk(self, chunk: Chunk, pending_usn: int) -> None:
        """Apply a chunk of changes received from server."""
        # Apply notes
        for note_data in chunk.notes:
            self._apply_note(note_data)

        # Apply cards
        for card_data in chunk.cards:
            self._apply_card(card_data)

        # Apply revlog
        for revlog_data in chunk.revlog:
            self._apply_revlog(revlog_data)

    # -------------------------------------------------------------------------
    # Sanity Check and Finalization
    # -------------------------------------------------------------------------

    def get_sanity_check_counts(self) -> SanityCheckCounts:
        """Get counts for sanity check verification."""
        return SanityCheckCounts(
            cards=self._count("cards"),
            notes=self._count("notes"),
            revlog=self._count("revlog"),
            graves=self._count("graves"),
            notetypes=self._count("notetypes"),
            decks=self._count("decks"),
            deck_config=self._count("deck_config"),
        )

    def finalize_sync(self, server_usn: int, new_mtime: int) -> None:
        """Finalize sync by updating local USN and modification time."""
        self.db.execute(
            "UPDATE col SET usn = ?, mod = ? WHERE id = 1", (server_usn, new_mtime)
        )

    def set_schema_modified(self) -> None:
        """Mark schema as modified (forces full sync next time)."""
        self.db.execute(
            "UPDATE col SET scm = ? WHERE id = 1", (int(time.time() * 1000),)
        )

    # -------------------------------------------------------------------------
    # Full Sync Support
    # -------------------------------------------------------------------------

    def get_collection_path(self) -> Path:
        """Get path to collection file."""
        return self.db_path

    def close_for_full_upload(self) -> bytes:
        """Close database and return contents for upload."""
        self.db.close()
        return self.db_path.read_bytes()

    def replace_with_full_download(self, data: bytes) -> None:
        """Replace collection with downloaded data."""
        self.db.close()
        self.db_path.write_bytes(data)
        self.db = _connect_db(self.db_path)

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _count(self, table: str) -> int:
        """Count rows in a table."""
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def _get_notetype_dict(self, ntid: int) -> Optional[dict]:
        """Get notetype as dict for sync protocol (JSON format)."""
        row = self.db.execute(
            "SELECT id, name, mtime_secs, usn, config FROM notetypes WHERE id = ?",
            (ntid,),
        ).fetchone()
        if not row:
            return None

        # Parse notetype config protobuf
        nt_config = row["config"]
        nt_fields = _parse_protobuf_fields(nt_config) if nt_config else {}

        # Get CSS from field 3 of notetype config
        css = _get_str(nt_fields, 3, "")

        # Get fields
        fields = []
        for frow in self.db.execute(
            "SELECT name, ord, config FROM fields WHERE ntid = ? ORDER BY ord", (ntid,)
        ):
            fld_config = frow["config"]
            fld_fields = _parse_protobuf_fields(fld_config) if fld_config else {}

            # Extract field properties from protobuf
            # Field 3 = font, Field 4 = size
            font = _get_str(fld_fields, 3, "Arial")
            size = _get_int(fld_fields, 4, 20)

            fields.append(
                {
                    "name": frow["name"],
                    "ord": frow["ord"],
                    "font": font,
                    "size": size,
                }
            )

        # Get templates
        tmpls = []
        for trow in self.db.execute(
            "SELECT name, ord, config FROM templates WHERE ntid = ? ORDER BY ord",
            (ntid,),
        ):
            tmpl_config = trow["config"]
            tmpl_fields = _parse_protobuf_fields(tmpl_config) if tmpl_config else {}

            # Field 1 = qfmt, Field 2 = afmt
            qfmt = _get_str(tmpl_fields, 1, "")
            afmt = _get_str(tmpl_fields, 2, "")

            tmpls.append(
                {
                    "name": trow["name"],
                    "ord": trow["ord"],
                    "qfmt": qfmt,
                    "afmt": afmt,
                }
            )

        # Build the sync format dict
        return {
            "id": row["id"],
            "name": row["name"],
            "mod": row["mtime_secs"],
            "usn": row["usn"],
            "flds": fields,
            "tmpls": tmpls,
            "css": css,
            "type": 0,  # Standard notetype
        }

    def _apply_notetype(self, nt: dict, usn: int) -> None:
        """Apply a notetype from server (JSON sync format -> protobuf storage)."""
        ntid = nt["id"]

        # Build notetype config protobuf
        # Field 3 = css
        nt_config = b""
        if css := nt.get("css", ""):
            nt_config += _encode_string(3, css)

        # Insert or update notetype
        self.db.execute(
            """INSERT OR REPLACE INTO notetypes (id, name, mtime_secs, usn, config)
               VALUES (?, ?, ?, ?, ?)""",
            (ntid, nt["name"], nt.get("mod", 0), usn, nt_config),
        )

        # Update fields
        self.db.execute("DELETE FROM fields WHERE ntid = ?", (ntid,))
        for fld in nt.get("flds", []):
            # Build field config protobuf
            # Field 3 = font, Field 4 = size
            fld_config = b""
            if font := fld.get("font", "Arial"):
                fld_config += _encode_string(3, font)
            if size := fld.get("size", 20):
                fld_config += _encode_varint_field(4, size)

            self.db.execute(
                "INSERT INTO fields (ntid, name, ord, config) VALUES (?, ?, ?, ?)",
                (ntid, fld["name"], fld.get("ord", 0), fld_config),
            )

        # Update templates
        self.db.execute("DELETE FROM templates WHERE ntid = ?", (ntid,))
        for tmpl in nt.get("tmpls", []):
            # Build template config protobuf
            # Field 1 = qfmt, Field 2 = afmt
            tmpl_config = b""
            if qfmt := tmpl.get("qfmt", ""):
                tmpl_config += _encode_string(1, qfmt)
            if afmt := tmpl.get("afmt", ""):
                tmpl_config += _encode_string(2, afmt)

            self.db.execute(
                "INSERT INTO templates (ntid, name, ord, mtime_secs, usn, config) VALUES (?, ?, ?, 0, ?, ?)",
                (ntid, tmpl["name"], tmpl.get("ord", 0), usn, tmpl_config),
            )

    def _get_deck_dict(self, did: int) -> Optional[dict]:
        """Get deck as dict for sync protocol (JSON format)."""
        row = self.db.execute(
            "SELECT id, name, mtime_secs, usn, common, kind FROM decks WHERE id = ?",
            (did,),
        ).fetchone()
        if not row:
            return None

        # Parse protobuf common and kind fields
        common = row["common"]
        kind = row["kind"]
        common_fields = _parse_protobuf_fields(common) if common else {}
        kind_fields = _parse_protobuf_fields(kind) if kind else {}

        # Check if this is a filtered deck (kind field 2 has data) or normal
        is_filtered = bool(kind_fields.get(2))

        # Extract deck config id from NormalDeck (field 1 of kind)
        conf_id = 1
        if not is_filtered:
            normal_data = kind_fields.get(1, [b""])[0]
            if isinstance(normal_data, bytes) and normal_data:
                normal_fields = _parse_protobuf_fields(normal_data)
                conf_id = _get_int(normal_fields, 1, 1)

        # Build deck dict in sync format with all required fields
        return {
            "id": row["id"],
            "name": row["name"],
            "mod": row["mtime_secs"],
            "usn": row["usn"],
            "conf": conf_id,
            "dyn": 1 if is_filtered else 0,
            "desc": "",
            "collapsed": False,
            "browserCollapsed": False,
            "newToday": [0, 0],
            "revToday": [0, 0],
            "lrnToday": [0, 0],
            "timeToday": [0, 0],
            "extendNew": 0,
            "extendRev": 0,
        }

    def _apply_deck(self, deck: dict, usn: int) -> None:
        """Apply a deck from server (JSON sync format -> protobuf storage)."""
        # Build common protobuf (minimal - just enough to not break)
        # Field 1 = study_collapsed, Field 2 = browser_collapsed
        common = _encode_varint_field(1, 1) + _encode_varint_field(2, 1)

        # Build kind protobuf
        # For normal deck: field 1 = NormalDeck { field 1 = config_id }
        # For filtered deck: field 2 = FilteredDeck (complex)
        is_filtered = deck.get("dyn", 0) == 1
        if is_filtered:
            # Filtered deck - just create empty FilteredDeck
            kind = _encode_bytes(2, b"")
        else:
            # Normal deck - config_id in NormalDeck
            conf_id = deck.get("conf", 1)
            normal_deck = _encode_varint_field(1, conf_id)
            kind = _encode_bytes(1, normal_deck)

        self.db.execute(
            """INSERT OR REPLACE INTO decks (id, name, mtime_secs, usn, common, kind)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                deck["id"],
                deck["name"],
                deck.get("mod", 0),
                usn,
                common,
                kind,
            ),
        )

    def _get_deck_config_dict(self, dcid: int) -> Optional[dict]:
        """Get deck config as dict for sync protocol (JSON format)."""
        row = self.db.execute(
            "SELECT id, name, mtime_secs, usn, config FROM deck_config WHERE id = ?",
            (dcid,),
        ).fetchone()
        if not row:
            return None

        # The config is protobuf, but for sync we need the legacy JSON format
        # For now, return minimal required fields - the server will merge
        config = row["config"]
        cfg_fields = _parse_protobuf_fields(config) if config else {}

        # Build deck config in sync format (legacy JSON)
        # The full format has many fields, we extract what we can
        return {
            "id": row["id"],
            "name": row["name"],
            "mod": row["mtime_secs"],
            "usn": row["usn"],
            # Minimal config - most values will use defaults
            "new": {"perDay": 20},
            "rev": {"perDay": 200},
            "lapse": {},
            "dyn": False,
        }

    def _apply_deck_config(self, dconf: dict, usn: int) -> None:
        """Apply a deck config from server (JSON sync format -> protobuf storage)."""
        # Build minimal deck config protobuf
        # This is complex, but we can create a basic config that Anki can use
        # For now, create an empty protobuf - Anki will use defaults
        config = b""

        self.db.execute(
            """INSERT OR REPLACE INTO deck_config (id, name, mtime_secs, usn, config)
               VALUES (?, ?, ?, ?, ?)""",
            (
                dconf["id"],
                dconf["name"],
                dconf.get("mod", 0),
                usn,
                config,
            ),
        )

    def _apply_tag(self, tag: str, usn: int) -> None:
        """Apply a tag from server."""
        self.db.execute(
            "INSERT OR REPLACE INTO tags (tag, usn) VALUES (?, ?)", (tag, usn)
        )

    def _get_note_for_sync(self, nid: int) -> Optional[list]:
        """Get note data as list for sync protocol.

        Note: sfld and csum are always empty strings in sync protocol,
        they are only used locally.
        """
        row = self.db.execute(
            "SELECT id, guid, mid, mod, usn, tags, flds, flags, data FROM notes WHERE id = ?",
            (nid,),
        ).fetchone()
        if not row:
            return None

        return [
            row["id"],
            row["guid"],
            row["mid"],
            row["mod"],
            row["usn"],  # Will be updated to server_usn in get_chunk
            row["tags"],
            row["flds"],
            "",  # sfld - always empty in sync protocol
            "",  # csum - always empty string in sync protocol
            row["flags"],
            row["data"],
        ]

    def _apply_note(self, note_data: list) -> None:
        """Apply note data from server."""
        # note_data format: [id, guid, mid, mod, usn, tags, flds, sfld, csum, flags, data]
        self.db.execute(
            """INSERT OR REPLACE INTO notes 
               (id, guid, mid, mod, usn, tags, flds, sfld, csum, flags, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(note_data),
        )

    def _get_card_for_sync(self, cid: int) -> Optional[list]:
        """Get card data as list for sync protocol."""
        row = self.db.execute(
            """SELECT id, nid, did, ord, mod, usn, type, queue, due, ivl, 
                      factor, reps, lapses, left, odue, odid, flags, data 
               FROM cards WHERE id = ?""",
            (cid,),
        ).fetchone()
        if not row:
            return None

        return list(row)

    def _apply_card(self, card_data: list) -> None:
        """Apply card data from server."""
        # card_data format: [id, nid, did, ord, mod, usn, type, queue, due, ivl,
        #                    factor, reps, lapses, left, odue, odid, flags, data]
        self.db.execute(
            """INSERT OR REPLACE INTO cards 
               (id, nid, did, ord, mod, usn, type, queue, due, ivl,
                factor, reps, lapses, left, odue, odid, flags, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(card_data),
        )

    def _get_revlog_for_sync(self, rid: int) -> Optional[dict]:
        """Get revlog entry as dict for sync protocol."""
        row = self.db.execute(
            """SELECT id, cid, usn, ease, ivl, lastIvl, factor, time, type
               FROM revlog WHERE id = ?""",
            (rid,),
        ).fetchone()
        if not row:
            return None

        return {
            "id": row["id"],
            "cid": row["cid"],
            "usn": row["usn"],
            "ease": row["ease"],
            "ivl": row["ivl"],
            "lastIvl": row["lastIvl"],
            "factor": row["factor"],
            "time": row["time"],
            "type": row["type"],
        }

    def _apply_revlog(self, revlog_data: dict) -> None:
        """Apply revlog entry from server."""
        self.db.execute(
            """INSERT OR REPLACE INTO revlog 
               (id, cid, usn, ease, ivl, lastIvl, factor, time, type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                revlog_data["id"],
                revlog_data["cid"],
                revlog_data["usn"],
                revlog_data["ease"],
                revlog_data["ivl"],
                revlog_data["lastIvl"],
                revlog_data["factor"],
                revlog_data["time"],
                revlog_data["type"],
            ),
        )

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def count(self, table: str) -> int:
        """Public method to count rows in a table."""
        return self._count(table)

    def add_note(self, front: str, back: str, notetype: str = "Basic") -> int:
        """Add a note with a card. Returns note ID."""
        import random
        import string
        import zlib

        note_id = int(time.time() * 1000)
        mod = int(time.time())
        guid = "".join(random.choices(string.ascii_letters + string.digits, k=10))

        # Get notetype ID
        row = self.db.execute(
            "SELECT id FROM notetypes WHERE name = ? LIMIT 1", (notetype,)
        ).fetchone()
        if not row:
            raise ValueError(f"Notetype '{notetype}' not found")
        mid = row[0]

        csum = zlib.crc32(front.encode()) & 0xFFFFFFFF
        flds = f"{front}\x1f{back}"

        # Insert note with usn=-1 (pending sync)
        self.db.execute(
            """INSERT INTO notes (id, guid, mid, mod, usn, tags, flds, sfld, csum, flags, data)
               VALUES (?, ?, ?, ?, -1, '', ?, ?, ?, 0, '')""",
            (note_id, guid, mid, mod, flds, front, csum),
        )

        # Insert card with usn=-1 (pending sync)
        card_id = note_id + 1
        self.db.execute(
            """INSERT INTO cards (id, nid, did, ord, mod, usn, type, queue, due, ivl,
                                  factor, reps, lapses, left, odue, odid, flags, data)
               VALUES (?, ?, 1, 0, ?, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, '')""",
            (card_id, note_id, mod),
        )

        # Update collection modification time
        self.db.execute("UPDATE col SET mod = ? WHERE id = 1", (mod * 1000,))
        self.db.commit()

        return note_id
