# Kiểm tra che tên trên lần chạy dàn dựng, ngày 04/11/2026

Bản ghi này cho biết bộ lọc che tên sinh viên và cán bộ tốt đến đâu trên 434 email, trước và sau khi sửa. Dữ liệu và thiết lập giống [lần chạy làm sạch](validation-2026-11-04-cleaning-run.md): chưa có tham chiếu đồng ý thật và chưa có người duyệt riêng tư. Các con số này thay thế số `[NAME]` và số lần che trong bản ghi đó.

Kiểm tra dùng quy tắc, không có nhãn vàng do người gán. Vì vậy số liệu là ước lượng, không phải precision hay recall. Kết quả không chứng minh văn bản đã ẩn danh.

## Phương pháp

Ứng viên tên là chuỗi từ viết hoa bắt đầu bằng họ tiếng Việt, được phân loại theo ngữ cảnh. Ứng viên mạnh là ứng viên có mọi từ phần tên xuất hiện trong tên ở header của corpus. Che thừa được phát hiện qua các cụm từ chung và các từ thường gặp ở dạng chữ thường nhưng không có trong tên header nào.

Tên thật chỉ nằm trong tệp CSV riêng dưới `tmp/cleaning-run-2026-11-04/reports/`. Không có văn bản nào được gửi tới nhà cung cấp mô hình LLM để gán nhãn. Một lần kiểm tra trong phiên làm việc có in mảnh tên một phần vào hội thoại với trợ lý AI, vì bộ lọc từ thông thường của nó quá rộng. Lần kiểm tra sau đã thay bộ lọc đó và chỉ in các từ không có trong tên header nào.

## Kết quả

| Chỉ số | Trước | Sau |
|---|---|---|
| `[NAME]` trong toàn corpus | 234 | 281 |
| Tài liệu có `[NAME]` | 122 | 126 |
| `[NAME] học` (dấu hiệu che nhầm `Trường Đại học`) | 109 | 0 |
| Tài liệu đọc được `Trường Đại học` | 64 | 134 |
| Tài liệu đọc được `Việt Nam` | 22 | 34 |
| Tên học từ mẫu trong nội dung | 150 | 1 |
| Ứng viên mạnh cùng dòng với MSSV | 8 | 0 |
| Ứng viên mạnh sau từ chỉ sinh viên | 12 | 0 |
| Ứng viên mạnh sau chức danh cán bộ | 113 | 0 |
| Ứng viên mạnh dạng dòng chữ ký | 1 | 0 |
| Ứng viên mạnh trong nội dung khác | 64 | 12 |
| Tài liệu có ít nhất một ứng viên mạnh | 111 | 14 |

Sau khi sửa, 278 lần che theo ngữ cảnh chủ yếu dài ba hoặc bốn từ, gồm 136 và 87 lần. Có 13 lần che ở 10 cụm chứa một từ phổ biến không có trong tên header nào; đây có thể là che thừa.

Thay đổi quy tắc làm đổi văn bản của 218 tài liệu. Offset câu vẫn khớp trên toàn bộ 8.526 câu, không có nguồn bị từ chối, và vòng lặp mock đạt 434 trên 434.

## Giới hạn còn lại

- Tên hai từ trong câu thường, không có ngữ cảnh, vẫn hiển thị. Đây là phần lớn trong 12 ứng viên mạnh còn lại.
- Tên riêng đứng sau lời chào vẫn hiển thị: 33 hàng trong 4 tài liệu khớp mẫu này, và một số có thể là trùng hợp từ danh sách người nhận lớn.
- Danh sách họ, cụm từ chung và địa danh công khai được viết tay, nên có thể bỏ sót tên hiếm hoặc địa danh chưa liệt kê. Tên địa danh mang họ người ngoài danh sách và ngoài ngữ cảnh địa điểm có thể bị che.
- Một số cụm chứa từ phổ biến có thể bị che thừa, như đã nêu ở trên.
- 7 trên 10 annotation trong `data/annotations/model_draft_2026-11-03/` vẫn không khớp văn bản hiện tại.

Khi duyệt riêng tư, hãy đọc toàn bộ văn bản và kiểm tra cả hai chiều: tên còn sót và `[NAME]` che nhầm.

## Lệnh phần mềm

Các lệnh sau chạy trên fixture tổng hợp. `tests/test_name_masking.py` được quan sát thất bại trước khi sửa.

| Lệnh | Kết quả |
|---|---|
| `uv run pytest` | 268 ca đạt |
| `uv run ruff check .` | Đạt |
| `uv run ruff format --check .` | Đạt |
| `uv run smartnotice demo` | 9 tài liệu tổng hợp, 30 cặp event/profile, chạy hết |
| `uv run python tools/run_notebooks.py` | Thực thi đủ 3 notebook; chưa xem lại các hình |
