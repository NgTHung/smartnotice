# Dựng nhóm sự kiện và đầu việc, ngày 06/11/2026

Lần chạy này sửa các điểm phát hiện trong lượt đọc nguồn và dựng nhóm từ 20 quyết định có tác giả `ai_assistant`. Đầu ra giữ riêng sự kiện, đầu việc/phiên, nguồn thông báo và lịch sử cập nhật theo [contract](../docs/interface.md#assemble-event-groups-and-tasks). Không có xác nhận của con người hoặc clearance riêng tư được tạo; kết quả là nhóm đề xuất trên mẫu phát triển.

## Sửa nhãn và ghi xác nhận

Đầu vào là bản nháp tại `data/annotations/event-grouping-review-2026-11-06/draft/`, gắn với các nguồn trong gói pilot. Bản nháp trước và prepared text giữ nguyên. Bản xác nhận mới nằm tại `confirmed-ai-v2/` trong cùng gói, có phiếu duyệt, canonical annotations, quyết định cặp và diễn giải thời gian.

Hai hạn KIT giữ trọn cụm chỉ một thời điểm, gồm toán tử “trước” hoặc “đến hết”; ngày và giờ ở cùng câu không tạo hai DEADLINE. Cặp `p007` ghi `REPEATED_NOTICE`, vì nguồn không xác định rõ lời nhắc. Bốn mốc cuối khoảng có diễn giải END trong đầu ra nhóm, không thêm vai trò mới vào Annotation. Ba span giờ/ngày của cùng buổi họp dùng khóa tương đương có tác giả sau khi đối chiếu nguồn; không sửa văn bản để ghép span qua hai câu.

Mỗi cặp có quyết định, quan hệ đầu việc/thông báo, tác giả, thời điểm có múi giờ, snapshots và bằng chứng nguồn. Tác giả được ghi là trợ lý, không phải người dùng. Các mẫu quyết định của con người và approval riêng tư được sao chép nguyên, vẫn chưa xác nhận.

## Phạm vi dựng nhóm

`annotations.full.jsonl` giữ 34 tài liệu và 170 sự kiện của bản nháp sau sửa. File `annotations.grouping.jsonl` lấy đúng 33 lần nhắc thuộc 20 cặp; 136 dự đoán lân cận chưa rà soát và một ứng viên tham gia ngoài các cặp không đi vào lần dựng nhóm. Hash annotation của tập con được tạo lại trước khi gắn vào quyết định.

| Số đếm quy trình | Kết quả |
|---|---:|
| Lần nhắc đầu vào | 33 |
| Quyết định cặp có xác nhận AI | 20 |
| Nhóm sự kiện, gồm nhóm đơn | 19 |
| Đầu việc hoặc phiên | 23 |
| Cập nhật hạn được áp dụng | 2 |
| Diễn giải mốc kết thúc | 4 |
| Span giờ/ngày được xác nhận tương đương | 3 |
| Mâu thuẫn bộ dựng nhóm báo trong lần chạy | 0 |
| Xác nhận con người hoặc clearance được tạo | 0 |

Đầu ra chính ở `data/processed/event-grouping-assembly-2026-11-06-v2/`. Mỗi nhóm và đầu việc giữ tất cả thành viên; các giá trị cũ có liên kết sang giá trị thay thế và không bị xóa. Các nhóm vẫn có `review_required=true` và `privacy_review_required=true`. Không thay đổi phân công tập dữ liệu hoặc dùng nhãn của mẫu để tính accuracy/F1.

## Kiểm chứng

Mã được thêm tại [`event_groups.py`](../src/labeling/event_groups.py), models tại [`schemas.py`](../src/schemas.py) và caller tại [`build_event_groups.py`](../tools/build_event_groups.py). Đây là bộ dựng nhóm từ quyết định đã cung cấp, không phải bộ phân loại tự động cặp sự kiện. Lệnh chạy nằm trong [README](../README.md); [quy trình](../docs/event-grouping.md#dựng-nhóm-từ-quyết-định-có-tác-giả) giải thích ý nghĩa các quan hệ và mâu thuẫn.

Môi trường Windows, Python 3.12.13; dùng uv, dependency lock hiện có và cache `tmp/uv-cache`. Không thêm dependency. Các record `run.json` lưu hashes đầu vào, mã, schema và lock, môi trường và loại người xác nhận. Lựa chọn mẫu không đổi; không có RNG hoặc tham số được fit trong lần dựng nhóm.

| Kiểm tra | Kết quả |
|---|---|
| Bộ kiểm thử đầy đủ | 302 ca đạt, gồm 21 ca cho bộ dựng nhóm |
| Ruff check và format check toàn repository | Đạt |
| Offline demo | 9 tài liệu tổng hợp, 5 annotation, 30 cặp; không có nhóm qua nhiều split |
| Nguồn bản nháp và Notice trước/sau | 15 file đầu vào không đổi; các checksums bản nháp khớp |
| Canonical annotations đầy đủ và tập con | Đạt validation cho 170 sự kiện đầy đủ và 33 lần nhắc được chọn |
| Bằng chứng giá trị trong nhóm | 99 offsets khớp prepared text |
| Thành viên nhóm/đầu việc | Mỗi lần nhắc thuộc đúng một nhóm và một đầu việc/phiên |
| Cập nhật và điều kiện | Hạn cũ KIT được giữ, hạn mới có hiệu lực trong đầu việc; giấy khám không kế thừa hạn phiếu |
| Các phiên chương trình | Ba phiên Future Leaders giữ một nhóm với ba đầu việc/phiên riêng |
| Các bước trong Festival | Bốn lần nhắc giữ một nhóm, hai đầu việc/phiên |
| Tái tạo cùng thời điểm xác nhận đã ghi | 12 file nội dung khớp từng byte |
| Xác nhận con người và approvals | Giữ nguyên mẫu chưa xác nhận |

Các kiểm thử tổng hợp bao gồm chuỗi đăng ký → nhắc → gia hạn → check-in, việc/phiên khác nhau, nghĩa vụ theo điều kiện, nhiều sự kiện trong một nguồn, cập nhật địa điểm/trạng thái, mâu thuẫn bắc cầu, ngày khác nhau thiếu cập nhật, hai cập nhật cạnh tranh và chuỗi quay về giá trị cũ. Kiểm thử cũng từ chối snapshots/quotes sai, TIME cập nhật không có annotation hỗ trợ, bản ghi trùng và vòng cập nhật. Những kiểm thử này không đo chất lượng nhóm trên corpus thực.

Lượt tái tạo lưu đầu vào tại `reports/generated/event-grouping-confirmed-ai-recheck/` và nhóm tại `reports/generated/event-grouping-assembly-recheck/`. Bằng chứng tổng hợp nằm tại `reports/generated/event-grouping-assembly-verification/verification.json`; script kiểm chứng ở gói cục bộ là `verify_assembly.py`. Metadata thời điểm chạy và checksums tương ứng thay đổi giữa hai lần tái tạo.

Không có mâu thuẫn được báo trong mẫu không chứng minh tiêu chí hoặc corpus đã hoàn chỉnh. Các ACTION liệt kê nhiều hoạt động cùng phiên được giữ ở mức hiện có; các nhóm/đầu việc cần con người kiểm tra trước khi dùng làm nhãn chuẩn, và dữ liệu thực vẫn chờ review riêng tư trước chia sẻ.
