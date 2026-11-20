#!/usr/bin/env python3
"""Trích xuất requirement từ txt/md/docx/pptx/xlsx/xlsm/csv/pdf sang Markdown.

Chỉ dùng thư viện chuẩn (zipfile + xml), PDF dùng `pdftotext` nếu có,
định dạng cũ (.doc/.ppt/.xls) được convert qua LibreOffice nếu có.

    python3 extract.py <input_dir_or_file> <workspace>

Kết quả:
    <ws>/01_extracted/<slug>.md       nội dung kèm mốc vị trí nguồn
    <ws>/01_extracted/manifest.json   hash từng file -> phát hiện file mới / đổi / xóa
"""
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
SUPPORTED = {".txt", ".md", ".markdown", ".docx", ".pptx", ".xlsx", ".xlsm", ".csv", ".tsv", ".pdf"}
LEGACY = {".doc": "docx", ".ppt": "pptx", ".xls": "xlsx"}
MAX_COLS = 30


def slugify(rel_path: str) -> str:
    s = unicodedata.normalize("NFKD", rel_path.replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "file"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cell_md(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).replace("|", "\\|").strip()


def md_table(rows):
    rows = [r[:MAX_COLS] for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(cell_md(c) for c in rows[0]) + " |",
           "|" + "---|" * width]
    out += ["| " + " | ".join(cell_md(c) for c in r) + " |" for r in rows[1:]]
    return out


# ---------- docx ----------
def _w_text(el) -> str:
    parts = []
    for node in el.iter():
        tag = node.tag.split("}")[-1]
        if tag == "t" and node.text:
            parts.append(node.text)
        elif tag == "tab":
            parts.append("\t")
        elif tag in ("br", "cr"):
            parts.append(" ")
    return "".join(parts)


def extract_docx(path: Path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
        styles = {}
        if "word/styles.xml" in z.namelist():
            for st in ET.fromstring(z.read("word/styles.xml")).findall("w:style", NS):
                sid = st.get(f"{{{NS['w']}}}styleId")
                name = st.find("w:name", NS)
                styles[sid] = (name.get(f"{{{NS['w']}}}val") if name is not None else sid) or ""
    body = root.find("w:body", NS)
    out, pno, tno = [], 0, 0
    for el in body:
        tag = el.tag.split("}")[-1]
        if tag == "p":
            text = _w_text(el).strip()
            if not text:
                continue
            pno += 1
            ppr = el.find("w:pPr", NS)
            style, is_list = "", False
            if ppr is not None:
                ps = ppr.find("w:pStyle", NS)
                if ps is not None:
                    sid = ps.get(f"{{{NS['w']}}}val")
                    style = styles.get(sid, sid or "").lower()
                is_list = ppr.find("w:numPr", NS) is not None
            m = re.match(r"(heading|見出し|title)\s*(\d)?", style)
            if m:
                level = int(m.group(2) or 1) if m.group(1) != "title" else 1
                out.append(f"\n{'#' * min(level + 1, 6)} {text}  `[p{pno}]`\n")
            elif is_list or "list" in style:
                out.append(f"- {text}  `[p{pno}]`")
            else:
                out.append(f"{text}  `[p{pno}]`")
        elif tag == "tbl":
            tno += 1
            rows = []
            for tr in el.findall("w:tr", NS):
                rows.append([_w_text(tc).strip() for tc in tr.findall("w:tc", NS)])
            out.append(f"\n`[table{tno}]`\n")
            out += md_table(rows)
            out.append("")
    return out


# ---------- pptx ----------
def _num(name: str) -> int:
    m = re.search(r"(\d+)\.xml$", name)
    return int(m.group(1)) if m else 0


def _a_paragraphs(xml_bytes):
    root = ET.fromstring(xml_bytes)
    in_tables = {id(p) for tbl in root.iter(f"{{{NS['a']}}}tbl") for p in tbl.iter(f"{{{NS['a']}}}p")}
    paras = []
    for p in root.iter(f"{{{NS['a']}}}p"):
        if id(p) in in_tables:
            continue
        t = "".join(x.text or "" for x in p.iter(f"{{{NS['a']}}}t")).strip()
        if t:
            paras.append(t)
    return paras, root


def extract_pptx(path: Path):
    out = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        slides = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=_num)
        for sn in slides:
            n = _num(sn)
            paras, root = _a_paragraphs(z.read(sn))
            out.append(f"\n## Slide {n}  `[slide{n}]`\n")
            # bảng trong slide
            for ti, tbl in enumerate(root.iter(f"{{{NS['a']}}}tbl"), 1):
                rows = [["".join(t.text or "" for t in tc.iter(f"{{{NS['a']}}}t"))
                         for tc in tr.findall("a:tc", NS)] for tr in tbl.findall("a:tr", NS)]
                out.append(f"`[slide{n}-table{ti}]`\n")
                out += md_table(rows) + [""]
            out += [f"- {t}" for t in paras]
            note = f"ppt/notesSlides/notesSlide{n}.xml"
            # notesSlideN không luôn khớp slideN; tra qua rels cho chắc
            rels = f"ppt/slides/_rels/slide{n}.xml.rels"
            if rels in names:
                for r in ET.fromstring(z.read(rels)).findall("rel:Relationship", NS):
                    if r.get("Type", "").endswith("/notesSlide"):
                        note = "ppt/" + r.get("Target").replace("../", "")
            if note in names:
                npar, _ = _a_paragraphs(z.read(note))
                npar = [t for t in npar if not re.fullmatch(r"\d+", t)]
                if npar:
                    out.append(f"\n> Speaker notes `[slide{n}-notes]`:")
                    out += [f"> {t}" for t in npar]
    return out


# ---------- xlsx ----------
def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def extract_xlsx(path: Path):
    out = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("s:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['s']}}}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target")
                for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall("rel:Relationship", NS)}
        for sh in wb.find("s:sheets", NS).findall("s:sheet", NS):
            name = sh.get("name")
            target = rels.get(sh.get(f"{{{NS['r']}}}id"), "")
            target = target.lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            if target not in names:
                continue
            root = ET.fromstring(z.read(target))
            grid = {}
            for row in root.iter(f"{{{NS['s']}}}row"):
                r = int(row.get("r"))
                for c in row.findall("s:c", NS):
                    ref, t = c.get("r"), c.get("t")
                    v = c.find("s:v", NS)
                    if t == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(f"{{{NS['s']}}}t"))
                    else:
                        val = v.text if v is not None else ""
                    if val and val.strip():
                        grid[(r, _col_index(ref))] = val
            out.append(f"\n## Sheet: {name}  `[sheet:{name}]`\n")
            if not grid:
                out.append("_(trống)_")
                continue
            rows_idx = sorted({r for r, _ in grid})
            max_c = min(max(c for _, c in grid), MAX_COLS - 1)
            # thêm cột "Row" để trích dẫn được số dòng gốc
            rows = [["Row"] + [chr(65 + i) if i < 26 else f"C{i+1}" for i in range(max_c + 1)]]
            for r in rows_idx:
                rows.append([str(r)] + [grid.get((r, c), "") for c in range(max_c + 1)])
            out += md_table(rows)
    return out


