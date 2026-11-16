# Kiểm tra split v3.3 và lập Group K-fold, ngày 16/11/2026

Lần kiểm tra này đối chiếu gói v3.3 với quyết định duyệt nhóm từ `notes-2026-11-09-review-3.json`. Hai nhóm sự kiện đã duyệt có tài liệu ở cả train và test, dù các nhóm tài liệu trong split đóng băng không đi qua nhiều tập. Bản chia thử giữ nguyên split gốc và loại phần train của hai nhóm xung đột khỏi kiểm định chéo.

## Cấu trúc và khả năng đọc dữ liệu

Gói `data/annotations/split_65_15_20_v3_3_2026-11-15/` có `assignments.jsonl` nối mỗi `doc_id` với nhóm, split và hash văn bản. Các thư mục theo split chứa Notice. Hai tập phát triển có Annotation; hai tập giữ lại có task trống để gán nhãn độc lập và hàng chờ kiểm tra. Thư mục `reference_only_do_not_train_on_test` chỉ được đối chiếu checksum trong lượt này.

| Split | Email | Web | Bản ghi nhãn hoặc task | Annotation bị schema hiện tại từ chối |
|---|---:|---:|---|---:|
| train | 281 | 122 | 403 Annotation | 367 |
| validation | 65 | 28 | 93 Annotation | 89 |
| test | 88 | 38 | 126 task chưa có nhãn hoặc dự đoán | Không nhập |
| domain_test | 0 | 62 | 62 task chưa có nhãn hoặc dự đoán | Không nhập |
| excluded | 0 | 0 | Không có | Không nhập |

Đủ 684 Notice khớp ID và hash văn bản trong assignment; đủ 25 checksum của gói khớp. Có 505 nhóm tài liệu, gồm 88 nhóm có nhiều tài liệu đang chờ duyệt. Không có ID trùng hay nhóm tài liệu gốc đi qua hai split. Hàng chờ test và domain_test có 0 tài liệu `gold_ready` trên 188 tài liệu.

Lỗi schema nằm ở `audience_constraints`: `scope`, `degree_levels`, `cohort_min`, `cohort_max` và `unrepresented` chưa được hợp đồng hiện tại chấp nhận, và một số phần tử `cohorts` là số thay vì chuỗi. Khi tách phần này chỉ trong bộ nhớ để kiểm tra cấu trúc, 5.766 span khớp offsets và 1.873 event ở train/validation có liên kết hợp lệ với văn bản. Không xuất annotation rút gọn hay kết luận các điều kiện đối tượng đúng nghĩa. Cần thống nhất hợp đồng phiên bản v3.3 trước khi đọc trực tiếp các annotation này để huấn luyện hoặc chạy grouping từ nhãn mới.

## Đối chiếu nhóm sự kiện với split

Tệp đính kèm khớp fingerprint `b26cab10db1c0a3349c984e50bc0c4619ec3b6f6c5f6595caae0ebf631c2e942` của `automatic-grouping-2026-11-09-final/assembly.json`. Cả 30 tài liệu trong assembly có hash văn bản khớp v3.3. Tệp ghi 26 nhóm `looks_ok`, trong đó chín nhóm nối nhiều email. Các quyết định dương trong snapshot gồm hai cặp nhắc lại và một cặp cập nhật. Đây là mẫu phát triển có hỗ trợ từ quy tắc và người dùng duyệt ở cấp nhóm; bản [chốt ngày 10/11](validation-2026-11-10-group-acceptance.md) có fingerprint khác.

Một mục `looks_ok` còn đề xuất thêm đầu việc. Bản chia dùng membership của nhóm đã xem. Đề xuất đó được giữ trong ghi chú gốc; muốn bổ sung đầu việc cần có ACTION và bằng chứng nguồn theo [quy trình grouping](../docs/event-grouping.md).

Hai thành phần đi qua train/test sau khi nối các nhóm tài liệu với chín liên kết đã duyệt. Phép chia thử loại hai tài liệu train thuộc các thành phần này. Cấu hình 5 fold, seed 42, Python 3.12.13 trên Windows cho kết quả:

| Fold dùng để validation | Tài liệu | Nhóm đánh giá |
|---:|---:|---:|
| 0 | 81 | 55 |
| 1 | 80 | 55 |
| 2 | 80 | 56 |
| 3 | 80 | 56 |
| 4 | 80 | 56 |

Trong 401 tài liệu có fold, không nhóm tài liệu gốc hay nhóm đánh giá đã nối nào đi qua hai fold. Bản đề xuất tự động trên batch email ngày 15/11 có 17 nhóm nhiều tài liệu: bốn nối qua các split gốc và một nối qua hai fold. Các đề xuất này đi vào hàng chờ riêng, không thay đổi fold. Ưu tiên kiểm tra các đề xuất vượt ranh giới trước khi chốt dữ liệu huấn luyện, rồi ghi nhận cách xử lý bằng một phiên bản split mới. Các trường hợp test đã xuất hiện trong mẫu phát triển cần được xử lý trước phép đo cuối cùng.

## Tái tạo và kiểm tra

Dùng [lệnh lập fold](../docs/evaluation.md#plan-group-k-fold-from-reviewed-events) với thư mục đích `reports/generated/group-cv-2026-11-16/`. Gói cục bộ có bảng fold, xung đột split, hàng chờ đề xuất, tham số và hash trong `run.json`. Lần chạy lại với một thư mục đích khác tạo sáu file giống từng byte. Script kiểm tra và số đếm nằm ở `reports/generated/group-cv-2026-11-16-validation/audit.py` và `audit.json`; chạy script từ thư mục gốc bằng uv.

Bộ kiểm thử có 361 ca đạt, Ruff và kiểm tra format đạt, demo tổng hợp chạy thành công. Các kết quả chỉ xác nhận cấu trúc, khả năng tái tạo và việc giữ nguyên các nhóm đã biết. Chưa có điểm chất lượng grouping, lượt duyệt toàn batch hoặc kết quả mô hình.
