# Áp dụng lượt duyệt nhóm thứ hai, ngày 10/11/2026

Lần áp dụng này nhập ghi chú người dùng xuất từ bản đề xuất tự động và hai câu trả lời làm rõ trong hội thoại. Kết quả gộp các bước mua vé/nhận vé vào cùng sự kiện, giữ Festival riêng và bổ sung tên Chiến dịch Mùa hè xanh để nhận diện nhóm. Ghi chú người dùng, quyết định cặp do trợ lý áp dụng và tên hiển thị được lưu riêng theo [contract](../docs/interface.md#apply-local-group-review-notes).

## Đầu vào và quyết định đã làm rõ

File thực tế là `data/annotations/event-grouping-review-2026-11-06/user-notes/notes-2026-11-09-review-2.json`. Bản xuất lúc 23:45:24 ngày 09/11/2026, UTC+07:00, có 26 ghi chú: 25 `looks_ok` và một `needs_check`. Fingerprint khớp đúng assembly tại `reports/generated/automatic-grouping-2026-11-09-final/assembly.json`. Việc áp dụng được ghi lúc 00:00:05 ngày 10/11/2026, UTC+07:00; thời điểm từng ghi chú gốc giữ nguyên.

Số thứ tự và nội dung người dùng nhắc ban đầu không khớp. Sau khi đối chiếu ID và ACTION, người dùng chọn gộp nhóm 13 với nhóm 04, giữ nhóm 05 Festival riêng. Hai ACTION được giữ là mua vé Trọn gói và nhận vé xem phim. Mốc 18g00 ngày 22/3/2025 gắn với việc nhận vé; không chuyển nó thành lịch chiếu hoặc thời hạn sử dụng vé. Nguồn chưa cung cấp những mốc đó.

Với ghi chú Chiến dịch Mùa hè xanh, người dùng chọn bổ sung tên chiến dịch cho nhóm. Tên hiển thị lấy từ trích dẫn chính xác trong nguồn và có tác giả áp dụng AI; các hoạt động Lễ ra quân đã có được giữ nguyên. Không tạo thêm ACTION tham gia chiến dịch từ tên chương trình.

Phương án và câu trả lời nằm trong `review-2-resolution-2026-11-09/` thuộc gói annotation cục bộ. `prepare_review_2.py` tại gói tái tạo phương án vào thư mục trống; `--recorded-at` nhận thời điểm đã lưu trong receipt để tái tạo cùng nội dung. File xuất gốc không bị sửa.

## Cách áp dụng và đầu ra

[`apply_group_feedback`](../src/labeling/group_feedback.py) nhận một `GroupMergeResolution` tường minh, thay quyết định chưa rõ giữa hai mục bằng `SAME_EVENT` và `DIFFERENT_TASK`. Các cặp băng qua nhóm được thay hoặc thêm đầy đủ để không giữ cạnh mâu thuẫn. Việc đồng ý một nhóm không tự tạo nhãn cho các cặp ngoài nhóm đó.

[`apply_group_review.py`](../tools/apply_group_review.py) dựng lại bản đã xem từ Notice/Annotation và các quyết định cặp trước khi áp dụng. Lệnh trong [README](../README.md) ghi một thư mục mới với ghi chú/phương án gốc, ledger, assembly, các file nhóm, tên hiển thị và HTML. Nguồn, annotation, split và trang cũ giữ nguyên. Mỗi tên nhóm phải khớp trích dẫn thuộc một tài liệu thành viên; tên không thêm đầu việc và không sửa fingerprint assembly.

Bản bàn giao tại `reports/generated/group-review-2026-11-10-review-2/index.html`. Nhóm ưu đãi có ID `cc73b55921ab3d4cd8387560`, giữ hai đầu việc riêng. Các tên/ID nhóm cũ và ghi chú của cả hai nhóm được giữ trong ledger và `source_notes` của trang xem. Nhóm gộp hiển thị cần kiểm tra lại; 24 nhóm không đổi giữ trạng thái đồng ý từ bản xuất. Việc xác nhận nhóm không phê duyệt mọi span, vai trò thời gian hoặc quyền chia sẻ dữ liệu.

| Số đếm quy trình | Trước | Sau |
|---|---:|---:|
| Lần nhắc | 35 | 35 |
| Nhóm | 26 | 25 |
| Hoạt động/đầu việc | 30 | 30 |
| Quyết định cặp | 65 | 65 |
| Cập nhật được áp dụng | 1 | 1 |
| Mâu thuẫn bộ dựng nhóm báo | 0 | 0 |
| Tên nhóm có trích dẫn riêng | 0 | 1 |

Ledger có 24 ứng dụng `accepted` và hai ứng dụng `merged` tương ứng hai ghi chú cũ. Hai record cặp thay đổi: quan hệ giữa mua vé và nhận vé; bằng chứng/tác giả áp dụng cho cặp Chiến dịch Mùa hè xanh. Các quyết định suy ra có tác giả `ai_assistant`, không trở thành annotation cặp độc lập của con người. Quy tắc dự đoán tự động không được fit hoặc thay bằng các xác nhận này; đây là lượt áp dụng phản hồi có giám sát trên bản đã xem.

## Kiểm chứng

Môi trường Windows, Python 3.12.13, uv và dependency lock hiện có. Không thêm dependency, huấn luyện hoặc RNG. `run.json` lưu hashes của 14 file đầu vào/mã/template/lock; bằng chứng kiểm tra tại `reports/generated/group-review-2026-11-10-review-2-final-verification/verification.json`. Chạy lại cùng `--applied-at` vào thư mục mới cho 11 file giống từng byte.

| Kiểm tra | Kết quả |
|---|---|
| Bộ kiểm thử đầy đủ | 352 ca đạt |
| Ruff check và format check | Đạt |
| Offline demo | Chín tài liệu tổng hợp, năm annotation, 30 cặp; không có nhóm qua nhiều split |
| Bảo toàn ghi chú và nguồn | Bản xuất khớp từng byte; hashes của 14 đầu vào/mã khớp |
| Bảo toàn công việc | Mọi mention, 30 task và 109 fact giữ nguyên; mỗi mention thuộc đúng một nhóm |
| Gộp đúng phạm vi | Mua vé và nhận vé cùng nhóm, hai task; toàn bộ nhóm Festival không đổi |
| Tên chiến dịch | Khớp trích dẫn nguồn, không tạo task hoặc đổi annotation |
| Trạng thái giao diện | Giữ hai ghi chú gốc; nhóm gộp cần kiểm tra, cho phép ghi chú mới hơn thay trạng thái |
| JavaScript | Qua kiểm tra cú pháp và kiểm tra khởi tạo nhóm/tên/trạng thái bằng Node.js |

Lệnh kiểm thử dùng `uv run pytest -q -o cache_dir=tmp/pytest-cache --basetemp tmp/pytest-review2-complete`, với cache uv `tmp/uv-cache` và `--no-sync` trên môi trường đã cài. Một ca hồi quy bắt lỗi trạng thái giao diện trả cố định `looks_ok` khi nhập trạng thái cần kiểm tra; lỗi được sửa trước bản bàn giao. Ca chạy JavaScript trong pytest dùng Node.js khi có, bỏ qua nếu môi trường thiếu Node; trên máy này ca đã chạy và đạt.

Đây là kiểm chứng phần mềm và việc áp dụng góp ý, không đo chất lượng gom nhóm hoặc đồng thuận độc lập. Kiểm tra Node.js không thay cho kiểm tra hiển thị trực tiếp trên trình duyệt. Không có clearance riêng tư được tạo; dữ liệu và HTML chứa email tiếp tục nằm ngoài Git.
