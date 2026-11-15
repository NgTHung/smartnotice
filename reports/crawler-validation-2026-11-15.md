# Kiểm chứng bộ 250 thông báo học vụ, ngày 15/11/2026

[Bộ dữ liệu](../data/catalogs/hcmus-focused-250/README.md) gồm 100 bản ghi gốc và 150 thông báo HCMUS mới. Tổng theo nguồn là 190 HCMUS, 30 UIT và 30 UEH. Cả 150 thông báo bổ sung đến từ [trang thông tin dành cho người học của HCMUS](https://hcmus.edu.vn/thong-tin-danh-cho-nguoi-hoc/).

## Thu thập và rà nội dung

Crawler duyệt theo thứ tự trang danh sách, áp dụng bộ lọc tiêu đề học vụ và nội dung có hướng dẫn hoặc hành động. Lượt chạy tuân thủ robots.txt và giãn cách tối thiểu 2 giây giữa các yêu cầu đến cùng nguồn. Danh mục 100 bài gốc được dùng để loại URL và văn bản trùng ngay khi crawl.

Hai lượt HCMUS đưa ra 165 và 12 ứng viên sau lọc tự động. Lượt bổ sung dùng lại các trang đã lưu của lượt trước khi cần đối chiếu. Khi rà nội dung, loại 23 ứng viên, gồm 9 bài phụ thuộc tệp hoặc liên kết để đọc hướng dẫn, 5 bài tường thuật hoặc kế hoạch nội bộ, 3 bài có mâu thuẫn về thời gian trong nội dung và 6 bài có dấu hiệu chứa định danh hoặc thông tin liên hệ cần xử lý thêm. Chọn 150 trong số 154 ứng viên còn lại theo thứ tự thu thập.

## Kiểm tra 250 bài

| Kiểm tra | Kết quả |
|---|---|
| Số bản ghi khớp giữa văn bản, chỉ mục và danh mục nguồn | 250/250 |
| URL nguồn, mã tài liệu, mã băm văn bản gốc và mã băm văn bản chia sẻ duy nhất | 250/250 |
| Có ngày đăng trích từ trang nguồn, khớp giữa các tệp | 250/250 |
| Lược đồ dữ liệu, mã băm liên kết với nguồn và vị trí câu | 250/250 đạt |
| Phạm vi ngày đăng của cả bộ | 12/03/2021–05/11/2026 |
| Phạm vi ngày đăng của 150 bài mới | 02/07/2024–11/02/2026 |
| Độ dài văn bản của 150 bài mới | 157–9.216 ký tự, trung vị 2.119,5 |
| Cờ ngữ cảnh tệp đính kèm và ô bảng gộp trong 150 bài mới | 32 và 2 |

Đã phân tích lại HTML đã lưu của 100 bài gốc và 177 ứng viên mới để đối chiếu nguồn, ngày đăng, tiêu đề, nội dung và vị trí câu. Văn bản của bộ chia sẻ cũng qua kiểm tra dấu tiếng Việt và quét các mẫu số điện thoại, tên liên hệ đã cấu hình. Có 49 lượt che bổ sung ở 150 bài mới. Quét năm từ liên tiếp với độ tương đồng Jaccard từ 0,85 tìm thấy hai cặp gần trùng. Nội dung các cặp này áp dụng cho các học kỳ hoặc năm khác nhau.

Các thông báo cung cấp nội dung cho bước rà soát và gán nhãn, gồm đăng ký học phần, học bổng, học phí, nhận bằng và bảo hiểm y tế. Ngày đăng vẫn mang trạng thái ứng viên theo [quy trình thu thập](../docs/collection.md). Cờ tệp đính kèm và ô bảng gộp xác định những bài cần chú ý khi đọc. Nhóm vẫn cần xác minh ngày đăng và rà soát riêng tư theo quy trình trước khi dùng dữ liệu cho huấn luyện hoặc đánh giá.

```powershell
uv run python tools/check_notice_dataset.py --snapshot-dir data/catalogs/hcmus-focused-250 --expected-documents 250
```

Các số liệu và mã băm danh mục nguồn được lưu trong [validation.json](../data/catalogs/hcmus-focused-250/validation.json).
