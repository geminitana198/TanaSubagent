#!/usr/bin/env python3
"""Tính tổng estimation từ WBS (CSV) + cấu hình đã được con người duyệt. Dùng Decimal.

    python3 estimate.py <wbs.csv> <estimation_config.json> <out_dir>

wbs.csv (UTF-8) cột bắt buộc:
    id, module, feature, task, phase, role, effort, kb_refs, assumption
    - effort: số dương theo đơn vị trong config (`unit`), effort "thuần" (chưa buffer)
    - phase/role: phải có trong config (`phases`, `rates`)
    - kb_refs: ID note KB cách nhau bởi ';' (ví dụ F-001;S-003)

Sinh ra: <out_dir>/estimation_summary.md, estimation_summary.json; in lỗi dữ liệu nếu có.
"""
import csv
import json
import sys
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

REQUIRED = ["id", "module", "feature", "task", "phase", "role", "effort", "kb_refs", "assumption"]


def q(x: Decimal, places="0.01") -> Decimal:
    return x.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    wbs_path, cfg_path, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    unit = cfg.get("unit", "man-day")
    rates = {k: Decimal(str(v)) for k, v in cfg.get("rates", {}).items()}
    phases = cfg.get("phases", [])
    overhead = {k: Decimal(str(v)) for k, v in cfg.get("overhead_percent", {}).items()}
    buffer_pct = Decimal(str(cfg.get("buffer_percent", 0)))
    hours_per_day = Decimal(str(cfg.get("hours_per_day", 8)))
    days_per_month = Decimal(str(cfg.get("days_per_month", 20)))
    currency = cfg.get("currency", "USD")

    errors, rows, seen = [], [], set()
    with wbs_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            sys.exit(f"WBS thiếu cột: {', '.join(missing)}")
        for n, r in enumerate(reader, 2):
            rid = (r["id"] or "").strip()
            if not rid:
                errors.append(f"dòng {n}: thiếu id")
                continue
            if rid in seen:
                errors.append(f"dòng {n}: id trùng {rid}")
            seen.add(rid)
            try:
                eff = Decimal(r["effort"].strip())
                if eff <= 0:
                    raise InvalidOperation
            except (InvalidOperation, AttributeError):
                errors.append(f"dòng {n} ({rid}): effort không hợp lệ '{r['effort']}'")
                continue
            if r["role"] not in rates:
                errors.append(f"dòng {n} ({rid}): role '{r['role']}' không có trong config.rates")
            if phases and r["phase"] not in phases:
                errors.append(f"dòng {n} ({rid}): phase '{r['phase']}' không có trong config.phases")
            if not (r["kb_refs"] or "").strip():
                errors.append(f"dòng {n} ({rid}): thiếu kb_refs (không truy vết được về requirement)")
            r["effort_d"] = eff
            rows.append(r)

    base = sum((r["effort_d"] for r in rows), Decimal(0))
    by = {k: defaultdict(Decimal) for k in ("module", "phase", "role")}
    for r in rows:
        for k in by:
            by[k][r[k]] += r["effort_d"]

    # overhead (PM, QA, ...) tính theo % effort thuần, gán cho role cùng tên nếu có rate
    oh_rows = {name: base * pct / 100 for name, pct in overhead.items()}
    subtotal = base + sum(oh_rows.values(), Decimal(0))
    buffer = subtotal * buffer_pct / 100
    total = subtotal + buffer

    def cost_of(role_efforts):
        return sum((e * rates.get(role, Decimal(0)) for role, e in role_efforts.items()), Decimal(0))

    role_eff = dict(by["role"])
    for name, e in oh_rows.items():
        role_eff[name] = role_eff.get(name, Decimal(0)) + e
    no_rate = [r for r in role_eff if r not in rates]
    cost = cost_of(role_eff)
    avg_rate = cost / subtotal if subtotal else Decimal(0)
    cost_total = cost + buffer * avg_rate

    to_md = {"man-day": Decimal(1), "man-hour": 1 / hours_per_day, "man-month": days_per_month}[unit]
    total_md = total * to_md

    out.mkdir(parents=True, exist_ok=True)
    md = [f"# Tổng hợp estimation ({unit})", "",
          f"- Số hạng mục WBS: {len(rows)} · Lỗi dữ liệu: {len(errors)}",
          f"- Effort thuần: **{q(base)}** {unit}",
          *[f"- Overhead {k} ({overhead[k]}%): {q(v)} {unit}" for k, v in oh_rows.items()],
          f"- Buffer rủi ro ({buffer_pct}%): {q(buffer)} {unit}",
          f"- **Tổng effort: {q(total)} {unit}** (≈ {q(total_md, '0.1')} man-day, "
          f"≈ {q(total_md / days_per_month, '0.1')} man-month)",
          f"- **Tổng chi phí: {q(cost_total, '1')} {currency}**" + (f" _(role chưa có rate: {', '.join(no_rate)})_" if no_rate else ""),
          ""]
    for k, title in (("module", "Theo module"), ("phase", "Theo giai đoạn"), ("role", "Theo vai trò (effort thuần)")):
        md += [f"## {title}", "", f"| {k} | effort ({unit}) | % |", "|---|---:|---:|"]
        keys = phases if k == "phase" and phases else sorted(by[k], key=lambda x: -by[k][x])
        for key in keys:
            if by[k].get(key):
                md.append(f"| {key} | {q(by[k][key])} | {q(by[k][key] / base * 100, '0.1')} |")
        md.append("")
    md += ["## Chi phí theo vai trò (gồm overhead, chưa gồm buffer)", "",
           f"| Vai trò | effort ({unit}) | đơn giá/{unit} | thành tiền ({currency}) |", "|---|---:|---:|---:|"]
    for role, e in sorted(role_eff.items(), key=lambda x: -x[1]):
        rate = rates.get(role)
        md.append(f"| {role} | {q(e)} | {rate if rate is not None else '—'} | {q(e * rate, '1') if rate is not None else '—'} |")
    if errors:
        md += ["", "## Lỗi dữ liệu WBS (phải sửa trước khi gửi khách hàng)", ""] + [f"- {e}" for e in errors]
    (out / "estimation_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    summary = {"unit": unit, "items": len(rows), "base": str(q(base)),
               "overhead": {k: str(q(v)) for k, v in oh_rows.items()}, "buffer": str(q(buffer)),
               "total": str(q(total)), "total_man_day": str(q(total_md)), "currency": currency,
               "cost_total": str(q(cost_total, "1")),
               "by_module": {k: str(q(v)) for k, v in by["module"].items()},
               "by_phase": {k: str(q(v)) for k, v in by["phase"].items()},
               "by_role": {k: str(q(v)) for k, v in role_eff.items()},
               "errors": errors}
    (out / "estimation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("items", "total", "unit", "cost_total", "currency")} | {"errors": len(errors)},
                     ensure_ascii=False))
    for e in errors:
        print("LỖI:", e)


if __name__ == "__main__":
    main()
