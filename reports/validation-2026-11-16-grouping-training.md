# Duyệt nhóm vượt ranh giới và đóng băng dữ liệu gom nhóm, 16/11/2026

Bản dữ liệu huấn luyện thử nghiệm dựng từ v3.3 có 400 tài liệu train và 16 cặp gắn nhãn sự kiện. Trợ lý đối chiếu năm nhóm ưu tiên với email nguồn và kiểm tra tám cặp âm trong tập train. Hồ sơ riêng lưu tác giả, quyết định, câu bằng chứng và offsets.

## Đối chiếu nhóm ưu tiên

Bảng 1 trình bày quyết định cấp sự kiện. Mã nhóm tra được trong hàng chờ của [bản chia thử](validation-2026-11-16-group-kfold.md).

| Mã nhóm | Quyết định | Căn cứ và xử lý |
|---|---|---|
| `270a1b3` | `SAME_EVENT` | Thư công bố chiến dịch và thư hỏi đáp lặp lại cùng lịch tổng kết và hội quân. Ghi quan hệ `REPEATED_NOTICE`. |
| `3827339` | `SAME_EVENT` | Hai thư nói cùng hội nghị và khoảng ngày. Một thư báo đổi phòng, thư kia báo nghỉ lớp. Giữ hai email trong cùng fold và để quan hệ đầu việc là `UNRESOLVED`. |
| `97b0489` | `DIFFERENT_EVENT` | Một thư nói về ngày hội sức khỏe, thư kia nói về một kỳ hội nghị khoa học. Tên, mục đích và lịch khác nhau. Bỏ liên kết đề xuất. |
| `d37f86a` | `SAME_EVENT` | Cặp email ở nhóm `270a1b3` cũng lặp lại lịch ra quân của cùng chiến dịch. Giữ mốc ra quân riêng với mốc hội quân. |
| `e68e2d9` | `UNCLEAR` | Hai thư ghi cùng năm học nhưng trỏ tới tài liệu khác nhau và có phạm vi, mốc thời gian khác nhau. Giữ chúng cùng validation để tránh rò rỉ trong khi thiếu bằng chứng xác nhận phiên bản. |

Kết quả là 3/5 cùng sự kiện, 1/5 khác sự kiện và 1/5 chưa xác định. Hai nhóm cùng cặp email giải thích vì sao năm nhóm ứng với bốn cặp tài liệu. Mẫu được chọn vì vượt ranh giới, nên tỷ lệ này chỉ mô tả năm nhóm đã đọc.

## Đóng băng tập huấn luyện

Bản mới nằm tại `data/annotations/grouping-training-v3_3-2026-11-16/`. Bảng 2 ghi phân bổ sau khi giữ trọn các nhóm đã biết và áp dụng ràng buộc thận trọng cho 13 đề xuất còn thiếu xác nhận. Các ràng buộc thận trọng chỉ dùng khi chia tập.

| Split | Tài liệu | Thay đổi so với v3.3 |
|---|---:|---|
| train | 400 | Chuyển hai tài liệu vào excluded và một tài liệu vào validation |
| validation | 94 | Nhận một tài liệu nối với cặp kế hoạch năm học chưa xác định |
| test | 120 | Loại sáu tài liệu đã xuất hiện trong mẫu phát triển hoặc lần đọc nguồn |
| domain_test | 62 | Giữ đủ thành viên web đã dành riêng |
| excluded | 8 | Sáu tài liệu test đã đọc và hai tài liệu train liên kết với chúng |

Năm fold theo seed 42 có 80 tài liệu mỗi fold. Phép kiểm tra đối chiếu mọi liên kết giữ cùng nhóm với cả split và fold, kết quả bằng 0 liên kết băng qua ranh giới. Tập train có 278 email và 122 tài liệu web. Mười sáu cặp gắn nhãn đều là cặp lần nhắc từ email, gồm 7 `SAME_EVENT`, 1 `UPDATE_OF` và 8 `DIFFERENT_EVENT`. Bảy cặp dương đến từ bản nhóm phát triển đã được người dùng chấp nhận ở cấp nhóm. Một cặp dương và tám cặp âm có quyết định mới do trợ lý đối chiếu nguồn. Giữ nhãn và tác giả tại từng cặp để phân biệt với nhãn cặp độc lập của con người.

Đọc các tệp dưới `train/` để thử nghiệm. `pairs.jsonl` nối hai mã lần nhắc trong `mentions.jsonl` và lưu fold của từng tài liệu. Khi chạy fold `i`, fit trên cặp có cả hai đầu ngoài `i` và đánh giá trên cặp có cả hai đầu thuộc `i`. Cặp âm có đúng một đầu trong fold `i` nằm ngoài lượt đó. Các trường về quyết định, tác giả và nguồn gốc nhãn dùng để truy vết. Chỉ một fold có cả cặp dương và cặp âm ở phần đánh giá, và 16 cặp chủ yếu đến từ vài loại thông báo. Đây là dữ liệu thử nghiệm, chưa có kết quả huấn luyện hay chất lượng tổng quát. Gói dùng các lần nhắc đã kiểm tra offsets từ hai bản assembly có sẵn. Phần điều kiện đối tượng của annotation v3.3 vẫn có [lỗi tương thích đã ghi nhận](validation-2026-11-16-group-kfold.md#cấu-trúc-và-khả-năng-đọc-dữ-liệu).

## Tái tạo và kiểm tra

`record.json` và `checksums.json` ghi hash đầu vào, đầu ra, Python 3.12.13, seed, phân bổ và số cặp theo fold. `split_changes.jsonl` ghi từng thay đổi và `review_only/source_reviews.jsonl` lưu bằng chứng dùng cho duyệt. Dùng một thư mục đích mới để chạy lại từ thư mục gốc.

```powershell
uv run --offline --no-sync python reports/generated/grouping-training-review-2026-11-16/freeze.py `
  --output-dir data/annotations/grouping-training-replay-2026-11-16
```

Lần chạy lại tạo 10 tệp giống từng byte. Kiểm tra độc lập xác nhận cả 25 ràng buộc giữ nhóm, 21 lần nhắc trong các cặp huấn luyện và 25 checksum của gói nguồn. Không tài liệu nào xuất hiện trong cả phần fit và validation của cùng lượt. Bộ kiểm thử có 362 ca đạt, Ruff và kiểm tra format đạt, demo offline chạy thành công.
