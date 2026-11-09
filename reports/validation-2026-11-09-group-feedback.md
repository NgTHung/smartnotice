# Áp dụng góp ý gom nhóm, ngày 09/11/2026

Lần chạy này áp dụng ghi chú người dùng xuất từ trang HTML và hai câu trả lời làm rõ trong hội thoại. Bản ghi giữ riêng góp ý ở cấp nhóm, cách diễn giải của trợ lý và các quyết định cặp được suy ra. Kết quả là một phiên bản nhóm đề xuất để đối chiếu, không phải nhãn cặp độc lập của con người hoặc số đo chất lượng gom nhóm.

## Đầu vào và phạm vi review

File `data/annotations/event-grouping-review-2026-11-06/user-notes/notes-2026-11-09.json` có 10 ghi chú: tám `looks_ok` và hai `suggest_split`. Fingerprint `c7d68092f0f2c12e4f4b4394509666b67a01da718a5785a8f6fec10e7b2410ef` khớp đúng bản assembly dùng để xuất trang HTML. Bản xuất ghi nhận lúc 21:41:05 ngày 09/11/2026, UTC+07:00. Giữ nguyên file xuất và thời điểm từng ghi chú; không thay `draft=true` bằng một xác nhận khác.

Chín nhóm đơn cũ không có trong file xuất được giữ ở trạng thái chưa có ghi chú người dùng. Việc chấp nhận một nhóm không tự xác nhận tất cả span, mốc thời gian, cặp bên ngoài nhóm hoặc quyền chia sẻ dữ liệu. Hai câu trả lời làm rõ xác định tách riêng cả ba chuyên đề và tách từng mục của email có ưu đãi xem phim cùng lịch Festival.

## Cách áp dụng

| Góp ý | Xử lý |
|---|---|
| Ba chuyên đề Future Leaders | Tách thành ba nhóm độc lập; thay các cạnh gộp băng qua phần đã tách và thêm cặp phân biệt còn thiếu |
| Email ưu đãi xem phim và lịch Festival | Giữ mục lịch Festival ở nhóm Festival; bổ sung hai lần nhắc có sẵn trong annotation đầy đủ vào nhóm ưu đãi/nhận vé riêng |
| Nhận diện chiến dịch Mùa hè xanh | Bổ sung tên đầy đủ của chiến dịch năm 2025 vào bằng chứng; ngày ra quân đóng vai trò hỗ trợ |
| Phiếu sức khỏe và gia hạn | Giữ nhóm đã được chấp nhận; biểu diễn gia hạn bằng cập nhật hạn của việc thực hiện phiếu, giữ việc nộp giấy khám theo điều kiện riêng |

Giờ nhận vé xem phim không được chuyển thành lịch chiếu phim. Nguồn không nêu lịch chiếu cụ thể. Ba chuyên đề có tên và lịch tham dự riêng; ngữ cảnh cùng chương trình không buộc chúng vào một sự kiện. [Quy trình gom nhóm](../docs/event-grouping.md) bổ sung ranh giới này và cách áp dụng ghi chú.

