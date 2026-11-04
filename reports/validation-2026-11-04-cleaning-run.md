# Lần chạy làm sạch toàn bộ email, ngày 04/11/2026

Bản ghi này cho biết hai tệp nén email đi qua toàn bộ bước làm sạch ra sao sau khi loại emoji ngoài BMP (Basic Multilingual Plane). Đây là lần chạy dàn dựng (staged): đầu ra chưa phải corpus nghiên cứu vì chưa có tham chiếu đồng ý thật và chưa có người duyệt riêng tư. Các số liệu mô tả phần mềm và nguồn thô, không đo chất lượng mô hình, mức độ ẩn danh hay độ đồng thuận.

## Đầu vào và phạm vi

| Nguồn | Số `.eml` | SHA-256 của tệp nén |
|---|---|---|
| `SmartNotice_HCMUS_selected_emails_2024-2026.zip` | 168 | `49113d7d9ce740330029534346b604c20033591023feffb858d09e10c1c28695` |
| `Mail_khoa.rar` | 266 | `a7913789fadfdc3ee50d6c64347bb89edde58b2cf9276e28a1669863d2d15a3a` |

Đầu ra nằm trong `tmp/cleaning-run-2026-11-04/`, thư mục bị Git bỏ qua và tách khỏi `data/raw/` cùng `data/interim/` để các lệnh mặc định không đọc nhầm. Manifest dùng giá trị giữ chỗ `UNVERIFIED-pending-team-consent-reference`; giá trị này không phải bằng chứng về sự đồng ý. Tệp nén gốc không đổi, và bản sao giải nén đã bị xóa sau khi nhập.

Không có tệp `--privacy-rules` nào được cung cấp, nên tên riêng chỉ được học từ header và mẫu giới thiệu tên trong từng email. Chính sách email là `all`. Không có văn bản nào được gửi tới nhà cung cấp mô hình.

Môi trường: Windows, Python 3.12.13, uv 0.11.7, `uv.lock` có SHA-256 `9579c05dcdcd3319fd08644c3aedf0321c15f9d04ffdf13a9b50d00bdaa97941`, commit gốc `112655a` cùng các thay đổi chưa commit. Seed chia tập là 42, ngưỡng tương đồng là 0,9.

## Kết quả

| Chỉ số | Giá trị |
|---|---|
| Hash byte thô khớp tên tệp | 434 trên 434 |
| Hàng `selected=yes` trong `selection_report.csv` khớp nguồn thô | 168 trên 168 |
| Notice được chuẩn bị / nguồn bị từ chối | 434 / 0 |
| Thiếu ngày tham chiếu | 0 |
| Năm tham chiếu 2024 / 2025 / 2026 | 77 / 186 / 171 |
| Độ dài văn bản, nhỏ nhất / trung vị / p95 / lớn nhất | 41 / 925 / 2.977 / 6.634 ký tự |
| Độ dài prompt, trung vị / lớn nhất | 4.975 / 17.540 ký tự |
| Số câu / câu dài tối đa 3 ký tự / câu trên 300 ký tự | 8.523 / 195 / 84 |
| Offset câu khớp văn bản | Có, trên toàn bộ câu |
| Tài liệu còn ký tự ngoài BMP / còn ký tự nối ZWJ | 0 / 0 |
| Tài liệu còn chuỗi dạng địa chỉ email | 0 |
| Tổng số lần che / tài liệu không có lần che nào | 524 / 216 |
| `[NAME]` / `[EMAIL]` / `[PHONE]` / `[STUDENT_ID]` | 234 / 207 / 39 / 35 |
| URL trong `attachments` | 733 |
| Train / validation / test | 304 / 65 / 65 |
| Số nhóm / nhóm lớn nhất | 336 / 11 tài liệu |
| Văn bản trùng hoàn toàn / văn bản dưới 80 ký tự | 1 / 5 |
| Hàng chờ duyệt riêng tư / hàng có số từ 8 chữ số trở lên | 434 / 34 |
| Vòng lặp mock đề xuất, task, import | 434 trên 434 |

Thời gian chạy: `prepare` 18,2 giây và `split` 26,3 giây. Không có tài liệu nào bị từ chối vì chỉ còn emoji. Với sổ duyệt rỗng, `export-tasks` và `suggest-labels` đều trả mã khác 0 và không ghi đầu ra. Vòng lặp mock dùng đề xuất tự tạo tại máy, nên chỉ kiểm tra định dạng và offset, không kiểm tra Label Studio hay mô hình thật.

Số che bằng 0 ở 216 tài liệu không có nghĩa các tài liệu đó không chứa thông tin cá nhân. Người duyệt vẫn phải đọc toàn bộ văn bản.

## Kiểm thử phần mềm

Các lệnh sau chạy trên fixture tổng hợp.

| Lệnh | Kết quả |
|---|---|
| `uv run pytest` | 218 ca đạt, trong đó có ca hồi quy emoji được quan sát thất bại trước khi sửa |
| `uv run ruff check .` | Đạt |
| `uv run ruff format --check .` | Đạt |
| `uv run smartnotice demo` | 9 tài liệu tổng hợp, 30 cặp event/profile, chạy hết |
| `uv run python tools/run_notebooks.py` | Thực thi đủ 3 notebook; chưa xem lại các hình |

## Việc còn lại

1. Nhập lại nguồn vào `data/raw/` bằng `collect-email --consent-ref` với tham chiếu đồng ý thật. Tham chiếu không đi vào Notice, nên `prepare` trên cùng byte thô và cùng cấu hình dự kiến cho cùng `text`; hãy đối chiếu `text_sha256` sau khi chạy lại.
2. Duyệt riêng tư theo `interim/privacy_review_queue.jsonl`, ưu tiên 34 hàng có số dài, 9 URL có `[STUDENT_ID]` và một số 10 chữ số bắt đầu bằng `06` đã ghi trong [bản ghi trước](validation-2026-11-04.md). Việc thêm `--privacy-rules` về sau làm đổi văn bản và làm mất hiệu lực các bản duyệt đã có.
3. Xem lại các nhóm gộp và 1 văn bản trùng trước khi đóng băng tập chia.
4. Xác định `Mail_khoa.rar` đã được lọc hay chưa. Tệp này không có báo cáo chọn lọc như tệp zip, nên có thể chứa thư không phải thông báo.
5. Tạo lại `data/annotations/model_draft_2026-11-03/`: 7 trên 10 annotation không còn khớp văn bản hiện tại.
6. Tạo `.env` và chạy thử một notice tổng hợp trước khi gửi dữ liệu thật.
