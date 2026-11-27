# Hoàn tất phần nền cho bộ lọc ứng viên span, 24/11/2026

Mốc tuần 1 thiết lập cách biểu diễn ứng viên, cách xác nhận đã rà đủ nhãn và cách tạo target nhị phân. Lần kiểm kê dùng tập train và validation của snapshot đã chia để kiểm tra khả năng đối chiếu span và xác định số tài liệu đủ căn cứ đưa vào thí nghiệm.

## Dữ liệu phát triển

Bảng 1 đếm span phân biệt theo tài liệu, vị trí và nhãn. Annotation đầu vào có nguồn gốc máy hỗ trợ. Script kiểm tra nhãn, offset, substring và hash văn bản trong assignment. Nhóm trong assignment không giao nhau giữa các tập đánh giá.

| Nhãn | Train (317 tài liệu) | Validation (73 tài liệu) |
|---|---:|---:|
| ACTION | 1.281 | 297 |
| TIME | 660 | 153 |
| AUDIENCE | 536 | 123 |
| CONDITION | 127 | 29 |
| CHANNEL | 458 | 106 |
| DOCUMENT | 338 | 79 |
| Tổng | 3.400 | 787 |

Cả 390 tài liệu có annotation với offset hợp lệ theo phép chiếu. Có 4.189 bản ghi span và 4.187 span phân biệt. Tập train có 281 email và 36 web. Tập validation có 65 email và 8 web. Assignment có 410 nhóm, seed 42 và ngưỡng gần trùng 0,8. Lần chạy chỉ dùng assignment để đếm 99 tài liệu test và 45 tài liệu domain test.

Số tài liệu có xác nhận rà đủ sáu nhãn trong lần chạy là 0 vì chưa có sổ `SpanReview` làm đầu vào. Hồ sơ duyệt ở cấp snapshot cần được bổ sung bằng xác nhận đã kiểm tra các span bị bỏ sót trên từng tài liệu. Việc xác nhận này do người duyệt thực hiện. Chỉ số của lần chạy mô tả dữ liệu và hành vi phần mềm. Chưa có phép đo recall của generator hay chất lượng LR/RF.

## Quy tắc tạo target

Mỗi ứng viên mang nhãn đề xuất và offset trong prepared text. Bộ đối chiếu kiểm tra hash rồi so sánh vị trí và nhãn với annotation. Khớp cả hai nhận `1`. Lệch ranh giới hoặc nhầm nhãn nhận `0` khi người duyệt đã xác nhận gán đủ nhãn. Với annotation thiếu xác nhận, bộ đối chiếu để `target=null`. [Data contract](../docs/interface.md#validate-candidate-targets)

Trong kiểm thử tổng hợp, gold đánh dấu `nộp hồ sơ` là ACTION tại `[4, 13)`. Ứng viên giống hệt nhận `1`, ứng viên lấy thêm dấu chấm nhận `0` với chẩn đoán lệch ranh giới và ứng viên cùng offset mang nhãn DOCUMENT nhận `0` với chẩn đoán sai nhãn.

## Tái lập lần chạy

Môi trường là macOS arm64, Python 3.12.13, uv 0.11.16. Thay đổi dựa trên commit `4f5b8b1`. Snapshot là `20261113-official-split`. SHA-256 của assignment là `0331c46c7c24f2dace366bfdc3d15e058e86b386e8f84d6f9c38069bdf7a8186`. Script in hash từng tệp đầu vào và `uv.lock` cùng thống kê tổng hợp.

```sh
uv run python tools/audit_span_development.py data/interim/lm_audit_snapshot/20261113-official-split
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run smartnotice demo
git diff --check
```

305 kiểm thử đạt, gồm 5 kiểm thử mới về target, offset, nhãn và hash. Ruff, kiểm tra định dạng, kiểm tra diff và demo ngoại tuyến đều đạt.

Mốc kế tiếp là sinh ứng viên theo luật và đo exact candidate recall trên tập phát triển đã rà đủ nhãn. Bắt đầu rà một lô nhỏ để đo thời gian gán nhãn và đếm số nhóm có positive/negative theo nhãn. [Quy trình annotation](../docs/annotation.md#measure-annotation-quality)