`apply_group_feedback` trong [`group_feedback.py`](../src/labeling/group_feedback.py) kiểm tra fingerprint, nhận phương án tách tường minh và giữ ghi chú gốc trong ledger. Nó không đoán các phần cần tách từ văn bản tự do. Các quyết định cặp được thay hoặc tạo bởi quá trình áp dụng có tác giả `ai_assistant`; không gán chúng thành review cặp độc lập của người dùng. [Contract](../docs/interface.md#apply-local-group-review-notes) định nghĩa các record.

Bản đầu vào mới nằm tại `data/annotations/event-grouping-review-2026-11-06/user-reviewed-2026-11-09/`. `feedback_application.json` giữ 10 ghi chú và kết quả áp dụng; `resolution_plan.json` giữ phương án và hai lựa chọn trong hội thoại. `snapshot_migrations.jsonl` ghi việc gắn lại hash cho lần nhắc cũ khi mở rộng tập annotation, sau khi kiểm tra nội dung event, argument và span không đổi.

## Kết quả dựng nhóm

| Số đếm quy trình | Trước | Sau |
|---|---:|---:|
| Lần nhắc đưa vào dựng nhóm | 33 | 35 |
| Nhóm, gồm nhóm đơn | 19 | 22 |
| Hoạt động hoặc đầu việc | 23 | 25 |
| Quyết định cặp trong đầu vào | 20 | 22 |
| Cập nhật hạn được áp dụng | 2 | 2 |
| Mâu thuẫn bộ dựng nhóm báo | 0 | 0 |

Hai lần nhắc bổ sung lấy từ nguồn và dự đoán đã có; không thu thập email mới. File annotation đầy đủ giữ 34 tài liệu và 170 sự kiện; tập con đưa vào gom nhóm có 35 lần nhắc. Nguồn, offsets, phiên bản cũ và phân công tập dữ liệu giữ nguyên.

Đầu ra ở `data/processed/event-grouping-user-reviewed-2026-11-09/`. Trang xem mới ở `reports/generated/group-review-2026-11-09-user-reviewed/index.html`. Trang hiển thị mọi nhóm, tên chuyên đề và các đoạn liên quan đến mục đang xét; có nút bật toàn văn. Các bằng chứng của cặp khác nhóm được xem trong phần lý do, không tự thêm nội dung sự kiện khác vào phần trích đoạn của nhóm hiện tại.

Trang ánh xạ 10 góp ý gốc tới 13 nhóm kết quả sau tách, kèm nguyên văn ghi chú và lý do áp dụng. Đây là cách hiển thị nguồn gốc của kết quả, không phải 13 lượt review mới. Ghi chú bổ sung được lưu theo fingerprint mới. Trang cũ và các ghi chú trình duyệt gắn với bản cũ không bị ghi đè.

## Kiểm chứng

Môi trường Windows, Python 3.12.13; dùng uv và dependency lock hiện có, không thêm dependency. Cache là `tmp/uv-cache`. Các file `run.json`, checksums và bằng chứng kiểm chứng lưu hashes đầu vào, mã, template và lock. Không có RNG, huấn luyện hoặc tối ưu tham số trong lần chạy này.

| Kiểm tra | Kết quả |
|---|---|
| Bộ kiểm thử đầy đủ | 314 ca đạt, gồm 7 ca áp dụng góp ý và 5 ca xuất HTML |
| Ruff check và format check | Đạt |
| Offline demo | 9 tài liệu tổng hợp, 5 annotation, 30 cặp; không có nhóm qua nhiều split |
| Bảo toàn đầu vào | Sáu file đầu vào không đổi; file review khớp fingerprint assembly gốc |
| Annotation đầy đủ và tập con | Qua validation cho 170 sự kiện và 35 lần nhắc được chọn |
| Bằng chứng giá trị trong nhóm | 109 offsets khớp nguồn |
| Thành viên | Đủ mọi lần nhắc cũ và hai lần nhắc bổ sung; mỗi lần thuộc đúng một nhóm và một hoạt động/đầu việc |
| Phân nhóm theo góp ý | Ba chuyên đề thành ba nhóm; phần lịch Festival và phần ưu đãi nằm ở hai nhóm tương ứng |
| Bảo toàn cập nhật | Hai cập nhật hạn vẫn áp dụng; giấy khám không kế thừa hạn phiếu |
| Tái tạo | 13 file nội dung, gồm HTML, khớp từng byte |
| JavaScript | Qua `node --check`; kiểm tra đích bằng chứng cho hai mục trong cùng email trỏ đúng chuyên đề sau tách |
| Ghi chú và quyền chia sẻ | Góp ý gốc giữ nguyên; không tạo clearance hoặc nhãn cặp độc lập của con người |

Kiểm tra HTML trong lượt này gồm cấu trúc dữ liệu, cú pháp JavaScript và hàm chọn đích bằng chứng; không có kiểm chứng giao diện trực tiếp trong trình duyệt. Kiểm thử phần mềm và việc không báo mâu thuẫn không thiết lập accuracy/F1, đồng thuận độc lập hoặc tính ẩn danh của corpus.

Script curation và kiểm chứng nằm trong gói cục bộ: `apply_user_notes.py`, `verify_user_feedback.py`. Tái tạo dùng thời điểm áp dụng đã ghi trong `run.json` và chọn thư mục đầu ra mới. Bản đối chiếu nằm tại `reports/generated/group-feedback-2026-11-09-verification/verification.json`; các bản tái tạo đầu vào, nhóm và HTML nằm dưới `reports/generated/`. Những dữ liệu này được Git bỏ qua và vẫn chờ review riêng tư trước chia sẻ.
