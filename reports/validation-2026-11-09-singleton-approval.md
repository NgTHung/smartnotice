# Xác nhận nhóm đơn, ngày 09/11/2026

Người dùng chỉ đạo đánh dấu tất cả nhóm đơn là duyệt đồng ý trong hội thoại. Lần áp dụng này ghi nhận xác nhận ở cấp nhóm trên bản kết quả sau góp ý ngày 09/11/2026; không thay thành viên nhóm, nhãn trích xuất hoặc quyết định cặp. [Bản ghi trước](validation-2026-11-09-group-feedback.md) giữ nguyên phạm vi review tại thời điểm đó.

## Phạm vi xác nhận

Đầu vào là `data/processed/event-grouping-user-reviewed-2026-11-09/assembly.json`, có 22 nhóm, 35 lần nhắc và 25 hoạt động/đầu việc. Chọn các nhóm có đúng một email nguồn: 13 nhóm, gồm toàn bộ 12 nhóm chỉ có một lần nhắc và một nhóm có hai mục trong cùng email. Trong số đó có chín nhóm đơn trước đây chưa có ghi chú.

Ledger mới nằm tại `data/annotations/event-grouping-review-2026-11-06/singleton-approvals-2026-11-09/`. `instruction_receipt.json` giữ chỉ đạo, tiêu chí chọn nhóm, fingerprint và danh sách ID. `normalized_notes.json` biểu diễn 13 xác nhận bằng `looks_ok`; `feedback_application.json` ghi việc áp dụng với tác giả trợ lý. Thời điểm là lúc ghi nhận chỉ đạo, không phải bằng chứng người dùng đọc riêng từng nhóm. Không tạo annotation cặp độc lập của con người hoặc clearance riêng tư.

Trang xem tại `reports/generated/group-review-2026-11-09-approved/index.html` kết hợp ledger góp ý trước và ledger xác nhận nhóm đơn. Cả 22 nhóm có thông tin góp ý đã áp dụng; 13 nhóm một email hiển thị xác nhận đồng ý. Những ghi chú trình duyệt mới hơn có thể thay trạng thái hiển thị; nội dung ghi chú cũ được giữ khi áp dụng xác nhận mới. File xuất review gốc và các trang cũ không bị ghi đè.

## Kiểm chứng và lưu trong Git

Lần chạy dùng Windows, Python 3.12.13, uv và dependency lock hiện có. Không dùng RNG, huấn luyện hoặc lựa chọn tham số. Hash đầu vào và thời điểm lưu trong `run.json`; kết quả kiểm tra cục bộ nằm tại `reports/generated/group-singleton-approval-verification/verification.json`.

| Kiểm tra | Kết quả |
|---|---|
| Xác nhận nhóm đơn | 13 nhóm một email được `looks_ok`, đủ 12 nhóm một lần nhắc và chín nhóm chưa có ghi chú |
| Nguồn và kết quả dựng nhóm | Hash đầu vào khớp; assembly và mọi quyết định cặp giữ nguyên |
| Phạm vi riêng tư | Cờ yêu cầu duyệt và yêu cầu duyệt riêng tư của nhóm được giữ |
| Kiểm thử gom nhóm, áp dụng góp ý và xuất trang | 33 ca đạt |
| Bộ kiểm thử đầy đủ | 314 ca đạt |
| Ruff check và format check | Đạt |
| Offline demo | Chín tài liệu tổng hợp, năm annotation, 30 cặp; không có nhóm qua nhiều split |
| JavaScript | Qua kiểm tra cú pháp; kiểm tra xác nhận mặc định, giữ nội dung ghi chú và ưu tiên ghi chú mới hơn |
| Quy tắc Git | Trang HTML sinh ra, browser archives và file xuất ghi chú bị bỏ qua; template nguồn và HTML tổng hợp phục vụ parser được giữ |

Lệnh kiểm thử đầy đủ dùng `uv run pytest -q -o cache_dir=tmp/pytest-cache --basetemp tmp/pytest-singleton-approval-20261109`. Lượt đầu với thư mục tạm Windows mặc định có lỗi quyền truy cập khi tạo fixture; lượt dùng thư mục trong workspace đạt đủ 314 ca. Cache uv đặt tại `tmp/uv-cache` và chạy `--no-sync` trên môi trường đã cài.

Template chung được lưu tại `tools/templates/group_review.html.template`; nó chứa vị trí nhúng dữ liệu, không chứa email mẫu thực. Các trang đã nhúng email, ledger và dữ liệu review nằm trong thư mục cục bộ được Git bỏ qua. Các kiểm tra trên xác minh phần mềm và việc ghi nhận chỉ đạo; không đo độ chính xác gom nhóm. Kiểm tra JavaScript không thay cho kiểm tra hiển thị trực tiếp trên trình duyệt.
