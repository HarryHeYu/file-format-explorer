"""SQLite database parser.

Parses the 100-byte database header and classifies every page (table/index
B-tree interior & leaf, freelist trunk, overflow). Decodes the sqlite_schema
table on page 1 so each schema object (table/index) links to its root page.
Bounds-checked everywhere; a corrupted database yields error nodes, not
exceptions.
"""
from __future__ import annotations

import struct

from ..core.datasource import DataSource
from ..core.model import Node, ParseResult
from ..core.registry import FormatParser, register

MAGIC = b"SQLite format 3\x00"
PAGE_TYPES = {2: "Interior index page", 5: "Interior table page",
              10: "Leaf index page", 13: "Leaf table page"}

MAX_CELLS_PER_PAGE = 65536  # sanity cap; real pages hold far fewer


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    """SQLite big-endian varint: returns (value, next_pos)."""
    result = 0
    for i in range(8):
        if pos + i >= len(buf):
            raise ValueError("varint out of bounds")
        b = buf[pos + i]
        result = (result << 7) | (b & 0x7F)
        if not b & 0x80:
            return result, pos + i + 1
    # 9th byte contributes all 8 bits
    if pos + 8 >= len(buf):
        raise ValueError("varint out of bounds")
    result = (result << 8) | buf[pos + 8]
    # interpret as signed 64-bit
    if result >= 1 << 63:
        result -= 1 << 64
    return result, pos + 9


def _decode_record(payload: bytes) -> list:
    """Decode a record (row) header + values into Python values."""
    hdr_len, pos = _varint(payload, 0)
    serials = []
    while pos < hdr_len:
        stype, pos = _varint(payload, pos)
        serials.append(stype)
    values = []
    p = hdr_len
    for stype in serials:
        if stype == 0:
            values.append(None)
        elif 1 <= stype <= 6:
            n = {1: 1, 2: 2, 3: 3, 4: 4, 5: 6, 6: 8}[stype]
            values.append(int.from_bytes(payload[p:p + n], "big", signed=True))
            p += n
        elif stype == 7:
            values.append(struct.unpack(">d", payload[p:p + 8])[0])
            p += 8
        elif stype == 8:
            values.append(0)
        elif stype == 9:
            values.append(1)
        elif stype >= 12:
            n = (stype - 12) // 2
            raw = payload[p:p + n]
            p += n
            if stype % 2:  # odd = text
                values.append(raw.decode("utf-8", "replace"))
            else:
                values.append(raw.hex() + f" ({n} B blob)")
        else:
            values.append(f"<serial {stype}>")
    return values


