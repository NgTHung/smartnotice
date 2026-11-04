# Lần chạy tiền xử lý đầy đủ tại commit `23df942`, ngày 04/11/2026

Bản ghi này giúp nhóm nhận ra đúng bộ đầu ra được tạo bằng mã đã commit, gồm cả quy tắc che tên mới. Đây vẫn là lần chạy dàn dựng: manifest dùng giá trị giữ chỗ `UNVERIFIED-pending-team-consent-reference`, giá trị này không phải bằng chứng về sự đồng ý, và chưa có người duyệt riêng tư. Số liệu mô tả phần mềm, không đo chất lượng mô hình hay mức độ ẩn danh.

## Nhận diện lần chạy

| Mục | Giá trị |
|---|---|
| Commit mã | `23df942be91f652e6130a18496ea2dc0c33a3762` |
| `src/`, `pyproject.toml`, `uv.lock` khác commit | Không |
| Môi trường | Windows, Python 3.12.13 |
| `uv.lock` SHA-256 | `9579c05dcdcd3319fd08644c3aedf0321c15f9d04ffdf13a9b50d00bdaa97941` |
| Tệp zip SHA-256 | `49113d7d9ce740330029534346b604c20033591023feffb858d09e10c1c28695` |
| Tệp rar SHA-256 | `a7913789fadfdc3ee50d6c64347bb89edde58b2cf9276e28a1669863d2d15a3a` |
| `notices.jsonl` SHA-256 | `6af51fbb103670fa05e5d85825862d0a3f0b3014bd5bac84c0c86800cdce321f` |
| `splits.jsonl` SHA-256 | `3d85f6a285c49c4cfc1d4c9b2b14b0078fd42530c37456785fe4aa2402f299c8` |
| Chính sách email / tệp `--privacy-rules` | `all` / không có |
| Seed / ngưỡng tương đồng | 42 / 0,9 |

Đầu ra riêng tư nằm trong `tmp/preprocess-run-2026-11-04/`, thư mục bị Git bỏ qua. Lần chạy bắt đầu từ thư mục trống và cho văn bản của cả 434 tài liệu cùng phép chia tập giống hệt lần chạy trước ở [bản ghi che tên](validation-2026-11-04-name-masking.md).

## Kết quả

| Chỉ số | Giá trị |
|---|---|
| Notice được chuẩn bị / nguồn bị từ chối | 434 / 0 |
| Thiếu ngày tham chiếu | 0 |
| Số câu; offset khớp văn bản | 8.526; có |
| Tài liệu còn ký tự ngoài BMP / chuỗi dạng địa chỉ email | 0 / 0 |
| `[NAME]` / `[EMAIL]` / `[PHONE]` / `[STUDENT_ID]` | 281 / 207 / 39 / 35 |
| Tổng số lần che / tài liệu không có lần che nào | 571 / 207 |
| Train / validation / test | 304 / 65 / 65 |
| Số nhóm / nhóm rò rỉ qua nhiều tập | 336 / 0 |
| Văn bản trùng hoàn toàn / văn bản dưới 80 ký tự | 2 / 5 |
| Hàng chờ duyệt riêng tư | 434 |

Với sổ duyệt rỗng, `export-tasks` và `suggest-labels` đều trả mã khác 0 và không ghi đầu ra. Không có văn bản nào được gửi tới nhà cung cấp mô hình. Thử nghiệm mock đạt 434 trên 434, nhưng chỉ kiểm tra định dạng và offset.

## Kiểm thử phần mềm

Tại commit này, `uv run pytest` đạt 268 ca trên fixture tổng hợp, `uv run ruff check .` và `uv run ruff format --check .` đều đạt. Các giới hạn về che tên và những việc còn phải làm trước khi gán nhãn nằm trong [bản ghi che tên](validation-2026-11-04-name-masking.md) và [bản ghi lần chạy làm sạch](validation-2026-11-04-cleaning-run.md).
