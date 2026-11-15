# Mở rộng grouping trên batch email, ngày 15/11/2026

Lần chạy này mở rộng quy trình đề xuất và dựng nhóm từ mẫu phát triển sang toàn bộ batch dự đoán email đã lưu. Bản xuất cho phép đọc nguồn, duyệt nhóm và giữ các giá trị thời gian cần kiểm tra. Các số đếm mô tả đầu ra quy tắc trên dự đoán mô hình; đánh giá chất lượng cần nhãn độc lập theo [quy trình đánh giá](../docs/evaluation.md).

## Phạm vi và đầu vào

Phần việc hoàn thành trước lần mở rộng được lưu tại commit `4db50b6`. Công cụ [`run_automatic_grouping.py`](../tools/run_automatic_grouping.py) được bổ sung đầu vào `--predictions`, dùng bộ chuyển đổi trong `studio.py` để kiểm tra nguồn và dự đoán. Công cụ yêu cầu batch bao phủ đúng tập Notice, giữ tác giả `model_prediction` và xuất cả annotation rỗng trong `annotations.jsonl`. [Contract](../docs/interface.md#propose-and-assemble-groups-automatically) quy định đầu vào và đầu ra.

| Đầu vào cục bộ | SHA-256 |
|---|---|
| `data/annotations/drive-auto-label-2026-11-04/notices.compat.jsonl` | `ba33789fb9fffdc1dffbb6e870a76dad7ca0b6eded65e6252256bbfa0881fc4c` |
| `data/annotations/drive-auto-label-2026-11-04/tasks.json` | `d4113822f703ffe9aab9f7574019d0abec52c89f7effc29b4ef2ef3b6c503f14` |

Batch gồm 434 email với dự đoán đã lưu từ Featherless. Cả 434 Annotation đầu vào có tác giả `model_prediction`; bốn tài liệu có dự đoán rỗng. Các sửa trích xuất và xác nhận của [mẫu đã chốt ngày 10/11](validation-2026-11-10-group-acceptance.md) tiếp tục gắn với snapshot của mẫu đó. Lần mở rộng dùng nguyên dự đoán batch làm đầu vào và yêu cầu duyệt cho toàn bộ nhóm mới.

Môi trường chạy là Windows, Python 3.12.13 và dependency lock hiện có. Quy tắc `automatic-event-grouping-v1` dùng Jaccard ứng viên `0.35`, ít nhất ba từ chung ở nhánh từ vựng và hai từ nhận diện có thông tin. Các giá trị này giữ cấu hình mặc định; tham số và hashes của 12 file đầu vào, mã, template và lock được ghi trong `run.json`. Quy trình chạy xác định, với `randomness=null`.

Lệnh từ thư mục gốc, dùng cache uv cục bộ và môi trường đã cài.

```powershell
$env:UV_CACHE_DIR = 'tmp/uv-cache'
$env:PYTHONIOENCODING = 'utf-8'
uv run --offline --no-sync python tools/run_automatic_grouping.py `
  --notices data/annotations/drive-auto-label-2026-11-04/notices.compat.jsonl `
  --predictions data/annotations/drive-auto-label-2026-11-04/tasks.json `
  --output-dir reports/generated/automatic-grouping-full-2026-11-15
```

Thời điểm tạo được ghi là `2026-11-15T08:33:52.658602+00:00`, tương ứng 15 giờ 33 phút ngày 15/11 tại Việt Nam. Chọn thư mục mới khi chạy lại. Để tái tạo nội dung, thêm `--generated-at 2026-11-15T08:33:52.658602+00:00` với cùng nguồn và mã.

## Kết quả quan sát

| Số đếm quy trình | Kết quả |
|---|---:|
| Tài liệu / Annotation | 434 / 434 |
| Annotation rỗng | 4 |
| Lần nhắc | 1.630 |
| Cặp đã xét | 1.327.635 |
| Cặp có đề xuất | 10.787 |
| `SAME_EVENT` | 19 |
| `DIFFERENT_EVENT` | 251 |
| `UNCLEAR` | 10.517 |
| Nhóm, gồm nhóm đơn | 1.611 |
| Nhóm nhiều lần nhắc / nhóm đơn | 19 / 1.592 |
| Đầu việc | 1.626 |
| Cập nhật được áp dụng | 0 |
| Mâu thuẫn `competing_values` | 61 |

Trong các đề xuất cùng sự kiện, 15 cặp giữ riêng đầu việc và bốn cặp cùng đầu việc. Có 10.515 cặp `UNCLEAR` do thiếu căn cứ nhận diện và hai cặp do khoảng thời gian chưa tách. Việc kiểm tra thông báo gia hạn tiếp tục cần đọc nguồn và phạm vi trích xuất của từng mục.

Các mâu thuẫn giá trị gồm 18 trường `DEADLINE`, 29 `EVENT_TIME` và 14 `START`. Khi dựng từng lần nhắc riêng với cùng Annotation, bộ dựng nhóm đã ghi nhận 59 mâu thuẫn; bản có quyết định cặp ghi nhận 61. Người duyệt cần đối chiếu cả phạm vi trích xuất và các giá trị được giữ trong đầu việc. Mỗi giá trị tiếp tục có trích dẫn và offsets để kiểm tra.

## Bàn giao lượt duyệt

Bản xuất nằm tại `reports/generated/automatic-grouping-full-2026-11-15/`. Mở `index.html` để đọc nguồn và xuất ghi chú. Fingerprint của assembly là `f0f97ae4c18cfc4e6e4bc1a5e0b0c4773fc2b80d3e4804daa6416b40bb5c4d23`.

Danh sách ưu tiên tại `reports/generated/automatic-grouping-full-2026-11-15-verification/review_queue.md` liên kết tới 74 nhóm có mâu thuẫn giá trị hoặc nhiều lần nhắc. `review_queue.json` giữ ID, trường cần kiểm tra và bốn ID tài liệu có dự đoán rỗng. Các tài liệu này cần lượt kiểm tra bỏ sót trích xuất trên Notice gốc; trang HTML chứa 430 tài liệu có lần nhắc đầu vào.

Có 15 nhóm đề xuất nối các tài liệu thuộc nhiều `Notice.group_id` tiền xử lý. Trước khi chốt dữ liệu nghiên cứu, cần duyệt các quan hệ này và giữ tài liệu liên quan trong cùng nhóm đánh giá. File split của corpus 434 tài liệu được nêu trong báo cáo ngày 04/11 hiện thiếu trong workspace, nên phép đối chiếu với train/validation/test còn chờ snapshot đó. Các nhóm và quyết định ở lần này được lưu với yêu cầu duyệt nhóm và riêng tư.

## Kiểm chứng

| Kiểm tra | Kết quả |
|---|---|
| Kiểm thử grouping sau bổ sung | 29 ca đạt |
| Bộ kiểm thử đầy đủ | 358 ca đạt |
| Ruff check và format check | Đạt |
| Offline demo | Chín tài liệu tổng hợp, năm Annotation, 30 cặp; số nhóm qua nhiều split bằng 0 |
| Nguồn và Annotation | 434 Annotation khớp phép chuyển đổi dự đoán; tác giả mô hình được giữ |
| Thành viên, trích dẫn và offsets | Dựng lại assembly từ nguồn thành công; đủ 1.630 lần nhắc, mỗi lần xuất hiện đúng một lần |
| Hash đầu vào và mã | 12 file khớp `run.json` |
| Hash đầu ra | Chín file khớp `checksums.json` |
| Tái tạo | Cả mười file của thư mục chạy lại khớp từng byte |
| Mẫu đã chốt | Mười hash trong gói chốt ngày 10/11 khớp bản lưu |
| Trang HTML | Payload khớp assembly, đủ 430 tài liệu nguồn; JavaScript qua `node --check` |

Ca kiểm thử bổ sung kiểm tra đường chạy dự đoán, giữ annotation rỗng và tác giả mô hình, cùng các batch thiếu tài liệu, trùng tài liệu, sai hash, có completion hoặc JSON hỏng. Ca đường chạy mới được quan sát thất bại vì thiếu hỗ trợ `--predictions` trước khi bổ sung công cụ. Lệnh toàn bộ suite là `uv run --offline --no-sync pytest -q -o cache_dir=tmp/pytest-cache --basetemp tmp/pytest-grouping-2026-11-15-expanded`.

Bằng chứng tại `reports/generated/automatic-grouping-full-2026-11-15-verification/verification.json`; script `verify_artifacts.py` trong cùng thư mục tái tạo phép kiểm tra và danh sách duyệt. Kiểm tra trực tiếp trong trình duyệt bị dừng do công cụ hết thời gian chờ cấp quyền mở ứng dụng. Phần hiển thị thực tế cần được kiểm tra khi mở trang cục bộ.

Các số lượng trên giới hạn ở batch email và các sự kiện mô hình đã trích xuất. Phần mở rộng sang thông báo web, nhãn độc lập, hoàn tất duyệt riêng tư và đo chất lượng còn cần dữ liệu tương ứng. Đầu ra, HTML và danh sách duyệt được lưu riêng tư ngoài Git; báo cáo này chỉ chứa số đếm, đường dẫn và mã băm.
