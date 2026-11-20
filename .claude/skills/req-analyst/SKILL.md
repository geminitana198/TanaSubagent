---
name: req-analyst
description: Phân tích requirement (txt, md, docx, pptx, xlsx/xlsm, csv, pdf) thành hệ thống tri thức có back-link, rồi tạo tài liệu tổng quan hệ thống, mockup, artifact HTML, estimation và proposal bằng các subagent — luôn hỏi người dùng trước (dịch sang tiếng Việt? làm deliverable nào? tham số?). Dùng khi người dùng đưa tài liệu yêu cầu/RFP/spec và muốn phân tích, dịch, dựng KB, ước lượng, báo giá, làm proposal/mockup, hoặc hỏi lại nghiệp vụ dự án đã phân tích; ví dụ "/req-analyst", "phân tích requirement trong thư mục X", "dịch tài liệu yêu cầu", "làm estimate cho RFP này", "viết proposal", "nghiệp vụ X trong dự án là gì".
---

# req-analyst — Requirement → Tri thức → Deliverable

Session hiện tại là **điều phối viên (orchestrator)**: hỏi người dùng, chạy script, giao việc cho subagent,
kiểm tra kết quả. Không tự viết hàng loạt nội dung mà subagent đảm nhận.

- `S` = `.claude/skills/req-analyst` (script ở `S/scripts`, mẫu ở `S/templates`)
- `WS` = workspace dự án, mặc định `req-workspace/<project-slug>/` ở thư mục gốc project

```
WS/
  00_input/            (tùy chọn) bản sao file requirement
  01_extracted/        Markdown trích xuất + manifest.json (hash, phát hiện file đổi)
  02_translated/       <slug>.vi.md + _new_terms/ (thuật ngữ mới đề xuất)
  glossary.md          bảng thuật ngữ — nguồn chuẩn cho mọi bản dịch & deliverable
  kb/                  hệ thống tri thức: modules, features, actors, rules, entities, screens,
                       integrations, nfr, processes, questions, assumptions, decisions, sources
                       + index.md, _lint.md (sinh tự động)
  deliverables/        overview/ mockups/ artifact/ estimation/ proposal/
  state.json           giai đoạn hiện tại + mọi quyết định/câu trả lời của người dùng
```

Subagent (trong `.claude/agents/`): `ra-translator`, `ra-kb-builder`, `ra-overview-writer`,
`ra-mockup-designer`, `ra-artifact-builder`, `ra-estimator`, `ra-proposal-writer`, `ra-kb-qa`.

## Nguyên tắc bắt buộc

1. **Hỏi trước khi làm.** Mỗi Gate dưới đây dùng `AskUserQuestion` và *chờ* câu trả lời. Không đoán thay
   người dùng những thứ ảnh hưởng tới kết quả (dịch hay không, deliverable nào, đơn giá, tech stack…).
2. **Mọi câu trả lời ghi vào `WS/state.json` → `decisions`** (kèm ngày) và với câu trả lời nghiệp vụ thì tạo
   note `D-xxx` trong KB để lần sau không hỏi lại.
3. **Truy vết.** Mọi khẳng định trong KB/deliverable phải dẫn về `[[SRC-...]]` + mốc vị trí
   (`[p12]`, `[slide3]`, `[sheet:Tên] Row 5`, `[page2]`) hoặc về `[[D-xxx]]`. Không có nguồn → ghi là
   giả định `AS-xxx` hoặc câu hỏi `Q-xxx`, không trình bày như sự thật.
4. **Không bịa số liệu.** Estimation/proposal chỉ dùng tham số người dùng đã duyệt.
5. Subagent chạy song song khi độc lập (gửi nhiều lệnh `Agent` trong cùng một message). Truyền cho subagent
   đường dẫn `WS`, danh sách file cần làm, và các quyết định liên quan — subagent không thấy hội thoại này.
6. Báo tiến độ ngắn gọn cho người dùng sau mỗi giai đoạn; trả lời bằng tiếng Việt.

## Bước 0 — Nhận diện tình huống

- Nếu `WS/state.json` đã tồn tại → đọc `phase` và `decisions`, **tiếp tục** từ chỗ dở, không hỏi lại điều đã chốt.
- Nếu người dùng chỉ **hỏi nghiệp vụ** của dự án đã có KB → nhảy tới *Chế độ hỏi đáp*.
- Nếu người dùng đưa **phiên bản mới** của tài liệu → *Cập nhật khi requirement thay đổi*.

## Gate G0 — Hỏi ngay từ đầu (bắt buộc, trước khi đọc nội dung)

Liệt kê nhanh các file requirement (tên, loại, dung lượng) rồi hỏi bằng **một** `AskUserQuestion`:

