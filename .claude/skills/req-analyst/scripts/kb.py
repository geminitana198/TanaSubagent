#!/usr/bin/env python3
"""Công cụ cho hệ thống tri thức (knowledge base) dạng Markdown + [[wikilink]].

    python3 kb.py init    <ws>                 tạo cấu trúc thư mục workspace
    python3 kb.py index   <ws>                 sinh note nguồn, back-link, index.md, _lint.md
    python3 kb.py search  <ws> <từ khóa...>    tìm nhanh trong KB, glossary, bản dịch, bản trích xuất
    python3 kb.py show    <ws> <ID>            xem 1 note + note nó trỏ tới + note trỏ tới nó
    python3 kb.py next-id <ws> <type>          ID kế tiếp cho loại note (feature, rule, ...)
    python3 kb.py impact  <ws>                 note bị ảnh hưởng bởi file nguồn mới/đổi/xóa ở lần extract gần nhất

Note KB: file `<ID>.md` trong thư mục theo loại, có frontmatter (id, type, title,
aliases, status, sources) và liên kết `[[ID]]` / `[[ID|nhãn]]` / `[[ID#mục]]`.
"""
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

TYPES = {  # type: (thư mục, tiền tố ID, nhãn tiếng Việt)
    "module": ("modules", "M", "Module / phân hệ"),
    "feature": ("features", "F", "Chức năng"),
    "actor": ("actors", "A", "Tác nhân / vai trò"),
    "rule": ("rules", "BR", "Quy tắc nghiệp vụ"),
    "entity": ("entities", "E", "Thực thể dữ liệu"),
    "screen": ("screens", "S", "Màn hình"),
    "integration": ("integrations", "I", "Tích hợp hệ thống ngoài"),
    "nfr": ("nfr", "NFR", "Yêu cầu phi chức năng"),
    "process": ("processes", "P", "Quy trình nghiệp vụ"),
    "question": ("questions", "Q", "Câu hỏi mở (Q&A)"),
    "assumption": ("assumptions", "AS", "Giả định"),
    "decision": ("decisions", "D", "Quyết định / câu trả lời đã chốt"),
    "source": ("sources", "SRC", "Tài liệu nguồn"),
}
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
BL_START, BL_END = "<!-- backlinks:start -->", "<!-- backlinks:end -->"


def ws_paths(ws: Path):
    return ws / "kb", ws / "01_extracted" / "manifest.json"


