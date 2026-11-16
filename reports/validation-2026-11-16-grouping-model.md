# Huấn luyện và đo mô hình gom nhóm, 16/11/2026

Hồi quy logistic đạt Macro-F1 0,785 trên 14 cặp kiểm định chéo và 0,400 trên 22 cặp email giữ lại có nhãn xác định. Cách đối chiếu theo độ giống từ đạt 0,844 và 0,575 trên cùng hai tập cặp. Lần chạy đo việc phân loại hai lần nhắc có cùng sự kiện hay không.

## Cấu hình và nguồn mẫu

Tập phát triển là bản [đóng băng từ v3.3](validation-2026-11-16-grouping-training.md) với 16 cặp email gồm 8 cặp cùng sự kiện hoặc cập nhật và 8 cặp khác sự kiện. Nhãn đến từ bản nhóm đã duyệt ở cấp nhóm và lượt đối chiếu nguồn của trợ lý. [Hồi quy logistic](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html) của scikit-learn 1.9.1 chạy trên CPU, Windows, Python 3.12.13. Tham số cố định gồm L2, `C=1.0`, bộ giải `lbfgs`, tối đa 1.000 vòng lặp, seed 42 và ngưỡng 0,5.

Sáu đặc trưng lấy từ bằng chứng nguồn của hai lần nhắc. Chúng gồm độ giao trên hợp của từ trong câu bằng chứng, của từ trong ACTION, và của nhóm ba ký tự trong ACTION, cùng ba tín hiệu về ngày trùng, ngày khác nhau ở cùng vai trò và liên kết web trùng. Từng lượt học hệ số chuẩn hóa và trọng số trên phần fit. Giữ 14 cặp có cả hai đầu cùng fold cho đánh giá ngoài tập fit. Hai cặp âm nằm ở hai fold khác nhau không có dự đoán ngoài fold. Sau kiểm định chéo, fit mô hình lưu trên đủ 16 cặp train. Phương pháp đối chiếu từ dự đoán cùng sự kiện khi độ giao trên hợp của từ trong bằng chứng đạt 0,5.

Từ 82 email ở split test có dự đoán trích xuất đã lưu, phép lấy mẫu xét 3.321 cặp tài liệu. Chọn 3 cặp trong cùng nhóm tài liệu, 14 cặp thuộc nhóm khác nhau theo độ giống nội dung cao và 6 cặp nền bằng seed 42. Chọn một cặp lần nhắc cho mỗi cặp tài liệu theo độ giống câu bằng chứng. Tổng cộng 23 cặp dùng 46 tài liệu khác nhau. Trợ lý đọc nguồn và chốt nhãn trước khi xem dự đoán trên mẫu này. Có 2 cặp cùng sự kiện, 20 cặp khác sự kiện và 1 cặp `UNCLEAR` nằm ngoài mẫu số khi tính điểm.

## Kết quả đo

Bảng 1 trình bày số dự đoán và Macro-F1. Macro-F1 lấy trung bình F1 của hai lớp, còn F1 cùng sự kiện chỉ tính lớp dương. Các hàng trong một chế độ dùng cùng tập cặp.

| Tập cặp | Phương pháp | Đúng / số cặp | Macro-F1 | F1 cùng sự kiện | Gộp nhầm | Bỏ sót |
|---|---|---:|---:|---:|---:|---:|
| Kiểm định chéo | Hồi quy logistic | 11/14 | 0,785 | 0,800 | 1 | 2 |
| Kiểm định chéo | So khớp từ | 12/14 | 0,844 | 0,889 | 2 | 0 |
| Email giữ lại | Hồi quy logistic | 11/22 | 0,400 | 0,154 | 10 | 1 |
| Email giữ lại | So khớp từ | 17/22 | 0,575 | 0,286 | 4 | 1 |
| Email giữ lại | Luôn dự đoán khác sự kiện | 20/22 | 0,476 | 0,000 | 0 | 2 |

Trên mẫu giữ lại, hồi quy logistic đánh dấu 11 cặp là cùng sự kiện và chỉ đúng một cặp. Sáu lỗi gộp nhầm nằm trong 13 cặp có nhãn xác định ở nhóm giống nội dung cao. Ba lỗi nữa nằm trong sáu cặp nền. Cả hai phương pháp đều bỏ sót cặp yêu cầu và phản hồi trong cùng luồng thư. Nhóm lớp âm chiếm 20/22 cặp. Độ chính xác 20/22 của cách luôn dự đoán khác sự kiện đi kèm việc bỏ sót cả hai cặp dương.

Hai mẫu số dương, 8 trong kiểm định chéo và 2 trong email giữ lại, giới hạn kết luận. Mẫu test chọn có chủ đích và dùng nhãn của trợ lý. Hai tập giữ lại chưa có tài liệu `gold_ready`. Kết quả phản ánh khả năng phân loại trên các cặp email đã chọn, chưa đủ để ước lượng chất lượng tổng quát, độ bao phủ tìm cặp, chất lượng gom cụm toàn bộ hoặc khả năng chuyển sang thông báo web. Trong lần chạy này, các điểm tại ngưỡng 0,5 ủng hộ việc giữ mô hình hồi quy ở mức thử nghiệm.

## Tái tạo lần chạy

Từ thư mục gốc, dùng nhóm phụ thuộc `models` và thư mục đích mới.

```powershell
uv run --group models python tools/run_grouping_model.py train `
  --dataset data/annotations/grouping-training-v3_3-2026-11-16 `
  --output-dir reports/generated/grouping-logistic-local
uv run --group models python tools/run_grouping_model.py evaluate `
  --dataset data/annotations/grouping-training-v3_3-2026-11-16 `
  --reviewed-holdout reports/generated/grouping-holdout-review-2026-11-16 `
  --test-notices data/annotations/split_65_15_20_v3_3_2026-11-15/test/notices.jsonl `
  --model-dir reports/generated/grouping-logistic-local `
  --output-dir reports/generated/grouping-logistic-holdout-local
```

Trọng số JSON và số đo gốc ở `reports/generated/grouping-logistic-2026-11-16/` và `reports/generated/grouping-logistic-holdout-2026-11-16/`. Hồ sơ chọn mẫu và quyết định có offsets ở `reports/generated/grouping-holdout-review-2026-11-16/`. Tệp `run.json` ghi hash dữ liệu, mã, lockfile, mô hình và tham số. Tệp `predictions.jsonl` lưu dự đoán theo ID để truy vết lỗi.

Lần chạy lại tạo năm tệp giống từng byte, gồm checkpoint, hai bảng dự đoán và hai bản ghi. Bộ kiểm thử có 364 ca đạt. Ruff, kiểm tra format, kiểm tra lockfile và demo offline đều đạt.