1. **Dịch sang tiếng Việt?** — "Có, dịch sát nghĩa kèm thuật ngữ chuyên ngành (Khuyến nghị nếu tài liệu
   không phải tiếng Việt)" / "Không dịch" / "Chỉ tạo bảng thuật ngữ". Luôn hỏi câu này kể cả khi tài liệu
   có vẻ đã là tiếng Việt (có thể lẫn tiếng Anh/Nhật).
2. **Deliverable cần tạo** (multiSelect): Tổng quan hệ thống · Mockup · Artifact HTML · Estimation · Proposal.
   (KB luôn được tạo.)
3. **Tên dự án / lĩnh vực nghiệp vụ** (ví dụ: ngân hàng, logistics, y tế, bán lẻ) — giúp chọn thuật ngữ.
4. **Ngôn ngữ deliverable**: Tiếng Việt / Tiếng Anh / Song ngữ / Tiếng Nhật.

Ghi vào `state.json`, rồi:

```bash
python3 .claude/skills/req-analyst/scripts/kb.py init <WS>
python3 .claude/skills/req-analyst/scripts/extract.py <thư mục hoặc file requirement> <WS>
```

Đọc JSON kết quả; file `failed` → báo người dùng (ví dụ .doc cần LibreOffice, PDF scan cần OCR qua skill `pdf`).
File ảnh/sơ đồ nhúng không trích được chữ — ghi chú lại, có thể đọc ảnh bằng `Read` nếu người dùng gửi riêng.

## Giai đoạn 1 — Bảng thuật ngữ & dịch (chỉ khi G0 chọn dịch / tạo glossary)

1. Giao **một** `ra-translator` chế độ `glossary`: đọc toàn bộ `01_extracted/`, lập `WS/glossary.md`
   (thuật ngữ gốc → tiếng Việt thống nhất, viết tắt, định nghĩa theo ngữ cảnh dự án, nguồn, trạng thái
   `đề xuất`/`cần xác nhận`).
2. **Gate G1 — xác nhận thuật ngữ:** trình bày tối đa ~15 thuật ngữ *mơ hồ / có nhiều cách dịch* (đánh dấu
   `cần xác nhận`) và hỏi người dùng chọn cách dịch. Cập nhật glossary thành `đã duyệt`.
3. Giao `ra-translator` chế độ `translate` **song song**, mỗi agent 1 file (file lớn > ~1500 dòng: chia theo
   khoảng dòng/heading, mỗi agent một phần, ghi `<slug>.part-N.vi.md` rồi ghép). Agent ghi thuật ngữ mới vào
   `02_translated/_new_terms/<slug>.md`; sau khi xong, orchestrator gộp vào glossary (hỏi người dùng nếu xung đột).
4. Kiểm tra mẫu: mỗi bản dịch giữ đủ mốc vị trí `[pN]`/`[slideN]`/Row, bảng đủ số dòng, không bỏ đoạn.

## Giai đoạn 2 — Xây hệ thống tri thức có back-link

1. Giao `ra-kb-builder`. Tài liệu ít (< ~3000 dòng tổng): 1 agent. Nhiều hơn: chia theo **nhóm file/ phân hệ**,
   mỗi agent một nhóm, và chỉ định trước dải ID cho từng agent (ví dụ agent 1: F-001..F-099, agent 2: F-100..F-199)
   để không trùng ID. Sau đó chạy thêm 1 `ra-kb-builder` chế độ `consolidate` để gộp note trùng nghĩa và nối link chéo.
2. Chạy và đọc kết quả:
   ```bash
   python3 .claude/skills/req-analyst/scripts/kb.py index <WS>
   ```
   `kb/_lint.md` phải: 0 liên kết hỏng; mọi note nghiệp vụ có `[[SRC-...]]`; nguồn "chưa khai thác" được giải thích.
   Nếu chưa đạt → gửi lại `ra-kb-builder` danh sách cần sửa.
3. Báo người dùng: số note theo loại (từ `kb/index.md`), số câu hỏi mở.

## Gate G2 — Làm rõ nghiệp vụ (trước mọi deliverable)

Đọc `kb/questions/` và `kb/assumptions/`. Trình bày cho người dùng các câu hỏi **quan trọng nhất** (ảnh hưởng
phạm vi/effort), nhóm theo module, mỗi câu kèm giả định đề xuất. Hỏi bằng `AskUserQuestion`
(tối đa 4 câu/lần; nhiều hơn thì liệt kê dạng bảng và cho chọn "Chấp nhận toàn bộ giả định đề xuất" /
"Tôi sẽ trả lời từng câu" / "Gửi khách hàng trước, tạm dừng").
Với mỗi câu trả lời: tạo `D-xxx` (nguồn = người dùng, ngày), đổi `Q-xxx` sang `status: answered` và link
`[[D-xxx]]`, cập nhật note bị ảnh hưởng; giả định được chấp nhận → `AS-xxx status: accepted`. Chạy lại `kb.py index`.

## Gate G3 — Hỏi tham số cho từng deliverable đã chọn (trước khi giao subagent)