@register
class SQLiteParser(FormatParser):
    name = "SQLite"
    magic = MAGIC  # 16-byte prefix

    def parse(self, src: DataSource) -> ParseResult:
        messages: list[str] = []
        root = Node(name="SQLite", kind="container", offset=0, size=src.size,
                    description="SQLite 3 database file")
        root.metadata["sqlite"] = {}

        hdr = self._header(src, root, messages)
        if hdr is None:
            root.link_parents()
            return ParseResult(format_name="SQLite", file_size=src.size,
                               root=root, messages=messages, )
        page_size = hdr
        n_pages = src.size // page_size
        root.metadata["sqlite"]["pageSize"] = page_size
        root.metadata["sqlite"]["pageCount"] = n_pages

        pages_node = Node("Pages", kind="container", offset=0, size=src.size,
                          description=f"{n_pages} pages × {page_size} bytes "
                                      "(page 1 includes the 100-byte header)")
        root.add(pages_node)

        # classify every page
        schema_rows: list[list] = []
        freelist_pages: set[int] = set()
        page_nodes: dict[int, Node] = {}
        for pgno in range(1, n_pages + 1):
            off = (pgno - 1) * page_size
            node = self._page_node(src, off, pgno, page_size, messages, schema_rows)
            pages_node.add(node)
            page_nodes[pgno] = node

        # freelist traversal (from header)
        fl_trunk = int.from_bytes(src.read(32, 4), "big")
        fl_count = int.from_bytes(src.read(36, 4), "big")
        if fl_trunk:
            seen = set()
            ptr = fl_trunk
            while ptr and ptr not in seen and len(seen) < 1024:
                seen.add(ptr)
                freelist_pages.add(ptr)
                nxt = int.from_bytes(src.read((ptr - 1) * page_size, 4), "big")
                ptr = nxt
            if fl_count != len(seen):
                pass  # header count may differ slightly; not fatal
        if freelist_pages:
            pages_node.add(Node("Freelist", kind="container",
                                description=f"{len(freelist_pages)} free page(s): "
                                            + ", ".join(map(str, sorted(freelist_pages)))))

        # schema table → relations object → root page
        schema_node = Node("sqlite_schema", kind="container", offset=0, size=0,
                           description=f"{len(schema_rows)} schema objects "
                                       "(from page 1 table b-tree)")
        for row in schema_rows:
            if len(row) < 5:
                continue
            typ, name, tbl, rootpage, sql = row[0], row[1], row[2], row[3], row[4]
            item = Node(f"{typ}: {name}", kind="container",
                        description=f"root page {rootpage}"
                                    + (f" — {sql}" if sql and len(sql) < 200 else ""))
            item.add(Node("Type", kind="field", value=typ, data_type="text"))
            item.add(Node("Root page", kind="field", value=rootpage, data_type="uint32",
                          description=f"page {rootpage} starts the object's b-tree"))
            target = page_nodes.get(rootpage)
            if target is not None:
                item.metadata["relation"] = {"label": f"Page {rootpage}",
                                             "nodeId": target.id}
            schema_node.add(item)
        if schema_rows:
            root.add(schema_node)

        root.link_parents()
        return ParseResult(format_name="SQLite", file_size=src.size, root=root,
                           messages=messages)

    def _header(self, src: DataSource, root: Node, messages: list) -> int | None:
        raw = src.read(0, 100)
        if raw[:16] != MAGIC:
            root.add(Node("Header", kind="error", offset=0, size=16, validation="error",
                          description="Missing 'SQLite format 3' magic"))
            messages.append("Not a SQLite 3 database (magic mismatch)")
            return None
        page_size = int.from_bytes(raw[16:18], "big")
        if page_size == 1:
            page_size = 65536
        valid = page_size >= 512 and page_size & (page_size - 1) == 0
        node = Node("Database Header", kind="container", offset=0, size=100,
                    description="Page 1 file header (100 bytes)")
        root.add(node)
        node.add(Node("Magic", kind="field", offset=0, size=16, value="SQLite format 3",
                      data_type="magic", raw=raw[0:16]))
        node.add(Node("Page size", kind="field", offset=16, size=2,
                      value=page_size, data_type="uint16", endian="big", raw=raw[16:18],
                      description="Must be a power of two between 512 and 65536"))
        node.add(Node("File format version", kind="field", offset=18, size=2,
                      value=f"write {raw[18]}, read {raw[19]}",
                      data_type="uint8", description="1=legacy 2=WAL"))
        node.add(Node("Reserved space per page", kind="field", offset=20, size=1,
                      value=raw[20], data_type="uint8"))
        node.add(Node("File change counter", kind="field", offset=24, size=4,
                      value=int.from_bytes(raw[24:28], "big"), data_type="uint32",
                      endian="big", raw=raw[24:28]))
        node.add(Node("Database size in pages", kind="field", offset=28, size=4,
                      value=int.from_bytes(raw[28:32], "big"), data_type="uint32",
                      endian="big", raw=raw[28:32]))
        node.add(Node("First freelist trunk page", kind="field", offset=32, size=4,
                      value=int.from_bytes(raw[32:36], "big"), data_type="uint32",
                      endian="big", raw=raw[32:36]))
        node.add(Node("Freelist page count", kind="field", offset=36, size=4,
                      value=int.from_bytes(raw[36:40], "big"), data_type="uint32",
                      endian="big", raw=raw[36:40]))
        node.add(Node("Schema cookie", kind="field", offset=40, size=4,
                      value=int.from_bytes(raw[40:44], "big"), data_type="uint32",
                      endian="big"))
        node.add(Node("Text encoding", kind="field", offset=56, size=4,
                      value={1: "UTF-8", 2: "UTF-16le", 3: "UTF-16be"}.get(
                          int.from_bytes(raw[56:60], "big"), "unknown"),
                      data_type="uint32", endian="big", raw=raw[56:60]))
        if not valid:
            messages.append(f"Page size {page_size} is invalid")
        if raw[18] == 2 or raw[19] == 2:
            messages.append("Database uses WAL journaling")
        return page_size if valid else None

    def _page_node(self, src: DataSource, off: int, pgno: int, page_size: int,
                   messages: list, schema_rows: list) -> Node:
        hdr_off = off + (100 if pgno == 1 else 0)
        raw = src.read(hdr_off, 12)
        ptype = raw[0] if raw else 0
        if ptype in PAGE_TYPES:
            cell_count = int.from_bytes(raw[3:5], "big")
            interior = ptype in (2, 5)
            node = Node(f"Page {pgno} — {PAGE_TYPES[ptype]}", kind="container",
                        offset=off, size=page_size,
                        description=f"{cell_count} cells"
                                    + (f", right-most pointer "
                                       f"{int.from_bytes(raw[8:12], 'big')}" if interior else ""))
            node.add(Node("Page type", kind="field", offset=hdr_off, size=1,
                          value=PAGE_TYPES[ptype], data_type="uint8", raw=raw[0:1]))
            node.add(Node("Cells", kind="field", offset=hdr_off + 3, size=2,
                          value=cell_count, data_type="uint16", endian="big",
                          raw=raw[3:5]))
            if ptype == 13:  # table leaf: decode rowids (records for page 1 schema)
                self._leaf_cells(src, off, hdr_off, pgno, page_size, node,
                                 messages, schema_rows)
            return node

        # freelist trunk: next-trunk + count at page start
        raw_full = src.read(off, 8)
        label = self._classify_non_btree(src, off, pgno, page_size)
        return Node(f"Page {pgno} — {label}", kind="container", offset=off,
                    size=page_size, description=raw_full.hex(" ")[:48])

    @staticmethod
    def _classify_non_btree(src: DataSource, off: int, pgno: int, page_size: int) -> str:
        first4 = int.from_bytes(src.read(off, 4), "big")
        second4 = int.from_bytes(src.read(off + 4, 4), "big")
        if second4 == 0 and 0 < first4 < 100000:
            return "Freelist trunk page (possible)"
        return "Unknown / overflow / free page"

    def _leaf_cells(self, src: DataSource, off: int, hdr_off: int, pgno: int,
                    page_size: int, node: Node, messages: list, schema_rows: list) -> None:
        cell_count = int.from_bytes(src.read(hdr_off + 3, 2), "big")
        cell_count = min(cell_count, MAX_CELLS_PER_PAGE)
        ptr_array = hdr_off + 8
        rows_node = Node("Rows", kind="container", offset=hdr_off,
                         size=off + page_size - hdr_off,
                         description=f"{cell_count} cells" if cell_count else "empty page")
        if cell_count:
            node.add(rows_node)
        usable = page_size  # reserved space ignored (see header field 20)
        for i in range(cell_count):
            ptr_raw = src.read(ptr_array + i * 2, 2)
            if len(ptr_raw) < 2:
                break
            cell_off = off + int.from_bytes(ptr_raw, "big")
            buf = src.read(cell_off, min(usable - (cell_off - off), 4096))
            if len(buf) < 2:
                continue
            try:
                payload_len, p = _varint(buf, 0)
                rowid, p = _varint(buf, p)
            except ValueError:
                node.validation = "error"
                messages.append(f"Page {pgno}: malformed cell {i}")
                continue
            if payload_len > len(buf) - p:
                # overflow page involved — read what we have, mark it
                payload = buf[p:]
                note = f"(payload {payload_len} B, first {len(payload)} B, overflow follows)"
            else:
                payload = buf[p:p + payload_len]
                note = ""
            try:
                values = _decode_record(payload) if len(payload) >= payload_len else None
            except (ValueError, struct.error):
                values = None
            row = Node(f"rowid {rowid}", kind="field", offset=cell_off,
                       value=note or (str(values[:6]) if values else payload.hex(" ")[:48]),
                       data_type="record",
                       size=p + min(payload_len, max(0, len(buf) - p)),
                       description=f"payload {payload_len} bytes at 0x{cell_off:X}")
            if pgno == 1 and values is not None:
                schema_rows.append(values)
            rows_node.add(row)
