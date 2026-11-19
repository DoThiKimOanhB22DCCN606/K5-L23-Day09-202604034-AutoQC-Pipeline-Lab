"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |

Gợi ý
- Mép trái = x - w/2, mép phải = x + w/2 (xem câu hỏi "dòng YOLO nào lỗi?" trong slide).
- Một dòng hỏng (BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO) thì `continue`, đừng kiểm tiếp hình học của dòng đó.
- Dòng thiếu cột làm script của slide dừng giữa chừng: đây là lý do phải `try/except`.
- `iou_xywh(a, b)` có sẵn trong common.py.
- Ngưỡng nằm trong `cfg["label_format"]` — đừng viết cứng số vào code.
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line  # noqa: F401


def run(ds, cfg):
    settings = cfg["label_format"]
    issues = []

    for label_file in ds.label_files():
        stem = label_file.stem
        image_size = ds.image_size(stem)
        previous_boxes = []

        for line_no, text in ds.read_label_lines(stem) or []:
            try:
                cls, cx, cy, width, height = parse_yolo_line(text)
            except ValueError as exc:
                issues.append(Issue(
                    "label_format", ERROR, "BAD_FORMAT", stem,
                    f"dòng nhãn không hợp lệ: {exc}", line_no,
                ))
                continue

            if not 0 <= cls < len(ds.classes):
                issues.append(Issue(
                    "label_format", ERROR, "BAD_CLASS_ID", stem,
                    f"id lớp {cls} ngoài khoảng 0..{len(ds.classes) - 1}", line_no,
                    extra={"class_id": cls},
                ))
                continue

            if width <= 0 or height <= 0:
                issues.append(Issue(
                    "label_format", ERROR, "BOX_ZERO", stem,
                    "chiều rộng và chiều cao phải lớn hơn 0", line_no,
                    extra={"width": width, "height": height},
                ))
                continue

            box = (cx, cy, width, height)
            left, top = cx - width / 2, cy - height / 2
            right, bottom = cx + width / 2, cy + height / 2
            overflow = max(0.0, -left, -top, right - 1, bottom - 1)
            if overflow > settings["overflow_tol"]:
                issues.append(Issue(
                    "label_format", ERROR, "BOX_OUT_OF_IMAGE", stem,
                    f"box tràn khỏi ảnh {overflow:.6g}", line_no,
                    extra={"overflow": overflow},
                ))

            if any(
                previous_cls == cls and iou_xywh(previous_box, box) > settings["dup_box_iou"]
                for previous_cls, previous_box in previous_boxes
            ):
                issues.append(Issue(
                    "label_format", ERROR, "DUP_BOX", stem,
                    "box gần như trùng với một dòng nhãn trước đó", line_no,
                ))
            previous_boxes.append((cls, box))

            if image_size is not None:
                width_px, height_px = image_size
                short_side = min(width * width_px, height * height_px)
                if short_side < settings["min_box_px"]:
                    issues.append(Issue(
                        "label_format", WARN, "BOX_TINY", stem,
                        f"cạnh ngắn {short_side:.2f}px < {settings['min_box_px']}px", line_no,
                        extra={"short_side_px": short_side},
                    ))

            if width * height > settings["max_box_frac"]:
                issues.append(Issue(
                    "label_format", WARN, "BOX_HUGE", stem,
                    f"box chiếm {width * height:.6g} diện tích ảnh", line_no,
                    extra={"area_frac": width * height},
                ))

    return issues
