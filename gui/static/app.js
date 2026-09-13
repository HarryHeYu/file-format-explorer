/* ffe GUI: virtualized hex viewer + structure tree + field inspector. */
"use strict";

const ROW_BYTES = 16, ROW_H = 20, CHUNK = 65536;
const S = {
  path: null, size: 0, root: null, flat: [],      // flat: nodes with size>0, sorted by size
  chunks: new Map(),                              // chunkIdx -> Uint8Array
  selNode: null, selByte: -1, selEnd: -1,         // byte selection range [selByte, selEnd)
};
const $ = (id) => document.getElementById(id);
const hex = (n, w) => n.toString(16).toUpperCase().padStart(w, "0");

/* ---------------- data ---------------- */
async function fetchChunk(i) {
  if (S.chunks.has(i)) return S.chunks.get(i);
  const off = i * CHUNK;
  const r = await fetch(`/api/bytes?path=${encodeURIComponent(S.path)}&offset=${off}&length=${CHUNK}`);
  const j = await r.json();
  const u8 = new Uint8Array(atob(j.data).split("").map((c) => c.charCodeAt(0)));
  S.chunks.set(i, u8);
  return u8;
}

function byteAt(off) {
  if (off < 0 || off >= S.size) return null;
  const u8 = S.chunks.get(Math.floor(off / CHUNK));
  return u8 ? u8[off % CHUNK] : null;
}

/* ---------------- tree index ---------------- */
function indexTree(node, out) {
  if (node.size > 0) out.push(node);
  for (const c of node.children || []) indexTree(c, out);
  return out;
}

function deepestAt(offset) {
  // smallest-size node containing the byte; tie-break: later (more specific) node
  let best = null;
  for (const n of S.flat) {
    if (n.offset <= offset && offset < n.end) {
      if (!best || n.size <= best.size) best = n;
    }
  }
  return best;
}

/* ---------------- hex rendering (virtualized) ---------------- */
const scrollEl = () => $("hexScroll");
function totalRows() { return Math.ceil(S.size / ROW_BYTES); }

function renderHex() {
  const sc = scrollEl();
  const first = Math.max(0, Math.floor(sc.scrollTop / ROW_H) - 8);
  const last = Math.min(totalRows(), first + Math.ceil(sc.clientHeight / ROW_H) + 16);
  const canvas = $("hexCanvas");
  canvas.style.top = (first * ROW_H) + "px";
  const frag = document.createDocumentFragment();
  for (let r = first; r < last; r++) frag.appendChild(hexRow(r));
  canvas.replaceChildren(frag);
}

function hexRow(r) {
  const row = document.createElement("div");
  row.className = "hexrow";
  const base = r * ROW_BYTES;
  const off = document.createElement("span");
  off.className = "hexoff";
  off.textContent = hex(base, 8);
  row.appendChild(off);

  const bytes = document.createElement("span");
  bytes.className = "hexbytes";
  const asc = document.createElement("span");
  asc.className = "hexasc";

  let ascText = "";
  for (let i = 0; i < ROW_BYTES; i++) {
    const o = base + i;
    if (o >= S.size) { bytes.appendChild(document.createTextNode("   ")); ascText += " "; continue; }
    const v = byteAt(o);
    const b = document.createElement("span");
    b.className = "b";
    b.textContent = v === null ? "??" : hex(v, 2);
    b.dataset.off = o;
    markByte(b, o, v === null ? 0 : v);
    bytes.appendChild(b);
    const ch = v === null ? " " : (v >= 32 && v < 127 ? String.fromCharCode(v) : "·");
    const a = document.createElement("span");
    a.className = "a";
    a.textContent = ch;
    a.dataset.off = o;
    if (inSel(o)) a.classList.add("sel");
    asc.appendChild(a);
    ascText += ""; // ascii built from spans
  }
  row.appendChild(bytes);
  row.appendChild(asc);
  return row;
}

function markByte(b, o, v) {
  if (inSel(o)) b.classList.add("sel");
  if (S.selNode && o >= S.selNode.offset && o < S.selNode.end) b.classList.add("hl");
}

function inSel(o) { return o >= S.selByte && o < S.selEnd; }

/* re-mark existing rendered bytes (cheap, called on selection change) */
function refreshMarks() {
  document.querySelectorAll("#hexCanvas .b").forEach((b) => {
    const o = +b.dataset.off;
    b.classList.toggle("sel", inSel(o));
    b.classList.toggle("hl", !!(S.selNode && o >= S.selNode.offset && o < S.selNode.end));
  });
  document.querySelectorAll("#hexCanvas .a").forEach((a) => {
    a.classList.toggle("sel", inSel(+a.dataset.off));
  });
}