def extract_csv(path: Path):
    delim = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        rows = list(csv.reader(f, delimiter=delim))
    return md_table([["Row"] + (rows[0] if rows else [])] +
                    [[str(i + 2)] + r for i, r in enumerate(rows[1:])])


def extract_pdf(path: Path):
    if not shutil.which("pdftotext"):
        raise RuntimeError("thiếu pdftotext (poppler-utils)")
    txt = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                         capture_output=True, text=True, check=True).stdout
    out = []
    for i, page in enumerate(txt.split("\f"), 1):
        if page.strip():
            out.append(f"\n## Page {i}  `[page{i}]`\n")
            out += [ln.rstrip() for ln in page.splitlines()]
    return out


def extract_text(path: Path):
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


EXTRACTORS = {".docx": extract_docx, ".pptx": extract_pptx, ".xlsx": extract_xlsx,
              ".xlsm": extract_xlsx, ".csv": extract_csv, ".tsv": extract_csv,
              ".pdf": extract_pdf, ".txt": extract_text, ".md": extract_text,
              ".markdown": extract_text}


def convert_legacy(path: Path, tmp: Path) -> Path:
    office = shutil.which("soffice") or shutil.which("libreoffice")
    if not office:
        raise RuntimeError(f"cần LibreOffice để đọc {path.suffix}; hãy lưu lại dạng {LEGACY[path.suffix.lower()]}")
    subprocess.run([office, "--headless", "--convert-to", LEGACY[path.suffix.lower()],
                    "--outdir", str(tmp), str(path)], capture_output=True, check=True, timeout=180)
    return tmp / (path.stem + "." + LEGACY[path.suffix.lower()])


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, ws = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    out_dir = ws / "01_extracted"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = src if src.is_dir() else src.parent
    files = sorted(p for p in (src.rglob("*") if src.is_dir() else [src])
                   if p.is_file() and not p.name.startswith(("~$", "."))
                   and p.suffix.lower() in SUPPORTED | set(LEGACY)
                   and ws not in p.resolve().parents)

    mpath = out_dir / "manifest.json"
    old = json.loads(mpath.read_text()) if mpath.exists() else {"files": {}}
    new = {"source_root": str(base), "updated": datetime.now().isoformat(timespec="seconds"), "files": {}}
    report = {"new": [], "changed": [], "unchanged": [], "removed": [], "failed": []}

    with tempfile.TemporaryDirectory() as tmp:
        for p in files:
            rel = str(p.relative_to(base))
            slug = slugify(rel)
            digest = sha256(p)
            prev = old["files"].get(rel)
            entry = {"slug": slug, "sha256": digest, "extracted": f"01_extracted/{slug}.md",
                     "src_id": f"SRC-{slug}"}
            if prev and prev.get("sha256") == digest and (out_dir / f"{slug}.md").exists():
                entry.update({k: prev[k] for k in ("lines", "extracted_at") if k in prev})
                new["files"][rel] = entry
                report["unchanged"].append(rel)
                continue
            try:
                real = convert_legacy(p, Path(tmp)) if p.suffix.lower() in LEGACY else p
                body = EXTRACTORS[real.suffix.lower()](real)
            except Exception as e:  # noqa: BLE001 - báo lỗi từng file, không dừng cả lô
                report["failed"].append(f"{rel}: {e}")
                continue
            header = [f"<!-- src_id: SRC-{slug} | source: {rel} | sha256: {digest[:12]} -->",
                      f"# {rel}", "",
                      "> Mốc vị trí: `[pN]` đoạn Word, `[tableN]` bảng, `[slideN]` slide, "
                      "`[sheet:Tên]` + cột Row = dòng Excel gốc, `[pageN]` trang PDF.", ""]
            text = "\n".join(header + body).rstrip() + "\n"
            (out_dir / f"{slug}.md").write_text(text, encoding="utf-8")
            entry["lines"] = text.count("\n")
            entry["extracted_at"] = new["updated"]
            new["files"][rel] = entry
            report["changed" if prev else "new"].append(rel)

    report["removed"] = [r for r in old["files"] if r not in new["files"]]
    report["removed_src_ids"] = {r: old["files"][r]["src_id"] for r in report["removed"]}
    new["last_run"] = report
    mpath.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
