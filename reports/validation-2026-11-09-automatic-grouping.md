# Đề xuất gom nhóm tự động, ngày 09/11/2026

Lần chạy này nối tìm cặp ứng viên, dự đoán quan hệ, dựng nhóm và xuất trang duyệt từ annotation đã lưu. Mục tiêu là tạo một vòng chạy tự động có thể kiểm tra bằng nguồn và đối chiếu với kết quả làm việc trước. Đây là bản quy tắc trên mẫu phát triển, không phải mô hình đã huấn luyện hoặc đánh giá độc lập.

## Phạm vi và cách chạy

Đầu vào là 34 Notice trong gói pilot, 35 lần nhắc thuộc `user-reviewed-2026-11-09/annotations.grouping.jsonl` và bảy diễn giải thời gian có tác giả. Nguồn và annotation đầy đủ ngoài tập con này không được mở rộng trong lần chạy. Bản tham chiếu là `data/processed/event-grouping-user-reviewed-2026-11-09/assembly.json`, có 22 quyết định cặp; nó chỉ được đọc sau dự đoán để lập đối chiếu.

Lệnh [`run_automatic_grouping.py`](../tools/run_automatic_grouping.py) trong [README](../README.md) nhận đầu vào và ghi một thư mục mới. Module [`automatic_grouping.py`](../src/labeling/automatic_grouping.py) sở hữu tìm ứng viên, quy tắc quyết định và đối chiếu; bộ dựng nhóm và trang xem dùng các module đã có. Không thêm dependency, gọi nhà cung cấp mô hình, đọc hộp thư hoặc sửa nguồn.