function scrollHexTo(offset) {
  const sc = scrollEl();
  const row = Math.floor(offset / ROW_BYTES);
  sc.scrollTop = Math.max(0, row * ROW_H - sc.clientHeight / 2 + ROW_H / 2);
  renderHex();
}

/* ---------------- validation summary panel ---------------- */
function renderValidation() {
  const panel = $("validationPanel");
  const all = [];
  (function collect(n) { all.push(n); (n.children || []).forEach(collect); })(S.root);
  const errors = all.filter((n) => n.validation === "error");
  const warns = all.filter((n) => n.validation === "warning");
  if (!errors.length && !warns.length) {
    panel.style.display = "";
    panel.innerHTML = `<div class="vp okline">✓ Structure valid (${all.length} nodes)</div>`;
    return;
  }
  panel.style.display = "";
  panel.replaceChildren();
  const head = document.createElement("div");
  head.className = "vp head";
  head.textContent = `✗ ${errors.length} error(s) · ⚠ ${warns.length} warning(s)`;
  panel.appendChild(head);
  for (const n of [...errors, ...warns]) {
    const el = document.createElement("div");
    el.className = "vp item " + (n.validation === "error" ? "iterr" : "itwarn");
    el.textContent = (n.validation === "error" ? "✗ " : "⚠ ") + (n.path || n.name) +
      (n.description ? ` — ${n.description}` : "");
    el.addEventListener("click", () => selectNode(n, false));
    panel.appendChild(el);
  }
}

/* ---------------- tree rendering ---------------- */
function renderTree() {
  const tree = $("tree");
  tree.replaceChildren();
  tree.appendChild(treeNode(S.root, 0));
}

function treeNode(node, depth) {
  const wrap = document.createElement("div");
  const el = document.createElement("div");
  el.className = "tnode";
  if (node.validation === "error") el.classList.add("terr");
  else if (node.validation === "warning") el.classList.add("twarn");
  if (S.selNode && S.selNode.id === node.id) el.classList.add("selected");
  el.dataset.id = node.id;

  const twist = document.createElement("span");
  twist.className = "twist";
  const kids = node.children || [];
  const collapsed = depth >= 2 && kids.length > 0; // auto-collapse deep levels
  twist.textContent = kids.length ? (collapsed ? "▶" : "▼") : " ";
  el.appendChild(twist);

  const name = document.createElement("span");
  name.className = "nname";
  name.textContent = node.name;
  el.appendChild(name);

  let valTxt = "";
  if (node.value !== null && node.value !== undefined) valTxt += " = " + node.value;
  else if (node.size > 0 && kids.length === 0) valTxt += `  [0x${hex(node.offset, 4)} · ${fmtSize(node.size)}]`;
  if (valTxt) {
    const v = document.createElement("span");
    v.className = "nval";
    v.textContent = valTxt;
    el.appendChild(v);
  }

  wrap.appendChild(el);
  const childWrap = document.createElement("div");
  childWrap.className = "tchildren";
  if (collapsed) childWrap.style.display = "none";
  for (const c of kids) childWrap.appendChild(treeNode(c, depth + 1));
  wrap.appendChild(childWrap);

  el.addEventListener("click", (ev) => {
    if (ev.target === twist && kids.length) {
      childWrap.style.display = childWrap.style.display === "none" ? "" : "none";
      twist.textContent = childWrap.style.display === "none" ? "▶" : "▼";
      ev.stopPropagation();
      return;
    }
    selectNode(node, true);
  });
  return wrap;
}

function revealNode(id) {
  // expand ancestors and highlight the row for node.id
  const all = $("tree").querySelectorAll(".tnode");
  let target = null;
  for (const el of all) {
    if (+el.dataset.id === id) { target = el; break; }
  }
  if (!target) return;
  let p = target.parentElement;
  while (p && p.id !== "tree") {
    if (p.classList && p.classList.contains("tchildren")) p.style.display = "";
    p = p.parentElement;
  }
  document.querySelectorAll(".tnode.selected").forEach((e) => e.classList.remove("selected"));
  target.classList.add("selected");
  target.scrollIntoView({ block: "nearest" });
}

