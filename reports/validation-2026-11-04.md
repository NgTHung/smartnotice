# Kiểm chứng bước chuyển từ chuẩn bị dữ liệu sang gán nhãn LLM, ngày 04/11/2026

Bản ghi này cho biết corpus email thực có đi được từ `prepare` đến `suggest-labels` hay không, và những gì còn chặn bước chuyển đó. Kết quả xác nhận hành vi phần mềm trên một lần chạy thử. Bản ghi không đo chất lượng trích xuất, mức độ ẩn danh hay độ đồng thuận của người gán nhãn.

## Phạm vi lần chạy thử

Dữ liệu vào là 434 tệp `.eml` có nội dung byte khác nhau, giải nén từ hai tệp nén trong `data/raw/` (168 và 266 tệp). Các nguồn này chưa được nhập bằng `collect-email` vì lần chạy không có tham chiếu đồng ý thật. Manifest tạm trong thư mục bị Git bỏ qua dùng giá trị giữ chỗ `scratch-unverified`; giá trị này không phải bằng chứng về sự đồng ý. Bản sao giải nén và đầu ra tạm đã bị xóa sau khi đếm.

Lần chạy chỉ in số liệu tổng hợp. Không có văn bản nào được gửi tới Gemini hoặc Featherless, không có người duyệt riêng tư, và không có thao tác trên Label Studio. Vòng lặp gán nhãn dùng đề xuất tự tạo tại máy (mock), không phải đầu ra của mô hình.

Môi trường: Windows, Python 3.12.13, uv 0.11.7, httpx 0.28.1, Pydantic 2.14.1, commit gốc `112655a` cùng các thay đổi chưa commit của bản ghi này. Seed chia tập là 42, ngưỡng tương đồng là 0,9.

## Lỗi tìm thấy và cách sửa

Mỗi ca hồi quy được quan sát thất bại trước khi sửa, trong `tests/test_review_handoff.py`, `test_pipeline.py`, `test_parsers.py` và `test_cleaning_regressions.py`.

| Vấn đề | Quan sát trước khi sửa | Sau khi sửa |
|---|---|---|
| `split` quá chậm | Ước tính 57,3 phút từ mẫu 300 cặp trên 93.961 cặp; một lần chạy thật bị dừng ở giới hạn 10 phút | 22,5 giây. Cận trên `quick_ratio` loại cả 300 cặp mẫu và không thấp hơn `ratio` ở cặp nào |
| Câu bị cắt sau số thứ tự và chức danh | 9.163 câu, 679 câu dài tối đa 3 ký tự, 179 câu kết thúc bằng viết tắt như `TP.`, `TS.`, `ThS.` | 8.526 câu, 198 câu dài tối đa 3 ký tự |
| MSSV dính vào từ đứng trước | 7 chuỗi 8 chữ số bắt đầu bằng `2` chưa bị che (1 trong nội dung, 6 trong URL) | 0 chuỗi còn lại; 35 `[STUDENT_ID]` so với 25 trước đó |
| Email thiếu `consent_ref` vẫn được chuẩn bị | Manifest không có tham chiếu đồng ý chạy thành công | `prepare` dừng tại dòng manifest và không ghi đầu ra |
| Không có bước duyệt riêng tư trước khi xuất | `export-tasks` xuất mọi notice thực; người duyệt phải tự tính hash | `privacy-review-queue` lập danh sách chờ; `export-tasks` giữ lại notice chưa được duyệt |
| Chọn lô cho LLM | Chỉ có `--doc-id` lặp lại; một notice chưa duyệt chặn cả lô | `--selection`, `--split`, `--approved-only` |
| Tệp chia tập thiếu thiết lập nhóm | Hàng chỉ ghi `seed` | Hàng ghi thêm `similarity` |

Quy tắc MSSV mới làm thay đổi 8 URL trong 5 tài liệu và văn bản của 6 tài liệu. Người duyệt cần kiểm tra các URL này, vì một đoạn số trong token URL có thể bị che nhầm. Một số 10 chữ số bắt đầu bằng `06` trong nội dung vẫn chưa bị che vì nằm ngoài quy tắc số di động; số này được giữ cho người duyệt và cột `long_number_count` của hàng đợi có đếm nó.

## Kết quả trên corpus thử

| Chỉ số | Giá trị |
|---|---|
| Notice được chuẩn bị / nguồn bị từ chối | 434 / 0 |
| Thiếu ngày tham chiếu | 0 |
| Độ dài văn bản, trung vị / lớn nhất | khoảng 926 / 6.634 ký tự |
| Độ dài prompt lớn nhất, trước khi sửa phân đoạn | 18.050 ký tự |
| Train / validation / test | 304 / 65 / 65 |
| Số nhóm / nhóm lớn nhất | 336 / 11 tài liệu |
| Offset câu khớp văn bản | Có, trên toàn bộ 8.526 câu |
| Tài liệu chứa ký tự ngoài BMP (Basic Multilingual Plane) | 95 trên 434, tất cả là biểu tượng |
| Vòng lặp mock đề xuất, Label Studio task, import | 434 trên 434 thành công |
| Notice chờ duyệt riêng tư | 434 trên 434 |

Với sổ duyệt rỗng, `export-tasks` và `suggest-labels` đều trả mã khác 0 và không gửi hay ghi dữ liệu.

## Lệnh phần mềm

Các lệnh sau chạy trên fixture tổng hợp và không liên quan tới corpus thực.

| Lệnh | Kết quả |
|---|---|
| `uv run pytest` | 207 ca đạt |
| `uv run ruff check .` | Đạt |
| `uv run ruff format --check .` | Đạt |
| `uv run smartnotice demo` | 9 tài liệu tổng hợp, chạy hết |
| `uv run python tools/run_notebooks.py` | Thực thi đủ 3 notebook; chưa xem lại các hình |

## Những gì còn chặn bước chuyển

1. Tham chiếu đồng ý: nhóm cần nhập nguồn bằng `collect-email --consent-ref` với hồ sơ đồng ý thật. `data/raw/` chưa có `manifest.jsonl`.
2. Duyệt riêng tư: người duyệt cần đọc văn bản và hoàn thành bản ghi. Phần mềm không thay thế bước này.
3. Cấu hình nhà cung cấp: repository chưa có `.env`, nên chưa có model hay key để chạy thật.
4. Ký tự ngoài BMP: 22% tài liệu có thể lệch offset giữa Python và trình duyệt. Chưa kiểm tra trên Label Studio thật. Trình nhập từ chối span lệch, và một span lệch làm cả lần `import-reviewed-labels` thất bại.
5. Bản nháp `data/annotations/model_draft_2026-11-03/`: 7 trên 10 annotation không còn khớp văn bản hiện tại và cần tạo lại.

Chất lượng đề xuất của mô hình, khả năng chịu giới hạn tốc độ của nhà cung cấp và độ dài đầu ra thực tế trên văn bản dài chưa được đo.
