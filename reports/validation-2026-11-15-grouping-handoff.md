# Kiểm tra thao tác và bàn giao duyệt grouping, ngày 15/11/2026

Lượt này kiểm tra thao tác của trang grouping trước khi người dùng đọc nguồn và đưa ra quyết định. Đầu vào là bản [mở rộng trên 434 email](validation-2026-11-15-full-grouping.md) tại commit `0f1782a`, với 1.611 nhóm đề xuất. Trang bàn giao bổ sung lối đọc bốn tài liệu có dự đoán rỗng để kiểm tra phần trích xuất bỏ sót.

## Phương pháp và kết quả

Sau khi được cấp quyền, công cụ Computer Use mở được Chrome nhưng dừng tại bước nhập đường dẫn vì cơ chế kiểm soát truy cập không xác định chắc chắn URL hiện tại trên Windows. Việc kiểm tra logic được tiếp tục bằng Node.js `v24.12.0`, chạy nguyên JavaScript của trang trong `node:vm` với DOM và bộ nhớ lưu ghi chú được mô phỏng trong bộ nhớ. Kiểm tra bố cục, xuống dòng, kích thước và tương tác trực tiếp trên trình duyệt tiếp tục cần người dùng mở trang.

Chín kịch bản sau đạt trên payload của batch đầy đủ.

| Kịch bản | Kết quả |
|---|---|
| Khởi tạo batch | Đủ 1.611 nhóm trong danh sách |
| Lọc và tìm kiếm | Lọc nhiều email, tìm theo ID và trạng thái kết quả rỗng hoạt động |
| Nhóm ưu tiên | Dựng nội dung đầu việc của đủ 74 nhóm |
| Giá trị đầu việc | Thao tác xem nguồn chuyển về email và đánh dấu đúng vùng trích dẫn |
| Hiện nguồn | Điều khiển toàn văn và đánh dấu trích xuất cập nhật trạng thái |
| Bằng chứng cặp | Thao tác xem trong email chuyển về vùng nguồn |
| Lưu ghi chú | Ghi chú kiểm thử được đọc lại khi khởi tạo lại môi trường mô phỏng |
| Xuất ghi chú | Đúng loại bản ghi, trạng thái nháp, ID nhóm và fingerprint assembly |
| Lỗi lưu trữ | Ghi chú trong phiên tiếp tục xuất được khi mô phỏng lỗi quota |

Các ghi chú kiểm thử chỉ tồn tại trong bộ nhớ mô phỏng, với nội dung đánh dấu kiểm thử phần mềm. Ledger của người dùng và bản assembly giữ nguồn tác giả trước đó. Bằng chứng tại `reports/generated/grouping-handoff-2026-11-15/javascript-verification.json`; script `check_viewer.cjs` trong cùng thư mục tái tạo phép kiểm tra.

## Bàn giao cho người duyệt

Mở `reports/generated/grouping-handoff-2026-11-15/index.html` để đi tới trang duyệt toàn batch, danh sách nhóm ưu tiên và toàn văn bốn tài liệu có dự đoán rỗng. Trang nguồn tĩnh dùng HTML đã escape, chính sách nội dung giới hạn tải tài nguyên và giữ dữ liệu cục bộ. `manual-review-manifest.json` lưu hashes và phạm vi bàn giao.

Danh sách 74 nhóm gồm 19 nhóm nhiều lần nhắc và 57 nhóm có giá trị cần đối chiếu, với hai nhóm thuộc cả hai loại. Trong đó, 15 nhóm nối qua nhiều nhóm tiền xử lý. Người duyệt cần xác nhận danh tính sự kiện, cách tách đầu việc và vai trò các mốc thời gian, rồi xuất ghi chú từ trang grouping. Nhãn span hoặc phần trích xuất cần bổ sung được ghi theo đoạn nguồn và ID tài liệu.

Bốn task dự đoán rỗng tại `data/annotations/event-grouping-pilot-2026-11-05/zero_prediction_tasks.json` khớp bản ghi gốc trong batch đầy đủ. Các Notice tương ứng được đưa vào trang bàn giao để đọc cục bộ. Việc quyết định có công việc bị bỏ sót và việc duyệt riêng tư cần người đọc nguồn thực hiện.

Các lần mở trang và kiểm thử thao tác giới hạn ở chức năng phần mềm. Nhãn cặp độc lập và phép đo chất lượng cần quy trình theo [hướng dẫn annotation](../docs/annotation.md) và [đánh giá](../docs/evaluation.md). Đối chiếu split lịch sử tiếp tục cần snapshot đã ghi nhận trong báo cáo tiền xử lý; sau khi chốt nhãn có thể lập một phiên bản split mới với grouping và seed được lưu đầy đủ.

Tái tạo từ thư mục gốc bằng các lệnh sau.

```powershell
node reports/generated/grouping-handoff-2026-11-15/check_viewer.cjs
uv run --offline --no-sync python reports/generated/grouping-handoff-2026-11-15/prepare_manual_review.py
```

Nguồn, bản grouping và chín hash đầu ra được kiểm tra khi dựng trang bàn giao. Mã package và quy tắc grouping trong lượt này giữ phiên bản đã commit; kiểm tra tài liệu dùng liên kết cục bộ và `git diff --check`.
