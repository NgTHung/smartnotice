# Chốt lượt duyệt nhóm, ngày 10/11/2026

Người dùng xác nhận trong hội thoại đã hoàn thành lượt review cuối và chấp nhận toàn bộ nhóm. Lần ghi nhận này chốt 25 nhóm của bản sau [lượt duyệt thứ hai](validation-2026-11-10-group-review-2.md) làm bản tham chiếu phát triển. Không thay thành viên, đầu việc, trích xuất hoặc quyết định cặp.

## Phạm vi xác nhận

Xác nhận gắn với `reports/generated/group-review-2026-11-10-review-2/assembly.json`, fingerprint `8ffc81f3bcf534911b46ad28606b009bc5868d26e34c9d4cbcdef345cb4d1a7c`. Bản này có 25 nhóm, 35 lần nhắc và 30 đầu việc. Phát biểu của người dùng xác nhận phạm vi nhóm của snapshot này; không tạo annotation cặp độc lập, xác nhận mọi span hoặc clearance riêng tư.

`data/annotations/event-grouping-review-2026-11-06/accepted-2026-11-10/confirmation_receipt.json` giữ nguyên phát biểu, danh sách nhóm, fingerprint, source hashes và thời điểm ghi nhận. Thời điểm là lúc trợ lý ghi nhận xác nhận tổng thể, không phải thời điểm quan sát người dùng đọc từng nhóm. `normalized_notes.json` biểu diễn 25 nhóm bằng `looks_ok`; trường `draft=true` thuộc định dạng trao đổi, không thay thế bằng một ledger Label Studio. `plan.json` chỉ chấp nhận nhóm và giữ tên chiến dịch đã có.

Bản bàn giao đã chốt nằm tại `reports/generated/group-review-2026-11-10-accepted/`. `index.html` hiển thị 25 nhóm được đồng ý; `feedback_application.json` giữ việc áp dụng với tác giả trợ lý. Assembly và các quyết định cặp giữ nguyên tác giả trước đó. Các bản xuất trình duyệt, lượt áp dụng trước và ghi chú riêng được giữ nguyên.

## Kiểm tra lần ghi nhận

Dùng script cục bộ `record_final_acceptance.py` trong gói annotation để tạo ghi chú từ phát biểu tường minh, rồi dùng `tools/apply_group_review.py` với đúng snapshot. Lệnh dựng lại assembly từ nguồn trước khi áp dụng và từ chối ghi đè thư mục. `--recorded-at` và `--applied-at` nhận thời điểm trong receipt/run khi cần tái tạo vào thư mục mới.

| Kiểm tra | Kết quả |
|---|---|
| Xác nhận | Đủ 25 ứng dụng `accepted`, trạng thái `looks_ok`; không còn nhóm thiếu xác nhận trong ledger này |
| Thành viên và đầu việc | 35 lần nhắc, 30 đầu việc giữ nguyên |
| Assembly và quyết định cặp | Khớp bản trước; fingerprint không đổi |
| Tên hiển thị | File nhãn nguồn giữ nguyên từng byte |
| Trang xem | Payload chứa đủ 25 trạng thái đồng ý, khớp assembly |
| Bảo toàn | Checksums của bản trước và bản chốt khớp; nguồn/mã khớp hashes trong run |

`accepted-2026-11-10/verification.json` lưu kết quả kiểm tra. Môi trường dùng Windows, Python 3.12.13, uv và dependency lock hiện có; không thêm dependency hoặc thay mã package trong lần ghi nhận này. Các kiểm thử phần mềm của thay đổi trước được ghi trong báo cáo lượt duyệt thứ hai; không chạy lại bộ kiểm thử cho thay đổi dữ liệu/ghi nhận này.

Lượt duyệt trên bộ mẫu này đã đóng. Dùng bản chốt để kiểm tra hồi quy khi phát triển tiếp; các thay đổi thành viên hoặc dữ liệu mới cần lượt duyệt đúng phạm vi thay đổi. Bản chốt đã tham gia phát triển, không phải tập đánh giá độc lập và không cung cấp số đo chất lượng mô hình. HTML, ghi chú và dữ liệu tham chiếu tiếp tục nằm ngoài Git.
