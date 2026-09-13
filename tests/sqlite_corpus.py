"""Generate SQLite corpus via the stdlib sqlite3 module."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def build_all(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    p = out / "demo.sqlite"
    p.unlink(missing_ok=True)
    con = sqlite3.connect(p)
    cur = con.cursor()
    cur.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, score REAL)")
    cur.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    cur.execute("CREATE INDEX idx_users_name ON users(name)")
    for i in range(200):
        cur.execute("INSERT INTO users VALUES (?, ?, ?)", (i, f"user{i:03d}", i * 1.5))
    for i in range(50):
        cur.execute("INSERT INTO notes VALUES (?, ?)", (i, f"note body {i} " + "x" * 60))
    cur.execute("DELETE FROM notes WHERE id % 2 = 0")   # create free pages
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()

    # corrupt: flip magic
    raw = bytearray(p.read_bytes())
    raw[0] = 0x00
    (out / "corrupt").mkdir(exist_ok=True)
    (out / "corrupt/bad_magic.sqlite").write_bytes(bytes(raw))
    # corrupt: truncate mid-file
    (out / "corrupt/truncated.sqlite").write_bytes(p.read_bytes()[: p.stat().st_size // 3])


if __name__ == "__main__":
    build_all(Path(__file__).resolve().parents[1] / "samples" / "sqlite")
    print("sqlite corpus written")