Cấu hình `automatic-event-grouping-v1` dùng ngưỡng Jaccard tìm ứng viên `0.35`, tối thiểu ba từ giao nhau cho nhánh tìm kiếm từ vựng và hai từ nhận diện có thông tin. Trùng mã, tên hoặc URL còn có các nhánh tìm ứng viên riêng; ngưỡng từ vựng không áp dụng thay cho chúng. Các quy tắc cố định không được fit hoặc chọn ngưỡng theo đối chiếu này. [Contract](../docs/interface.md#propose-and-assemble-groups-automatically) quy định căn cứ nhận diện, tách đầu việc, cập nhật và từ chối quyết định.

Đầu ra được bàn giao tại `reports/generated/automatic-grouping-2026-11-09-final/`. Mở `index.html` để xem nguồn hoặc `comparison.md` để xem nhãn, quan hệ đầu việc và liên kết đến nhóm tương ứng. `pair_proposals.jsonl` giữ căn cứ tìm cặp và quyết định; `result.json` và `assembly.json` giữ đầu ra có kiểu. Góp ý và xác nhận nhóm đơn trước được giữ nguyên, không kế thừa vào dự đoán mới.

## Kết quả quan sát

| Số đếm quy trình | Kết quả |
|---|---:|
| Lần nhắc đầu vào | 35 |
| Cặp có thể so sánh | 595 |
| Cặp ứng viên có đề xuất | 65 |
| `SAME_EVENT` | 8 |
| `UPDATE_OF` | 1 |
| `DIFFERENT_EVENT` | 11 |
| `UNCLEAR` | 45 |
| Nhóm, gồm nhóm đơn | 26 |
| Nhóm nhiều lần nhắc | 9 |
| Hoạt động/đầu việc | 30 |
| Cập nhật thời gian được áp dụng | 1 |
| Mâu thuẫn bộ dựng nhóm báo | 0 |

Đối chiếu chỉ xét 22 cặp tham chiếu tường minh. Có 19 cặp được bước tìm ứng viên bao phủ; ba cặp không được tìm thấy. Có 11 cặp không báo khác biệt ở các trường đã so sánh. Các vấn đề gồm bốn khác biệt nhãn, bảy khác biệt quan hệ đầu việc, bốn khác biệt cùng nhóm và năm khác biệt cùng đầu việc trong kết quả dựng. Một cặp có thể có nhiều vấn đề, nên không cộng các số này thành số cặp lỗi.

Những số đếm này mô tả khoảng cách với bản tham chiếu đã tham gia phát triển, không phải accuracy, F1 hoặc đồng thuận con người. Annotation đầu vào đã được sửa trong quá trình làm việc trước; quyết định cặp tham chiếu có nguồn gốc AI và áp dụng góp ý người dùng. Nhóm đơn được đồng ý không tự tạo nhãn phủ định giữa mọi nhóm. Bản tự động chỉ áp dụng một trong hai cập nhật có trong bản tham chiếu, nên không thay kết quả đã duyệt bằng đầu ra tự động này.

## Kiểm chứng

Môi trường Windows, Python 3.12.13, uv và dependency lock hiện có. Không có RNG hoặc huấn luyện. `run.json` lưu thời điểm, cấu hình, hashes của 13 file đầu vào/mã/template/lock và giới hạn xuất xứ. Chạy lại với cùng `--generated-at` vào thư mục mới; bằng chứng kiểm tra nằm tại `reports/generated/automatic-grouping-2026-11-09-final-verification/verification.json`.

| Kiểm tra | Kết quả |
|---|---|
| Kiểm thử tính năng mới | 23 ca đạt, gồm chuỗi nhắc/gia hạn/check-in, bí danh có mã, nhiều mục một email, ca và nghĩa vụ có điều kiện |
| Bộ kiểm thử đầy đủ | 337 ca đạt |
| Ruff check và format check | Đạt |
| Offline demo | Chín tài liệu tổng hợp, năm annotation, 30 cặp; không có nhóm qua nhiều split |
| Thành viên và offsets | 35 lần nhắc được giữ đúng một lần; 109 giá trị trong nhóm khớp nguồn; mọi trích dẫn cặp khớp nguồn |
| Hash đầu vào và triển khai | 13 file giữ nguyên trong lượt chạy và kiểm tra |
| Tái tạo | 11 file đầu ra, gồm HTML, khớp từng byte |
| Cách ly tham chiếu | Kiểm thử thay quyết định tham chiếu vẫn cho dự đoán giống nhau |
| Bảo toàn review trước | Checksums gói góp ý và xác nhận nhóm đơn khớp; không kế thừa approval vào trang mới |
| JavaScript | Qua `node --check`; payload nhúng khớp assembly |

Chạy kiểm thử bằng `uv run pytest -q -o cache_dir=tmp/pytest-cache --basetemp tmp/pytest-auto-final`, với cache uv tại `tmp/uv-cache` và `--no-sync` trên môi trường đã cài. Kiểm tra JavaScript không thay cho kiểm tra hiển thị trực tiếp trên trình duyệt. Dữ liệu, trang HTML và các lượt chạy lại nằm ngoài Git theo quy tắc hiện có.

## Giới hạn và lượt duyệt tiếp

Nhận diện phụ thuộc vào tên trong ACTION hoặc tiêu đề có cấu trúc và bằng chứng được annotation chọn. Hệ thống có thể bỏ sót bí danh thiếu mã, ngữ cảnh nằm ngoài bằng chứng, các bước diễn đạt khác nhau hoặc quy trình có nhiều phiên bản gia hạn. Tên có hai từ thông tin là một dấu hiệu quy tắc, không phải bảo đảm duy nhất của sự kiện. Mọi nhóm và mọi đề xuất vẫn cần duyệt.

Thay đổi địa điểm/trạng thái, thiếu mục tiêu cập nhật, khoảng thời gian chưa tách và nhiều giá trị không rõ được giữ để kiểm tra. Bước cải thiện tiếp theo là duyệt ba cặp thiếu ứng viên và các khác biệt đầu việc/cập nhật trong `comparison.md`, rồi dùng những lỗi có giải thích để bổ sung ca tổng hợp. Đánh giá chất lượng cần một tập nhãn độc lập và quy trình chia dữ liệu riêng theo [quy trình đánh giá](../docs/evaluation.md).
