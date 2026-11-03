# Kiểm chứng bộ xử lý dữ liệu, ngày 03/11/2026

Bản ghi này kiểm chứng các sửa đổi cho 10 lỗi đọc email/HTML, tách hội thoại và che thông tin riêng tư. Kiểm thử sử dụng dữ liệu tổng hợp và tuân theo [contract dữ liệu](../docs/interface.md). Kết quả xác nhận hành vi phần mềm; không đo chất lượng mô hình, mức độ ẩn danh hay độ đồng thuận của người gán nhãn.

## Đối chiếu 10 lỗi

Các ca hồi quy nằm trong [`test_cleaning_regressions.py`](../tests/test_cleaning_regressions.py). Bộ ca đầu tiên ghi nhận 51 ca thất bại và 17 ca đạt trước khi sửa. Các ca bổ sung kiểm tra tương tác giữa những thay đổi và ranh giới đầu vào.

| Lỗi | Hành vi được kiểm tra |
|---|---|
| 1. MSSV giống ngày | Che `20120318`, `19120105`, `24129999` khi thiếu ngữ cảnh ngày; giữ ngày thông báo có ngữ cảnh; che ngày sinh và ID có nhãn |
| 2. Trích dẫn trong bảng | Loại vùng email trích dẫn trước khi làm phẳng bảng, kể cả bảng lồng nhau; không sinh marker trong task |
| 3. Original Message | Nhận dòng phân cách trọn dòng với dấu gạch, underscore, hoặc không có dấu; giữ cụm từ xuất hiện trong câu |
| 4. Email có dấu bao quanh | Chính sách `all`/`legacy` và audit dùng địa chỉ chuẩn hóa; giữ dấu bao quanh, dấu lồng nhau và ký tự thực sự thuộc local part |
| 5. Tên có thành phần một chữ | Che đầy đủ `Trần Thị Ý`, `Nguyễn Văn A`, `Lê Văn Ý` trong ngữ cảnh tên, ở cả NFC và NFD |
| 6. Email mã hóa trong URL | Phát hiện email trong path/query/fragment qua nhiều lớp percent encoding; giữ cấu trúc query; loại URL không thể kiểm tra an toàn |
| 7. Ngày giờ bị nhận là điện thoại | Giữ `07.11.2026 17:00` cùng dạng `/` và `-`; che các định dạng điện thoại được hỗ trợ |
| 8. Cắt nhầm nội dung | Giữ `bài viết:`, giờ seminar và chủ đề; tiếp tục bản ghi hợp lệ trong chế độ batch review, báo lỗi bằng hash và mã lý do |
| 9. Blockquote thụt lề | Giữ blockquote thường; chỉ loại vùng trích dẫn rõ; giữ phần trả lời nằm sau vùng trích dẫn |
| 10. Giải mã HTML lặp | Giữ query `section`/`region`; chỉ giải mã entity tại parser HTML một lần; giữ entity lồng lớp còn lại |

Kiểm thử tích hợp kiểm tra nguồn thô không đổi, URL trong `attachments` xuất hiện trong `text`, offsets khớp văn bản cuối, và quan hệ `DEADLINE` đi qua import/export Label Studio. Audit riêng tư tiếp tục xét cả email nằm trong vùng HTML trích dẫn.

## Lệnh và kết quả

Môi trường chạy là Windows, Python 3.12.13 và uv 0.11.1, sử dụng `pyproject.toml` cùng `uv.lock` của repository. Không thay đổi dependency hoặc nguồn fixture.

| Lệnh | Kết quả |
|---|---|
| `uv run pytest -q --tb=short` | 190 ca đạt |
| `uv run ruff check .` | Đạt |
| `uv run ruff format --check .` | Đạt |
| `uv run smartnotice demo` | 9 tài liệu tổng hợp, 5 annotation hợp lệ, 30 cặp event/profile; không có nhóm đi qua nhiều split |
| `uv run python tools/run_notebooks.py` | Thực thi đủ 3 notebook |
| `git diff --check` | Đạt |

Đầu ra demo được tạo lại trong các thư mục sinh tự động đã được loại khỏi Git. Đã xem sáu hình: nhãn đọc được, không bị cắt và mỗi hình thể hiện đúng loại biểu đồ. Các bảng notebook mô tả corpus tổng hợp; các nhãn applicability là silver labels sinh bằng quy tắc.

## Phạm vi và đầu ra cũ

Chế độ `prepare()` mặc định giữ hành vi dừng lỗi trước khi thay thế đầu ra. Tùy chọn `--errors-output` cho phép ghi các Notice hợp lệ và một danh sách nguồn bị từ chối; CLI trả mã khác 0 khi có nguồn lỗi. [Contract](../docs/interface.md#trace-a-document) định nghĩa mã lỗi và các lỗi vẫn dừng toàn bộ batch.

Các bản xuất corpus thực chưa được tạo lại hay xác nhận riêng tư. Khi chuẩn bị lại nguồn theo quy tắc mới, cần đối chiếu văn bản, kiểm tra lại annotation và offsets, rồi tạo lại task cùng các đầu ra phụ thuộc. Hash nguồn thô không đổi không đảm bảo văn bản đã chuẩn bị giống phiên bản cũ. Kiểm tra riêng tư và gán nhãn của con người vẫn là các bước riêng.