/* ---------------- selection & inspector ---------------- */
function selectNode(node, fromTree) {
  S.selNode = node;
  S.selByte = node.offset;
  S.selEnd = Math.max(node.end, node.offset + (node.size ? node.size : 1));
  scrollHexTo(node.offset);
  refreshMarks();
  renderInspector();
  revealNode(node.id);
  setStatus(`Selected ${node.path || node.name} — 0x${hex(node.offset, 4)} … 0x${hex(Math.max(node.end - 1, node.offset), 4)}`);
}

function selectByte(offset) {
  S.selByte = offset; S.selEnd = offset + 1;
  refreshMarks();
  const node = deepestAt(offset);
  if (node) {
    S.selNode = null; // byte selection shows interpreter, plus node info
    renderInspector(node);
    revealNode(node.id);
    setStatus(`Byte 0x${hex(offset, 4)} belongs to: ${node.path || node.name}`);
  } else {
    renderInspector(null);
  }
}

function fmtSize(n) {
  return n >= 1048576 ? (n / 1048576).toFixed(2) + " MB"
       : n >= 1024 ? (n / 1024).toFixed(1) + " KB" : n + " B";
}

function kv(rows) {
  const d = document.createElement("div");
  d.className = "kv";
  for (const [k, v, cls] of rows) {
    const kEl = document.createElement("div"); kEl.className = "k"; kEl.textContent = k;
    const vEl = document.createElement("div"); vEl.className = "v" + (cls ? " " + cls : "");
    vEl.textContent = v;
    d.append(kEl, vEl);
  }
  return d;
}

function interpret(offset, length) {
  const buf = [];
  for (let i = 0; i < length; i++) {
    const v = byteAt(offset + i);
    if (v === null) return null;
    buf.push(v);
  }
  const u8 = Uint8Array.from(buf);
  const dv = new DataView(u8.buffer);
  const out = {};
  try {
    if (u8.length >= 2) { out["uint16 LE"] = dv.getUint16(0, true); out["uint16 BE"] = dv.getUint16(0, false); }
    if (u8.length >= 4) { out["uint32 LE"] = dv.getUint32(0, true); out["uint32 BE"] = dv.getUint32(0, false); }
    if (u8.length >= 4) { out["float32 LE"] = dv.getFloat32(0, true).toPrecision(7); }
    if (u8.length >= 8) { out["uint64 LE"] = dv.getBigUint64(0, true).toString(); out["double LE"] = dv.getFloat64(0, true).toPrecision(10); }
    out.ASCII = [...u8].map((v) => (v >= 32 && v < 127 ? String.fromCharCode(v) : ".")).join("");
    out["UTF-8"] = new TextDecoder("utf-8", { fatal: false }).decode(u8).replace(/[\x00-\x1f]/g, ".");
    out.Hex = [...u8].map((v) => hex(v, 2)).join(" ");
  } catch (e) { /* tolerate */ }
  return out;
}

function findNodeById(node, id) {
  if (node.id === id) return node;
  for (const c of node.children || []) {
    const f = findNodeById(c, id);
    if (f) return f;
  }
  return null;
}