# ---------- frontmatter tối giản (không cần PyYAML) ----------
def parse_note(path: Path):
    text = path.read_text(encoding="utf-8")
    meta, body = {}, text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            body = text[end + 4:].lstrip("\n")
            key = None
            for line in text[4:end].splitlines():
                if re.match(r"^\s+-\s+", line) and key:
                    meta.setdefault(key, [])
                    if isinstance(meta[key], list):
                        meta[key].append(line.split("-", 1)[1].strip().strip("'\""))
                    continue
                m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
                if not m:
                    continue
                key, val = m.group(1), m.group(2).strip()
                if val.startswith("[") and val.endswith("]"):
                    meta[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
                elif val == "":
                    meta[key] = []
                else:
                    meta[key] = val.strip("'\"")
    meta.setdefault("id", path.stem)
    meta.setdefault("title", path.stem)
    return meta, body, text


def strip_backlinks(text: str) -> str:
    return re.sub(re.escape(BL_START) + r".*?" + re.escape(BL_END) + r"\n?", "", text, flags=re.S).rstrip() + "\n"


def load_notes(kb: Path):
    notes = {}
    for p in sorted(kb.rglob("*.md")):
        if p.name in ("index.md", "_lint.md") or p.name.startswith("_"):
            continue
        meta, body, text = parse_note(p)
        content = strip_backlinks(text)
        links = sorted({l.strip() for l in LINK_RE.findall(content)})
        notes[meta["id"]] = {"path": p, "meta": meta, "text": text, "links": links}
    return notes


def label(n):
    return f"[[{n['meta']['id']}]] {n['meta'].get('title', '')}".rstrip()


# ---------- init ----------
def cmd_init(ws: Path):
    kb, _ = ws_paths(ws)
    for d in ["00_input", "01_extracted", "02_translated/_new_terms",
              "deliverables/overview", "deliverables/mockups", "deliverables/artifact",
              "deliverables/estimation", "deliverables/proposal"]:
        (ws / d).mkdir(parents=True, exist_ok=True)
    for folder, _, _ in TYPES.values():
        (kb / folder).mkdir(parents=True, exist_ok=True)
    state = ws / "state.json"
    if not state.exists():
        state.write_text(json.dumps({"project": ws.name, "phase": "init", "decisions": {}},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    gl = ws / "glossary.md"
    if not gl.exists():
        gl.write_text("# Bảng thuật ngữ dự án\n\n"
                      "| Thuật ngữ gốc | Tiếng Việt (dùng thống nhất) | Viết tắt | Định nghĩa trong ngữ cảnh dự án | Nguồn | Trạng thái |\n"
                      "|---|---|---|---|---|---|\n", encoding="utf-8")
    print(f"Đã tạo workspace: {ws}")


# ---------- index ----------
def generate_sources(ws: Path, kb: Path):
    _, mpath = ws_paths(ws)
    if not mpath.exists():
        return
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    src_dir = kb / TYPES["source"][0]
    src_dir.mkdir(parents=True, exist_ok=True)
    alive = set()
    for rel, e in manifest["files"].items():
        sid = e["src_id"]
        alive.add(sid)
        vi = ws / "02_translated" / f"{e['slug']}.vi.md"
        lines = [
            "---", f"id: {sid}", "type: source", f"title: {rel}", "status: generated", "---",
            f"# {sid} — {rel}", "",
            f"- File gốc: `{Path(manifest.get('source_root', '')) / rel}`",
            f"- Bản trích xuất: `{e['extracted']}` ({e.get('lines', '?')} dòng)",
            f"- Bản dịch tiếng Việt: `02_translated/{e['slug']}.vi.md`" + ("" if vi.exists() else " _(chưa có)_"),
            f"- sha256: `{e['sha256'][:16]}` — trích xuất lúc {e.get('extracted_at', '?')}", "",
            "_Note này sinh tự động bởi `kb.py index`; mục back-link bên dưới cho biết note KB nào dựa trên tài liệu này._",
        ]
        (src_dir / f"{sid}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for p in src_dir.glob("SRC-*.md"):
        if p.stem not in alive:
            p.unlink()  # file nguồn đã bị xóa khỏi input; back-link hỏng sẽ hiện trong _lint.md


def cmd_index(ws: Path):
    kb, _ = ws_paths(ws)
    generate_sources(ws, kb)
    notes = load_notes(kb)
    back = defaultdict(set)
    broken = []
    for nid, n in notes.items():
        for t in n["links"]:
            if t in notes:
                if t != nid:
                    back[t].add(nid)
            else:
                broken.append((nid, t))

    order = list(TYPES)
    for nid, n in notes.items():
        groups = defaultdict(list)
        for b in sorted(back[nid]):
            groups[notes[b]["meta"].get("type", "other")].append(label(notes[b]))
        block = [BL_START, "## Back-link (được tham chiếu bởi)", ""]
        if not groups:
            block.append("_Chưa có note nào trỏ tới._")
        for typ in sorted(groups, key=lambda t: order.index(t) if t in order else 99):
            block.append(f"**{TYPES.get(typ, (None, None, typ))[2]}:** " + " · ".join(groups[typ]))
        block.append(BL_END)
        new_text = strip_backlinks(n["text"]) + "\n" + "\n".join(block) + "\n"
        if new_text != n["text"]:
            n["path"].write_text(new_text, encoding="utf-8")

    # index.md
    by_type = defaultdict(list)
    for n in notes.values():
        by_type[n["meta"].get("type", "other")].append(n)
    idx = ["# Mục lục hệ thống tri thức", "",
           "Tìm nhanh: `python3 .claude/skills/req-analyst/scripts/kb.py search <ws> <từ khóa>` · "
           "Thuật ngữ: `../glossary.md` · Kiểm tra liên kết: `_lint.md`", ""]
    idx.append("| Loại | Số note |\n|---|---|")
    for typ in order + sorted(set(by_type) - set(order)):
        if by_type.get(typ):
            idx.append(f"| {TYPES.get(typ, (0, 0, typ))[2]} | {len(by_type[typ])} |")
    for typ in order + sorted(set(by_type) - set(order)):
        items = by_type.get(typ)
        if not items:
            continue
        idx += ["", f"## {TYPES.get(typ, (0, 0, typ))[2]}", "", "| ID | Tiêu đề | Trạng thái | Liên kết đi | Back-link |", "|---|---|---|---|---|"]
        for n in sorted(items, key=lambda x: natural_key(x["meta"]["id"])):
            m = n["meta"]
            idx.append(f"| [[{m['id']}]] | {m.get('title', '')} | {m.get('status', '')} | "
                       f"{len(n['links'])} | {len(back[m['id']])} |")
    (kb / "index.md").write_text("\n".join(idx) + "\n", encoding="utf-8")

    # _lint.md
    lint = ["# Kiểm tra KB", ""]
    lint += ["## Liên kết hỏng", ""] + ([f"- [[{a}]] → `[[{b}]]` không tồn tại" for a, b in broken] or ["_Không có._"])
    nosrc = [nid for nid, n in notes.items()
             if n["meta"].get("type") not in ("source", "question", "decision")
             and not any(l.startswith("SRC-") for l in n["links"])]
    lint += ["", "## Note chưa trích dẫn tài liệu nguồn ([[SRC-...]])", ""] + ([f"- [[{x}]]" for x in nosrc] or ["_Không có._"])
    orphans = [nid for nid, n in notes.items() if not back[nid] and n["meta"].get("type") != "source"]
    lint += ["", "## Note mồ côi (không note nào trỏ tới)", ""] + ([f"- [[{x}]]" for x in orphans] or ["_Không có._"])
    unused = [nid for nid, n in notes.items() if n["meta"].get("type") == "source" and not back[nid]]
    lint += ["", "## Tài liệu nguồn chưa được khai thác vào KB", ""] + ([f"- [[{x}]]" for x in unused] or ["_Không có._"])
    openq = [nid for nid, n in notes.items() if n["meta"].get("type") == "question"
             and n["meta"].get("status", "open") == "open"]
    lint += ["", f"## Câu hỏi còn mở ({len(openq)})", ""] + ([f"- {label(notes[x])}" for x in openq] or ["_Không có._"])
    (kb / "_lint.md").write_text("\n".join(lint) + "\n", encoding="utf-8")
    print(json.dumps({"notes": len(notes), "broken_links": len(broken), "without_source": len(nosrc),
                      "orphans": len(orphans), "unused_sources": len(unused), "open_questions": len(openq)},
                     ensure_ascii=False))


def natural_key(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


# ---------- search ----------
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).replace("đ", "d")


def cmd_search(ws: Path, terms, limit=12):
    kb, _ = ws_paths(ws)
    q = [re.compile(r"(?<!\w)" + re.escape(norm(t)) + r"(?!\w)") for t in terms if t.strip()]
    hits = []
    pools = [(p, 3) for p in kb.rglob("*.md") if p.name not in ("index.md", "_lint.md")]
    pools += [(ws / "glossary.md", 4)] if (ws / "glossary.md").exists() else []
    pools += [(p, 1) for p in (ws / "02_translated").glob("*.md")]
    pools += [(p, 1) for p in (ws / "01_extracted").glob("*.md")]
    for path, weight in pools:
        # bỏ khối back-link để note không "ăn điểm" nhờ tiêu đề của note khác
        lines = strip_backlinks(path.read_text(encoding="utf-8", errors="replace")).splitlines()
        nlines = [norm(l) for l in lines]
        per_line = [[len(t.findall(nl)) for t in q] for nl in nlines]
        score = sum(map(sum, per_line))
        if not score:
            continue
        cover = sum(any(pl[i] for pl in per_line) for i in range(len(q)))
        head = norm(" ".join(lines[:8]))
        score = score * weight * cover + 5 * sum(bool(t.search(head)) for t in q) * weight
        best = sorted(((sum(1 for c in pl if c), i) for i, pl in enumerate(per_line) if any(pl)), key=lambda x: -x[0])
        snippets = [f"  L{i+1}: {lines[i].strip()[:160]}" for _, i in best[:3]]
        hits.append((score, path, snippets))
    hits.sort(key=lambda h: -h[0])
    if not hits:
        print("Không tìm thấy. Thử từ đồng nghĩa / thuật ngữ gốc trong glossary.md.")
    for score, path, snippets in hits[:limit]:
        print(f"[{score}] {path.relative_to(ws)}")
        print("\n".join(snippets))


# ---------- show ----------
def cmd_show(ws: Path, nid: str):
    kb, _ = ws_paths(ws)
    notes = load_notes(kb)
    if nid not in notes:
        sys.exit(f"Không có note {nid}. Dùng `search` để tìm.")
    n = notes[nid]
    print(f"# {n['path'].relative_to(ws)}\n")
    print(strip_backlinks(n["text"]))
    print("## Trỏ tới")
    for t in n["links"]:
        print(f"- {label(notes[t])}" if t in notes else f"- [[{t}]] (HỎNG)")
    print("## Được trỏ tới bởi")
    for b in sorted(k for k, v in notes.items() if nid in v["links"] and k != nid):
        print(f"- {label(notes[b])}")


def cmd_next_id(ws: Path, typ: str):
    if typ not in TYPES:
        sys.exit(f"type phải là một trong: {', '.join(TYPES)}")
    kb, _ = ws_paths(ws)
    folder, prefix, _ = TYPES[typ]
    nums = [int(m.group(1)) for p in (kb / folder).glob(f"{prefix}-*.md")
            if (m := re.match(rf"{prefix}-(\d+)$", p.stem))]
    print(f"{prefix}-{(max(nums) + 1 if nums else 1):03d}")


def cmd_impact(ws: Path):
    kb, mpath = ws_paths(ws)
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    run = manifest.get("last_run", {})
    slugs = {rel: e["src_id"] for rel, e in manifest["files"].items()}
    notes = load_notes(kb)
    for kind in ("new", "changed", "removed"):
        for rel in run.get(kind, []):
            sid = slugs.get(rel) or run.get("removed_src_ids", {}).get(rel, "?")
            users = sorted(k for k, v in notes.items() if sid in v["links"] and k != sid)
            print(f"[{kind}] {rel} ({sid}) → {len(users)} note: " + (", ".join(users) or "—"))


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, ws = sys.argv[1], Path(sys.argv[2]).resolve()
    args = sys.argv[3:]
    if cmd == "init":
        cmd_init(ws)
    elif cmd == "index":
        cmd_index(ws)
    elif cmd == "search" and args:
        cmd_search(ws, args)
    elif cmd == "show" and args:
        cmd_show(ws, args[0])
    elif cmd == "next-id" and args:
        cmd_next_id(ws, args[0])
    elif cmd == "impact":
        cmd_impact(ws)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
