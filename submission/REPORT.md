# Báo cáo Day 09 — Đỗ Thị Kim Oanh, 202604034

## 1. Kết luận trước
Pipeline kết luận **Hold**. Có 224 ảnh raw; intake giữ 202 và loại 22. Dataset clean_v1 được xuất dưới dạng bản nháp Hold, có 202 ảnh và 0 lỗi bắt buộc còn lại, nhưng 38/202 ảnh vẫn có cảnh báo (18.8%), cao hơn ngưỡng Hold 10%.

## 2. Lỗi và phân việc
Số dưới đây là số issue theo mã trong `02_error_list_v1.csv`; một ảnh có thể có nhiều issue.

| Mã lỗi | Số ảnh/dòng | Ai xử lý | Cách xử lý |
|---|---:|---|---|
| `CORRUPT_IMAGE` | 2 | Máy | Intake loại ảnh không đọc được. |
| `BAD_SIZE` | 3 | Máy | Intake loại ảnh có cạnh ngắn dưới 250 px. |
| `DUP_IMAGE_EXACT` | 8 | Máy | Loại ảnh trùng byte. |
| `DUP_IMAGE_NEAR` | 4 | Máy | Loại ảnh gần trùng theo pHash. |
| `LEAK_TEST` | 5 | Máy | Loại ảnh trùng tập test/val. |
| `BAD_CLASS_ID`, `BAD_FORMAT`, `BOX_ZERO`, `DUP_BOX` | 6, 3, 4, 7 | Máy | Autofix xóa dòng nhãn lỗi; ghi từng thay đổi vào `03_fixes.csv`. |
| `BOX_OUT_OF_IMAGE` | 8 | Máy, rồi người kiểm | Autofix cắt box vào ảnh; hàng đợi ưu tiên các ảnh có sửa dòng. |
| `BAD_CLASS_NAME` | 2 | Máy | Autofix chuẩn hóa tên lớp trong `data.yaml`. |
| `MISSING_LABEL_FILE` | 6 | Người | Máy không bịa nhãn; chuyển người gán. |
| `POSSIBLE_WRONG_CLASS`, `POSSIBLE_MISSING`, `POSSIBLE_FALSE_POS`, `POSSIBLE_LOOSE_BOX` | 18, 53, 29, 28 | Người | Đây là cảnh báo ngữ nghĩa từ mô hình/nhãn, không tự sửa. |
| `BOX_TINY`, `BOX_HUGE`, `EMPTY_LABEL`, `CLASS_RARE` | 6, 3, 12, 4 | Người xem | Cảnh báo kích thước, ảnh không có box, hoặc mất cân bằng lớp cần ngữ cảnh dữ liệu. |

`05_review_queue.csv` có 125 ảnh; ảnh đầu hàng `img_0020` có ưu tiên 11.524 vì đồng thời có dòng bị xóa, nghi thiếu box và nghi sai lớp. Các ảnh thiếu nhãn được cộng trọng số `NEEDS_LABEL` cao (10). Ngân sách mô phỏng đã duyệt 80/125 ảnh; 74/80 ảnh được duyệt có ít nhất một cảnh báo ngữ nghĩa, tổng cộng 88 lượt cờ ngữ nghĩa (các loại có thể chồng lặp trên cùng ảnh).

## 3. Calibration (2 ngưỡng)
| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | 14 | `DUP_IMAGE_EXACT`: 1.00/1.00 → 1.00/1.00; `DUP_IMAGE_NEAR`: 1.00/0.50 → 1.00/0.67 | Chọn mức thấp hơn 16 để tránh xóa nhầm ảnh: kiểm tra cặp raw do ngưỡng 16 gắn cờ cho thấy `img_0008` (trượt tuyết) và `img_0011` (tennis) không phải ảnh trùng. |
| `second_opinion.conf` | 0.25 | 0.6 | `WRONG_CLASS`: 0.56/0.83 → 0.62/0.83; `MISSING`: 0.50/1.00 → 0.57/1.00; `LOOSE_BOX`: 0.29/0.40 → 0.20/0.20 | Tăng ngưỡng giữ recall của wrong-class và missing, tăng precision; đổi lại bỏ sót thêm loose-box. `FALSE_POS` giữ 0.31/1.00 vì dùng ngưỡng `fp_conf` riêng. |

Calibration có thể đánh lừa: tại `phash_dist=16`, calibration vẫn báo precision 1.00 nhưng trên raw cặp `img_0008`/`img_0011` (trượt tuyết/tennis) và `img_0113`/`img_0177` (người đàn ông ngồi bàn ăn/surfer) rõ ràng không trùng. Vì vậy chọn 14 để tránh xóa nhầm; ở ngưỡng cuối, tôi mở xem 4 cặp bị gắn cờ (`img_0076`/`img_0042`, `img_0143`/`img_0037`, `img_0186`/`img_0061`, `img_0223`/`img_0077`), đều là cùng cảnh/ảnh gần trùng. Intake loại 22/224 ảnh. Calibration chỉ có 6 near-duplicate trong 39 ảnh (mỗi ca làm recall đổi khoảng 16.7 điểm phần trăm) và không có ca `LEAK_TEST`, nên không bảo đảm ngưỡng sẽ tổng quát hóa cho raw.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
Chạy kiểm chứng với work directory riêng để giữ nguyên kết quả chạy chính:

```powershell
python -m pipeline.run --budget 0 --work work\work_gate_nb --reports work\rep_nb --export-dir work\exp_nb
```

Kết quả: còn 6 lỗi bắt buộc do ảnh thiếu file nhãn, kết luận **Rework**, mã thoát 20 và không tạo `work\exp_nb\clean_v1`. Đây là hành vi mong muốn: máy không tự tạo nhãn giả khi không có người duyệt.

Hai điểm mù có số liệu: ở ngưỡng `second_opinion.conf=0.6`, calibration chỉ bắt được 1/5 box lỏng (recall 0.20); ở `phash_dist=14`, recall near-duplicate là 0.67, tức bỏ sót 2/6 ca cài lỗi. Ngưỡng pHash cao hơn lại có thể báo nhầm cặp ảnh không liên quan, nên cảnh báo máy vẫn cần người xem.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
**Chưa chạy** phần train raw-vs-clean; đây là phần Colab tùy chọn và chưa có kết quả train trong lần làm này. Vì vậy không đưa ra kết luận mAP.

## 6. Quyết định và ghi chú AI
- **Quyết định:** Hold. Để tiến tới Release cần người xử lý các cảnh báo còn lại; hiện 38/202 ảnh có cảnh báo, cần giảm xuống tối đa 20/202 (≤10%) và chạy lại pipeline.
- **Prompt chính:** yêu cầu triển khai bốn module theo docstring và test có sẵn, theo TDD; sau đó calibrate ngưỡng và chạy pipeline.
- **Cách kiểm:** chạy toàn bộ pytest (79 passed), chạy pipeline, kiểm tra báo cáo/export và xem trực quan các cặp ảnh bị pHash gắn cờ.
- **Một lần AI sai:** lần đầu cân nhắc ngưỡng pHash 16 dựa vào điểm calibration; xem ảnh raw phát hiện cặp không liên quan bị gắn cờ, nên hạ xuống 14.
