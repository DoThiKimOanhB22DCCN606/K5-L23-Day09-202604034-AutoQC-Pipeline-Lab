"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict

import yaml

from ..common import ERROR, parse_yolo_line


def fix(ds, issues, cfg):
    drop_codes = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
    remove_codes = {
        "DUP_IMAGE_EXACT", "DUP_IMAGE_NEAR", "LEAK_TEST",
        "CORRUPT_IMAGE", "BAD_SIZE",
    }
    errors = [issue for issue in issues if issue.severity == ERROR]
    fixes = []
    removed = set()

    for issue in errors:
        if issue.code in remove_codes:
            removed.add(issue.image)

    for stem in sorted(removed):
        image_path = ds.image_path(stem)
        label_path = ds.label_path(stem)
        if image_path is None and not label_path.exists():
            continue
        if image_path is not None:
            image_path.unlink()
        if label_path.exists():
            label_path.unlink()
        fixes.append({
            "image": stem, "line": "", "action": "remove_image",
            "before": "ảnh và nhãn trong dataset làm việc", "after": "đã loại",
        })

    line_actions = defaultdict(set)
    missing_labels = set()
    rename_classes = any(issue.code == "BAD_CLASS_NAME" for issue in errors)
    for issue in errors:
        if issue.image in removed:
            continue
        if issue.code == "MISSING_LABEL_FILE":
            missing_labels.add(issue.image)
        elif issue.line is not None and issue.code in drop_codes | {"BOX_OUT_OF_IMAGE"}:
            line_actions[(issue.image, issue.line)].add(issue.code)

    for stem in sorted(missing_labels):
        if ds.image_path(stem) is not None and not ds.label_path(stem).exists():
            fixes.append({
                "image": stem, "line": "", "action": "needs_label",
                "before": "(không có file)", "after": "chuyển người gán",
            })

    by_file = defaultdict(dict)
    for (stem, line_no), codes in line_actions.items():
        if "BAD_FORMAT" in codes or "BAD_CLASS_ID" in codes or "BOX_ZERO" in codes or "DUP_BOX" in codes:
            by_file[stem][line_no] = "drop_line"
        elif "BOX_OUT_OF_IMAGE" in codes:
            by_file[stem][line_no] = "clip_box"

    for stem in sorted(by_file):
        label_path = ds.label_path(stem)
        if not label_path.exists():
            continue

        original = label_path.read_text(encoding="utf-8", errors="replace")
        lines = original.splitlines()
        output = []
        changed = False

        for line_no, text in enumerate(lines, 1):
            action = by_file[stem].get(line_no)
            if action == "drop_line":
                fixes.append({
                    "image": stem, "line": line_no, "action": "drop_line",
                    "before": text, "after": "",
                })
                changed = True
                continue

            if action == "clip_box":
                try:
                    cls, cx, cy, width, height = parse_yolo_line(text)
                except ValueError:
                    output.append(text)
                    continue

                left, top = cx - width / 2, cy - height / 2
                right, bottom = cx + width / 2, cy + height / 2
                clipped_left, clipped_top = max(0.0, left), max(0.0, top)
                clipped_right, clipped_bottom = min(1.0, right), min(1.0, bottom)
                clipped_width = clipped_right - clipped_left
                clipped_height = clipped_bottom - clipped_top

                if clipped_width <= 0 or clipped_height <= 0:
                    fixes.append({
                        "image": stem, "line": line_no, "action": "drop_line",
                        "before": text, "after": "",
                    })
                    changed = True
                    continue

                clipped_cx = (clipped_left + clipped_right) / 2
                clipped_cy = (clipped_top + clipped_bottom) / 2
                after = (
                    f"{cls} {clipped_cx:.6f} {clipped_cy:.6f} "
                    f"{clipped_width:.6f} {clipped_height:.6f}"
                )
                output.append(after)
                if after != text:
                    fixes.append({
                        "image": stem, "line": line_no, "action": "clip_box",
                        "before": text, "after": after,
                    })
                    changed = True
                continue

            output.append(text)

        if changed:
            content = "\n".join(output)
            if output and original.endswith(("\n", "\r")):
                content += "\n"
            label_path.write_text(content, encoding="utf-8")

    if rename_classes:
        yaml_path = ds.yaml_path
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) if yaml_path.exists() else {}
        if not isinstance(data, dict):
            data = {}
        old_names = data.get("names", "(không có names)")
        expected_names = dict(enumerate(cfg["classes"]))
        current_names = ds.yaml_names()
        if current_names != expected_names:
            data["names"] = expected_names
            yaml_path.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            fixes.append({
                "image": "data.yaml", "line": "", "action": "rename_classes",
                "before": str(old_names), "after": str(cfg["classes"]),
            })

    return fixes