function renderInspector(node) {
  const body = $("inspectorBody");
  body.replaceChildren();
  if (node && node.id !== undefined && S.selNode === null) {
    // byte click: show owning node path + interpreter for this byte
    body.appendChild(kv([
      ["Byte offset", "0x" + hex(S.selByte, 4)],
      ["Belongs to", node.path || node.name],
      ["Node range", `0x${hex(node.offset, 4)} – 0x${hex(Math.max(node.end - 1, node.offset), 4)} (${fmtSize(node.size)})`],
    ]));
    const it = interpret(S.selByte, Math.min(16, S.size - S.selByte));
    if (it) {
      const d = document.createElement("div");
      d.className = "interp";
      d.innerHTML = Object.entries(it).map(([k, v]) => `${k}: <b>${escapeHtml(String(v))}</b>`).join(" &nbsp;·&nbsp; ");
      body.appendChild(d);
    }
    return;
  }
  if (!S.selNode) { body.innerHTML = "<em>Click a structure node or a byte to inspect it.</em>"; return; }
  const n = S.selNode;
  const raw = n.rawHex ? n.rawHex : null;
  const vcls = n.validation === "error" ? "err" : n.validation === "warning" ? "warn" : "ok";
  body.appendChild(kv([
    ["Name", n.name],
    ["Path", n.path || n.name],
    ["Offset", "0x" + hex(n.offset, 4)],
    ["End offset", "0x" + hex(Math.max(n.end - 1, n.offset), 4)],
    ["Size", fmtSize(n.size) + (n.size ? ` (${n.size} bytes)` : "")],
    ...(n.dataType ? [["Type", n.dataType]] : []),
    ...(n.endian ? [["Endian", n.endian === "big" ? "Big Endian" : "Little Endian"]] : []),
    ...(raw ? [["Raw", raw]] : []),
    ...(n.value !== null && n.value !== undefined ? [["Value", String(n.value)]] : []),
    ...(n.validation ? [["Validation", n.validation, vcls]] : []),
    ...(n.description ? [["Description", n.description]] : []),
  ]));
  // cross-node relation (e.g. ZIP central entry → local header, SQLite schema → root page)
  if (n.metadata && n.metadata.relation) {
    const target = findNodeById(S.root, n.metadata.relation.nodeId);
    if (target) {
      const link = document.createElement("div");
      link.className = "interp";
      const a = document.createElement("a");
      a.textContent = `↔ ${n.metadata.relation.label}: ${target.name} — click to jump`;
      a.style.cssText = "color:var(--accent);cursor:pointer;text-decoration:underline";
      a.addEventListener("click", () => selectNode(target, false));
      link.appendChild(a);
      body.appendChild(link);
    }
  }
  if (!raw && n.size > 0 && n.size <= 64) {
    const it = interpret(n.offset, n.size);
    if (it && it.Hex) {
      const d = document.createElement("div");
      d.className = "interp";
      d.innerHTML = `Hex: <b>${escapeHtml(it.Hex)}</b>` +
        (n.size >= 2 ? ` &nbsp;·&nbsp; uint16 BE: <b>${it["uint16 BE"] ?? "-"}</b>` : "") +
        (n.size >= 4 ? ` &nbsp;·&nbsp; uint32 BE: <b>${it["uint32 BE"] ?? "-"}</b>` : "");
      body.appendChild(d);
    }
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ---------------- open file ---------------- */
async function openFile(path) {
  setStatus("Parsing…", true);
  S.chunks.clear();
  const r = await fetch(`/api/open?path=${encodeURIComponent(path)}`);
  const j = await r.json();
  if (j.error) { setStatus("Error: " + j.error); return; }
  if (!j.recognized) {
    $("fileInfo").textContent = "";
    $("tree").replaceChildren();
    $("hexCanvas").replaceChildren();
    setStatus(`Unrecognized format (${fmtSize(j.fileSize)}). Supported: ${supportedText()}`);
    return;
  }
  S.path = j.path; S.size = j.fileSize; S.root = j.root;
  S.flat = indexTree(j.root, []).sort((a, b) => a.size - b.size || a.offset - b.offset);
  $("fileInfo").innerHTML = `<b>${escapeHtml(j.format)}</b> · ${fmtSize(j.fileSize)}` +
    (j.messages.length ? ` · <span style="color:var(--warn)">${escapeHtml(j.messages.join("; "))}</span>` : "");
  // prime the first chunk then draw
  await fetchChunk(0);
  $("hexSpacer").style.height = (totalRows() * ROW_H) + "px";
  S.selNode = null; S.selByte = -1; S.selEnd = -1;
  renderTree();
  renderValidation();
  scrollHexTo(0);
  renderInspector();
  setStatus(`${j.format} parsed — ${S.flat.length} addressable nodes. Click a node or a byte.`);
}

function setStatus(msg, spin) {
  $("statusBar").innerHTML = spin ? `<span class="spin">⏳</span> ${escapeHtml(msg)}` : escapeHtml(msg);
}

/* ---------------- events ---------------- */
scrollEl().addEventListener("scroll", renderHex);
window.addEventListener("resize", renderHex);

document.addEventListener("click", (ev) => {
  const b = ev.target.closest(".b, .a");
  if (b && b.dataset.off !== undefined) selectByte(+b.dataset.off);
});

document.addEventListener("keydown", (ev) => {
  if (ev.target.tagName === "INPUT") return;
  const cur = S.selByte < 0 ? -ROW_BYTES : S.selByte;
  const nav = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -ROW_BYTES, ArrowDown: ROW_BYTES };
  if (nav[ev.key]) {
    ev.preventDefault();
    const o = Math.min(Math.max(0, cur + nav[ev.key]), S.size - 1);
    selectByte(o);
    const row = Math.floor(o / ROW_BYTES);
    const sc = scrollEl();
    const top = Math.floor(sc.scrollTop / ROW_H);
    if (row < top) sc.scrollTop = row * ROW_H;
    else if (row >= top + Math.floor(sc.clientHeight / ROW_H) - 2) sc.scrollTop = (row + 3) * ROW_H - sc.clientHeight;
    renderHex();
  }
});

$("btnOpen").addEventListener("click", () => openFile($("filePath").value.trim()));
$("filePath").addEventListener("keydown", (e) => { if (e.key === "Enter") openFile($("filePath").value.trim()); });

async function jumpTo(offset) {
  const ci = Math.floor(offset / CHUNK);
  if (!S.chunks.has(ci)) await fetchChunk(ci);
  selectByte(offset);
  scrollHexTo(offset);
}

function gotoOffset() {
  const t = $("goTo").value.trim();
  const n = t.startsWith("0x") || t.startsWith("0X") ? parseInt(t, 16) : parseInt(t, 10);
  if (!isNaN(n)) {
    if (n < 0 || n >= S.size) { setStatus(`Offset out of range: ${t} (file is ${S.size} bytes)`); return; }
    jumpTo(n);
    return;
  }
  // not an offset: search structure node names (case-insensitive substring)
  if (!S.root) return;
  const q = t.toLowerCase();
  const matches = S.flat.filter((x) => x.name.toLowerCase().includes(q))
    .sort((a, b) => a.size - b.size || a.offset - b.offset);
  if (matches.length === 0) { setStatus(`No offset or structure node matches "${t}"`); return; }
  selectNode(matches[0], false);
  setStatus(`"${t}" → ${matches[0].path || matches[0].name}` +
    (matches.length > 1 ? ` (${matches.length} matches, showing the most specific)` : ""));
}
$("btnGo").addEventListener("click", gotoOffset);
$("goTo").addEventListener("keydown", (e) => { if (e.key === "Enter") gotoOffset(); });

/* ---------------- search (hex bytes / ASCII text) ---------------- */
function looksLikeHex(t) {
  const s = t.trim().toLowerCase().replace(/^0x/, "").replace(/[\s,]/g, "");
  return s.length > 0 && s.length % 2 === 0 && /^[0-9a-f]+$/.test(s);
}

async function doSearch() {
  const q = $("searchBox").value.trim();
  if (!q || !S.path) return;
  const kind = looksLikeHex(q) ? "hex" : "ascii";
  setStatus(`Searching ${kind}…`, true);
  const r = await fetch(`/api/search?path=${encodeURIComponent(S.path)}&kind=${kind}&q=${encodeURIComponent(q)}`);
  const j = await r.json();
  if (j.error) { setStatus("Search error: " + j.error); return; }
  const box = $("searchResults");
  box.style.display = "";
  $("srSummary").textContent = j.count === 0 ? "No matches"
    : `${j.count} match${j.count > 1 ? "es" : ""} (${kind} "${j.pattern}")`;
  const list = $("srList");
  list.replaceChildren();
  if (j.count === 0) {
    const d = document.createElement("div");
    d.className = "sr-none";
    d.textContent = "Try a different pattern.";
    list.appendChild(d);
    return;
  }
  for (const off of j.hits) {
    const el = document.createElement("div");
    el.className = "sr-hit";
    el.textContent = "0x" + hex(off, 8);
    el.dataset.off = off;
    el.addEventListener("click", () => {
      box.style.display = "none";
      jumpTo(off);
    });
    list.appendChild(el);
  }
  setStatus(`${j.count} match(es) — click one to jump.`);
}
$("btnSearch").addEventListener("click", doSearch);
$("searchBox").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
$("srClose").addEventListener("click", () => { $("searchResults").style.display = "none"; });
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
    e.preventDefault();
    $("searchBox").focus();
    $("searchBox").select();
  }
  if (e.key === "Escape") $("searchResults").style.display = "none";
});

/* supported-format list comes from the registry, not hardcoded */
let FORMAT_LIST = "…";
fetch("/api/formats").then((r) => r.json())
  .then((j) => { FORMAT_LIST = (j.formats || []).join(" / "); })
  .catch(() => { FORMAT_LIST = "unknown"; });
function supportedText() { return FORMAT_LIST; }

/* auto-open from ?file= */
const params = new URLSearchParams(location.search);
if (params.get("file")) {
  $("filePath").value = params.get("file");
  openFile(params.get("file"));
} else {
  setStatus("Enter a file path above to open it.");
}
