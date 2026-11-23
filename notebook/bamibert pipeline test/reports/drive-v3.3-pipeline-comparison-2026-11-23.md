# So sánh pipeline SmartNotice trên dữ liệu Drive v3.3 ngày 23/11/2026

Pipeline đạt F1 sự kiện cao nhất trên validation dùng mẫu thông báo và mẫu câu để trích xuất sự kiện, rồi dùng BamiBERT để phân loại mức áp dụng. Trên 126 thông báo test thường, pipeline khớp 84 liên kết và 6 sự kiện đầy đủ. BamiBERT ban đầu khớp 13 liên kết và 9 sự kiện đầy đủ. Pipeline mới tăng độ chính xác khi nối đối số nhưng bỏ sót 462 trong 468 sự kiện tham chiếu.

## Dữ liệu và cách chọn

Lần chạy tải mới các tệp từ bản phát hành Drive. Trình chạy kiểm tra SHA-256, thành phần nhóm, nguồn thật, schema và khoảng ký tự. Tập train có 403 thông báo thuộc 281 nhóm. Validation có 93 thông báo thuộc 77 nhóm. Chỉ số chọn là F1 sự kiện đúng toàn bộ, dùng micro-F1 liên kết khi hòa. Tất cả phương án dùng cùng bộ phân loại mức áp dụng, 24 hồ sơ tổng hợp và seed 42 cho lần so sánh chính. Bảng 1 ghi điểm trước khi mở văn bản test và nhãn tham chiếu để chấm. Điểm validation (`reports/generated/drive-improvement-20261123/validation.json`), cấu hình đã chốt và hash (`reports/generated/drive-improvement-20261123/selected.json`).

| Phương án | F1 cụm | F1 liên kết | F1 sự kiện | F1 đồng thời sự kiện và nhãn áp dụng |
|---|---:|---:|---:|---:|
| BamiBERT ban đầu, trọng số dương 8 | 7,52% | 0,82% | 0,59% | 0,59% |
| BamiBERT huấn luyện lại, trọng số dương 2 | 12,37% | 0,61% | 0,30% | 0,30% |
| Bộ gán nhãn token theo ngữ cảnh | 10,11% | 1,05% | 0,59% | 0,59% |
| Thêm mẫu câu train | 17,70% | 7,66% | 2,75% | 2,05% |
| Thêm mẫu toàn thông báo train | 18,44% | 10,16% | 3,62% | 2,24% |

Bảng 1. Kết quả trên cùng 357 sự kiện validation. Điểm sự kiện đòi hỏi khớp chính xác công việc, đối số, vai trò và ngày chuẩn hóa. Các lượt BamiBERT dùng LoRA trên RTX 3050 Ti. Trọng số dương là hệ số của ví dụ dương trong hàm mất mát nhận diện cụm. Các ngưỡng liên kết thử cho mỗi phương án dùng đặc trưng ngữ cảnh là 0,35, 0,50 và 0,65. Lần huấn luyện trọng số 2 (`reports/generated/drive-improvement-20261123/weight2/run.json`), lịch sử epoch (`reports/generated/drive-improvement-20261123/weight2/extraction_history.json`).

## Pipeline đã chọn

1. Bộ gán nhãn học một mô hình tuyến tính cho từng kiểu cụm. Mỗi token được gán nhãn bắt đầu, bên trong hoặc ngoài cụm dựa trên các từ lân cận, cặp từ, kiểu chữ và nguồn email/web.
2. Với câu có độ tương đồng cosine từ 0,65, mô hình tìm câu train gần nhất bằng đặc trưng chuỗi 3–5 ký tự. Hai biên của cụm phải ánh xạ được sang token trong câu mới. Các câu dưới ngưỡng dùng bộ gán nhãn token.
3. Khi độ tương đồng toàn thông báo đạt 0,60, mô hình đối chiếu thứ tự token và chuyển các cụm cùng liên kết có đầu mút tương ứng. Với những cặp còn lại, hồi quy logistic theo từng kiểu đối số dùng khoảng cách, vị trí câu và ngữ cảnh. Ngưỡng liên kết đã chốt là 0,65.
4. Mỗi sự kiện giữ bằng chứng theo khoảng ký tự của thông báo mới. Bộ chuẩn hóa ngày dùng quy tắc ngày số của dự án. BamiBERT nhận bằng chứng sự kiện và hồ sơ để dự đoán một trong ba nhãn mức áp dụng.

## Kết quả trên test thường

Lần chấm dùng 88 email và 38 thông báo web thuộc 118 nhóm. Thư mục test chứa văn bản và hàng đợi gán nhãn. Sau khi chốt mô hình, trình chấm đối chiếu dự đoán với bản chú giải lịch sử có máy hỗ trợ theo đúng 126 mã tài liệu test. Ràng buộc chú giải chỉ dùng sinh nhãn áp dụng silver để tính điểm. Tập web chuyển miền gồm 62 thông báo vẫn được giữ riêng. Tập test thường này đã được dùng để đo hai pipeline. Bản phát hành ghi `gold_ready=false` và chưa hoàn thành duyệt nhóm thủ công. Kết quả và hash test (`reports/generated/drive-improvement-20261123/test.json`).

