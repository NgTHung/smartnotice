# Rà soát mẫu gộp sự kiện, ngày 06/11/2026

Trợ lý đọc lại các nguồn trong gói phát triển và áp dụng tiêu chí hai câu hỏi của [quy trình gộp sự kiện](../docs/event-grouping.md). Kết quả là bản nháp sửa trích xuất, đề xuất quan hệ cặp và các vị trí cần kiểm tra riêng tư. Không có annotation, adjudication hoặc xác nhận riêng tư của con người; số đếm dưới đây mô tả công việc chuẩn bị, không đo chất lượng.

## Nguồn và phạm vi

Đầu vào là gói `data/annotations/event-grouping-pilot-2026-11-05/` và batch dự đoán được gói đó tham chiếu. Snapshot trước khi rà soát lưu SHA-256 của 23 file, gồm toàn bộ file gói mẫu, bốn file batch, tiêu chí, contract, module chuyển đổi/validation, schema và dependency lock. Dự đoán được chuyển đổi và kiểm tra bằng `import_prediction_tasks`; không gọi nhà cung cấp hoặc tải nội dung từ liên kết ngoài.

Gói bàn giao cục bộ nằm tại `data/annotations/event-grouping-review-2026-11-06/`. Mở `README.md` tại đó, rồi đọc `draft/review_worksheet.md`. Các file chứa văn bản thực, annotation và ghi chú riêng tư đều được Git bỏ qua. Gói cũ, prepared text, dự đoán gốc và split assignments giữ nguyên.

| Phạm vi | Số lượng |
|---|---:|
| Tài liệu nguồn được đọc | 34 |
| Sự kiện trong dự đoán gốc của gói | 171 |
| Lần nhắc được chọn, trợ lý rà soát trích xuất | 33 |
| Cặp được trợ lý đọc lại | 20 |
| Tài liệu không có dự đoán được kiểm tra | 4 |
| Mảnh ACTION hợp nhất về cùng yêu cầu khảo sát | 2 |
| Ứng viên tham gia bổ sung từ tài liệu không có dự đoán | 1 |
| Sự kiện trong annotation nháp sau sửa | 170 |
| Sự kiện lân cận giữ nguyên, ngoài phạm vi rà soát nghĩa | 136 |

`draft/assistant_annotations.jsonl` chứa annotation canonical với tác giả `ai_assistant`. File bao gồm cả các dự đoán lân cận để tránh làm mất sự kiện khi đối chiếu. `event_origin.jsonl` phân biệt phần trợ lý rà soát với phần giữ nguyên chưa duyệt. Đây không phải completion Label Studio hoặc annotation đã đáp ứng `import-reviewed-labels`.

## Đề xuất cặp và sửa trích xuất

| Nhãn đề xuất của trợ lý | Số cặp |
|---|---:|
| `SAME_EVENT` | 12 |
| `UPDATE_OF` | 2 |
| `DIFFERENT_EVENT` | 5 |
| `UNCLEAR` | 1 |

Năm cặp đổi đề xuất so với gói cũ. Các cặp `p015`–`p018` chuyển từ `DIFFERENT_EVENT` sang `SAME_EVENT` ở cấp nhóm; ghi chú giữ riêng phiên, đầu việc hoặc nghĩa vụ phát sinh theo điều kiện. Cặp `p019` chuyển từ `UNCLEAR` sang `DIFFERENT_EVENT` sau khi đọc được mã học kỳ và biểu mẫu riêng của hai đợt. Cặp `p020` giữ `UNCLEAR` vì hướng dẫn đổi mật khẩu có thể chỉ là bước hỗ trợ dùng lại, chưa chốt đơn vị sự kiện.

Các sửa trích xuất gồm tách đầu khoảng thời gian, chuyển hạn gia hạn về đúng đầu việc, bỏ TIME gán nhầm cho năm của đợt và bỏ DOCUMENT gán nhầm cho địa điểm hoặc tên phiên. Hai mảnh ACTION bị cắt của mỗi nguồn khảo sát giữa kỳ được hợp nhất về một ACTION hoàn chỉnh có trong nguồn. `extraction_review.jsonl` lưu bản trước/sau; `reference_migrations.jsonl` giữ tham chiếu các mảnh đã hợp nhất.

Hai cặp cập nhật giữ chiều từ bản mới đến bản trước, cùng phạm vi và trích dẫn giá trị cũ/mới. Bản nháp không gán hạn thực hiện phiếu sang hạn nộp giấy khám thay thế. Các ACTION ghép nhiều hoạt động trong cùng phiên, vai trò mốc cuối khoảng khi schema không có END và ngày bị chèn dấu định dạng vẫn được ghi rõ để người duyệt quyết định; không sửa prepared text để giải quyết chúng.