Chỉ hỏi phần của deliverable được chọn; có thể gộp vào 1–2 lần `AskUserQuestion`:

| Deliverable | Cần hỏi |
|---|---|
| Tổng quan hệ thống | Đối tượng đọc (khách hàng / nội bộ dev), mức chi tiết, có đề xuất kiến trúc & tech stack không (nếu có: stack nào) |
| Mockup | Nền tảng (web / mobile / cả hai), độ trung thực (wireframe xám / có màu theo brand), màn hình nào (tất cả / ưu tiên Must) |
| Artifact HTML | Nội dung (tổng quan + sơ đồ + chức năng + mockup + estimation?), có publish thành Artifact link riêng tư không |
| Estimation | Phương pháp (WBS bottom-up 3 điểm / Function Point / Use Case Point), đơn vị (man-day/hour/month), vai trò & đơn giá, tiền tệ, % buffer, % PM/QA overhead, phạm vi giai đoạn (có gồm BA/thiết kế/UAT/triển khai/bảo hành không) |
| Proposal | Tên công ty gửi & khách hàng nhận, mô hình hợp đồng (trọn gói / T&M / ODC), điều khoản thanh toán, định dạng (Markdown / .docx / Claude Doc / slide) |

Ghi tham số estimation vào `WS/deliverables/estimation/estimation_config.json` (khởi tạo từ
`S/templates/estimation_config.example.json` rồi thay bằng giá trị người dùng đã chọn — xóa các mục không dùng).

## Giai đoạn 3 — Tạo deliverable bằng subagent

Thứ tự phụ thuộc:
```
overview ─┬─► artifact (cần overview, mockup; estimation nếu có)
mockup  ──┤
estimation ─► Gate G4 duyệt ─► proposal (cần overview + estimation đã duyệt)
```
- Đợt 1 (song song): `ra-overview-writer`, `ra-mockup-designer`, `ra-estimator`.
- **Gate G4 — duyệt estimation:** trình bày `estimation_summary.md` (tổng effort, chi phí, theo module/vai trò,
  top rủi ro, giả định chính) và hỏi: "Duyệt" / "Điều chỉnh (nêu thay đổi)" / "Ước lượng lại phần …".
  Điều chỉnh → gửi lại `ra-estimator` (dùng SendMessage nếu agent còn) rồi chạy lại `estimate.py`.
- Đợt 2 (song song): `ra-proposal-writer` (sau G4), `ra-artifact-builder`.
- Artifact: subagent chỉ tạo file `deliverables/artifact/index.html`. **Orchestrator** mới publish bằng tool
  `Artifact` — chỉ khi người dùng đã đồng ý ở G3; nạp skill `artifact-design` trước khi publish.
- Proposal dạng .docx → sau khi có Markdown, dùng skill `anthropic-skills:docx`; dạng Claude Doc → skill `anthropic-skills:docs`.

Kiểm tra trước khi báo xong: mọi link `[[ID]]` trong deliverable tồn tại trong KB; số liệu proposal khớp
`estimation_summary.json`; mockup mở được (`deliverables/mockups/index.html`). Cập nhật `state.json.phase = "done"`.

## Chế độ hỏi đáp nghiệp vụ (dùng nhiều lần)

Khi người dùng hỏi lại nghiệp vụ ("quy tắc hủy đơn thế nào?", "F-012 liên quan màn hình nào?"):
1. Tra nhanh: `python3 .claude/skills/req-analyst/scripts/kb.py search <WS> <từ khóa VN> <thuật ngữ gốc>`
   (tra `glossary.md` để có cả thuật ngữ gốc), rồi `kb.py show <WS> <ID>` để có note + liên kết 2 chiều.
2. Câu đơn giản → tự trả lời. Câu cần tổng hợp nhiều note → giao `ra-kb-qa` (rẻ, chỉ đọc).
3. Câu trả lời luôn kèm `[[ID]]` và nguồn gốc (file + mốc vị trí). Nếu KB không có → nói rõ "tài liệu chưa đề cập",
   đề xuất tạo `Q-xxx`; nếu người dùng trả lời luôn → tạo `D-xxx` và `kb.py index`.

## Cập nhật khi requirement thay đổi

1. Chạy lại `extract.py` (nó so hash, chỉ trích xuất file mới/đổi) rồi `kb.py impact <WS>` → danh sách note bị ảnh hưởng
   qua back-link từ `SRC-...`.
2. Hỏi người dùng có dịch lại file đổi không; giao `ra-translator` cho đúng các file đó.
3. Giao `ra-kb-builder` chế độ `update` với danh sách file + note bị ảnh hưởng (note đổi → `status: changed` + dòng lịch sử).
4. `kb.py index`, báo deliverable nào cần làm lại và hỏi người dùng trước khi làm lại.
   (So sánh chi tiết từng ô/đoạn giữa hai bản: có thể dùng skill `dcia-orchestrator` nếu người dùng muốn.)