| Chỉ số | BamiBERT ban đầu | Pipeline đã chọn |
|---|---:|---:|
| F1 cụm đúng kiểu và vị trí | 7,45% | 19,54% |
| F1 liên kết từ cụm dự đoán | 1,36% | 9,97% |
| Liên kết đúng / dự đoán / tham chiếu | 13 / 767 / 1.149 | 84 / 536 / 1.149 |
| F1 sự kiện đúng toàn bộ | 0,31% | 1,48% |
| Sự kiện đúng / dự đoán / tham chiếu | 9 / 5.271 / 468 | 6 / 343 / 468 |
| Precision / recall sự kiện | 0,17% / 1,92% | 1,75% / 1,28% |
| Ngày tường minh đúng đầu cuối | 0 / 188 | 16 / 188 |
| F1 đồng thời sự kiện và nhãn áp dụng | 0,31% | 0,87% |

Bảng 2. So sánh đã chốt trên test thường. Trong 20 liên kết dự đoán khớp ở nhóm có ngày tường minh, 16 ngày được chuẩn hóa đúng. Cả hai hệ thống đều bỏ sót ba liên kết có ngày suy ra. Điểm đồng thời tính trên 11.232 cặp tham chiếu. Với pipeline đã chọn, 85 trong 8.232 cặp dự đoán khớp cả sự kiện và nhãn.

Chênh lệch F1 sự kiện là +1,17 điểm phần trăm. Khoảng percentile 95% là +0,09 đến +2,47 điểm khi lấy mẫu lại có hoàn lại 118 nhóm test theo cặp, 5.000 lượt, seed 42. Khoảng này thể hiện biến thiên theo nhóm test trong bộ dữ liệu đang dùng. Sai khác giữa nhãn lịch sử và nhãn độc lập vẫn chưa được đo. Kết quả theo nguồn và khoảng chênh lệch (`reports/generated/drive-improvement-20261123/paired_events.json`).

Pipeline khớp 24/139 liên kết hạn chót `DEADLINE`, 5/61 liên kết bắt đầu `START` và 5/113 liên kết thời điểm sự kiện `EVENT_TIME`. Trong các liên kết giấy tờ `DOCUMENT`, chỉ 1/174 khớp. Theo nguồn, pipeline tìm đúng toàn bộ 3/346 sự kiện email và 3/122 sự kiện web trên tập test thường. Các mẫu chuyển từ train sang thông báo mới vẫn cần được đối chiếu với văn bản trước khi dùng để nhắc hạn.

## Độ ổn định trên dữ liệu phát triển

Sau khi chốt cấu hình, năm lượt GroupKFold trên 496 thông báo train và validation huấn luyện lại bộ gán nhãn, bộ nối đối số và cả hai chỉ mục mẫu từ phần train của từng lượt. Với seed 42, F1 sự kiện trung bình là 2,33% với độ lệch chuẩn mẫu 0,82 điểm phần trăm. F1 liên kết trung bình là 7,58% với độ lệch chuẩn 1,53 điểm. Đây là kiểm tra độ ổn định của cấu hình đã chọn trên cùng tập phát triển. Khi giữ nguyên phép chia 403/93 và đổi seed huấn luyện qua 42, 43, 44, F1 sự kiện trên validation đạt trung bình 3,69% với độ lệch chuẩn 0,17 điểm. Các lượt này chỉ huấn luyện lại phần trích xuất. Kết quả từng fold và seed (`reports/generated/drive-improvement-20261123/stability.json`), [mã tái lập](../../../tools/check_template_stability.py).

## Chạy dự đoán

Từ thư mục gốc dự án, dùng môi trường uv của thí nghiệm. Tham số `--notices` nhận tệp JSONL gồm các bản ghi Notice đã chuẩn bị. Tham số `--output` nhận đường dẫn thư mục mới. Lệnh sau minh họa trường hợp có một hồ sơ sinh viên tổng hợp. Bỏ `--profile`, `--base` và `--baseline` để chỉ trích xuất sự kiện.

```powershell
uv run --no-project --python tmp/bamibert-gpu/Scripts/python.exe python tools/predict_template_pipeline.py --run reports/generated/drive-improvement-20261123 --notices path/to/notices.jsonl --profile path/to/profile.json --base tmp/bamibert-checkpoint --baseline reports/generated/bamibert/v3_3-2026-11-23-final-seed42 --output path/to/new-predictions
```

Trình chạy ghi `events.jsonl` theo hợp đồng Annotation và `applicability.jsonl` gồm mã tài liệu, mã sự kiện, mã hồ sơ và nhãn dự đoán. Bộ trích xuất và chỉ mục mẫu nằm trong checkpoint đã chọn (`reports/generated/drive-improvement-20261123/documents.joblib`). Bộ phân loại dùng adapter BamiBERT (`reports/generated/bamibert/v3_3-2026-11-23-final-seed42/applicability.pt`) và BamiBERT gốc theo revision và hash đã ghi (`reports/generated/bamibert/v3_3-2026-11-23-final-seed42/run.json`).

Để tái lập phép so sánh trong một thư mục kết quả mới, chạy lượt huấn luyện trọng số 2 (`reports/generated/drive-improvement-20261123/weight2/retrain.ps1`) với `-Split`, `-Base` và `-Output` trỏ đến thư mục con `weight2` mới. Chạy [trình so sánh](../../../tools/compare_notice_pipelines.py) lần lượt với các bước `fit`, `templates`, `documents` và `select`. Mỗi bước nhận cùng các tham số `--split`, `--base`, `--baseline` và `--output`. Bước `test` kiểm tra lại hash của mô hình và mã so với cấu hình chốt trước khi chấm.