Trong bốn tài liệu không có dự đoán, một nguồn tiếng Anh có ứng viên tham gia cần người duyệt xác nhận phạm vi corpus; hai nguồn thiếu nội dung do chỉ nhắc file đính kèm hoặc tên poster; một nguồn bổ sung vị trí phòng nhưng thiếu mục tiêu để xác lập cập nhật. Không suy nội dung file, thời hạn hoặc sự kiện đích còn thiếu.

## Kiểm tra riêng tư

`draft/privacy_findings.jsonl` ghi 38 cờ rà soát trên 17 tài liệu. Các nhóm cờ gồm thông tin thanh toán, tên còn sót, truy cập cuộc họp, liên kết bảng tính ngoài, tham số theo dõi, thông tin tiểu sử có khả năng nhận diện và hướng dẫn tài khoản cần đọc khi duyệt chia sẻ. Cờ là ứng viên cần kiểm tra, có thể cùng trỏ một vùng nguồn; không phải số lượng vi phạm đã được con người xác nhận.

Hàng chờ riêng tư bao gồm cả 34 tài liệu, giữ mẫu approval chưa xác nhận. Không có cờ không có nghĩa là văn bản đã được duyệt. Các ô quyết định trong `draft/human_pair_review.jsonl` được sao chép nguyên từ mẫu và vẫn để trống; bản nháp AI nằm ở file riêng. Không ghi nhận người duyệt, thời điểm duyệt hoặc quyền đưa dữ liệu lên dịch vụ ngoài thay cho con người.

## Kiểm chứng và tái tạo

Lần kiểm chứng dùng Windows, Python 3.12.13, dependency lock của workspace và mã tại commit `0e85f88` cùng script curation cục bộ. `draft/run.json` lưu hashes tiêu chí, script, lock, snapshot nguồn và môi trường. Các cặp tham chiếu hash annotation đã sửa; nguồn giữ hash raw và prepared text. Không có chọn mẫu ngẫu nhiên hoặc tham số được fit trong lần rà soát này.

Chạy bằng uv từ thư mục gốc. Cache dùng `tmp/uv-cache` vì cache mặc định bị giới hạn quyền trong phiên.

```powershell
uv run --offline python data/annotations/event-grouping-review-2026-11-06/prepare_review.py --output-dir reports/generated/event-grouping-review-2026-11-06-recheck
uv run --offline python data/annotations/event-grouping-review-2026-11-06/verify_review.py
uv run smartnotice validate-labels --notices data/annotations/event-grouping-pilot-2026-11-05/sample_notices.jsonl --annotations data/annotations/event-grouping-review-2026-11-06/draft/assistant_annotations.jsonl
```

Script curation từ chối thư mục đã tồn tại; chọn đường dẫn mới nếu tái tạo thêm. Script kiểm chứng đối chiếu đường dẫn recheck ghi trong mã. Lượt xuất kiểm tra đầu tiên giữ riêng trong `results/`; bản bàn giao để xem xét nằm ở `draft/`.

| Kiểm tra | Kết quả |
|---|---|
| 23 hash đầu vào trước/sau | Không đổi; checksums gói cũ khớp |
| Annotation canonical, offsets, kiểu và bằng chứng | 34 tài liệu, 170 sự kiện qua validation |
| Trích dẫn nguồn trong rà soát cặp, cập nhật và tài liệu không có dự đoán | 104 trích dẫn khớp văn bản và câu chứa |
| Tham chiếu cặp và phiên bản annotation | Đủ 20 cặp, khớp các hash snapshot sau sửa |
| Sự kiện lân cận chưa rà soát | 136 sự kiện và các span liên kết giữ nguyên |
| Tái tạo nội dung | 12 file khớp từng byte; metadata thời điểm và checksums tương ứng thay đổi |
| Liên kết trong hai README cục bộ | 9 liên kết tới file tồn tại |
| Ô người duyệt và approval | Không tạo quyết định hoặc clearance |

Đối chiếu tổng hợp lưu tại `reports/generated/event-grouping-review-2026-11-06/verification.json`. Ruff format đã chạy trên hai script cục bộ; script kiểm chứng qua Ruff check, script curation qua check khi bỏ kiểm tra độ dài dòng E501 cho các chuỗi trích dẫn và nội dung phiếu. Package không đổi; không chạy lại bộ kiểm thử phần mềm cho việc curation dữ liệu này.

Người dùng cần xem các đề xuất và sửa trích xuất còn chưa chốt, xử lý riêng tư trên đúng snapshot, rồi ghi quyết định thực. Lần rà soát này không tạo nhóm chính thức, không đo đồng thuận hoặc độ chính xác và không thay đổi mẫu phát triển thành tập kiểm tra độc lập.
