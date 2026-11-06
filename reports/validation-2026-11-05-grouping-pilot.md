# Chuẩn bị mẫu gộp sự kiện, ngày 05/11/2026

Bản ghi này mô tả việc chuẩn bị mẫu phát triển từ batch dự đoán Featherless đã có trong repository. Trợ lý đối chiếu các đoạn nguồn được chọn và ghi đề xuất gộp theo [tiêu chí gộp sự kiện](../docs/event-grouping.md). Chưa có kiểm duyệt nhãn cặp, xác nhận riêng tư hoặc adjudication của con người; các số lượng dưới đây không đo chất lượng mô hình hay độ chính xác của việc gộp.

## Nguồn và môi trường

Nguồn là `data/annotations/drive-auto-label-2026-11-04/`. Không gọi lại nhà cung cấp mô hình, không sửa nguồn và không tạo completion Label Studio. Package ở commit `b2056e5`; môi trường Windows, Python 3.12.13, uv 0.11.1, Pydantic 2.14.1 và SmartNotice 0.1.0. Lần tạo gói ghi nhận lúc 15:30 ngày 05/11/2026, múi giờ UTC+07:00.

| Đầu vào | SHA-256 |
|---|---|
| `tasks.json` | `d4113822f703ffe9aab9f7574019d0abec52c89f7effc29b4ef2ef3b6c503f14` |
| `notices.compat.jsonl` | `ba33789fb9fffdc1dffbb6e870a76dad7ca0b6eded65e6252256bbfa0881fc4c` |
| `manifest.jsonl` | `07b75fdd769afa3dbb6648c4643c893daced51f6d762e9a6bbf80aca1d9c6223` |
| `uv.lock` | `9579c05dcdcd3319fd08644c3aedf0321c15f9d04ffdf13a9b50d00bdaa97941` |

Script dùng các hàm chuyển đổi và kiểm tra hiện có để kiểm tra cấu trúc trong bộ nhớ với tác giả `model_prediction`. Không ghi các bản chuyển đổi này như annotation của con người. Metadata gốc, hashes, ID và số lượng được đối chiếu với manifest cho toàn bộ 434 tài liệu và 1.630 sự kiện dự đoán.

## Mẫu được chọn

Gói nằm tại `data/annotations/event-grouping-pilot-2026-11-05/`. Mẫu chọn có chủ đích qua tìm các đoạn gần giống và các thông báo nhắc lại, gia hạn, khác đợt, khác công việc và trích xuất chưa đủ rõ. Không lấy mẫu ngẫu nhiên; không có seed lựa chọn. Lựa chọn cụ thể, đề xuất và script tái tạo nằm trong gói cục bộ. Đây là tập phát triển được dùng để soạn tiêu chí, chưa có phân công train/validation/test và không phải tập kiểm tra độc lập.

| Thành phần | Số lượng |
|---|---:|
| Tài liệu được đưa vào gói | 34 |
| Tài liệu có lần nhắc được chọn | 30 |
| Lần nhắc được chọn | 33 |
| Cặp sự kiện | 20 |
| Đề xuất `SAME_EVENT` của trợ lý | 8 |
| Đề xuất `UPDATE_OF` của trợ lý | 2 |
| Đề xuất `DIFFERENT_EVENT` của trợ lý | 8 |
| Đề xuất `UNCLEAR` của trợ lý | 2 |
| Tài liệu không có sự kiện dự đoán, đưa vào hàng chờ kiểm tra | 4 |
| Trích dẫn bổ sung có offsets, ngoài các câu bằng chứng của dự đoán | 59 |
| Quyết định cặp được con người hoàn thành | 0 |

Phiếu đọc nêu riêng các vấn đề ACTION ghép nhiều hoạt động, ACTION bị cắt, TIME role khác nhau trên cùng đoạn nguồn và khoảng ngày bị gán toàn bộ thành DEADLINE. Các ghi chú là nhận xét của trợ lý, cần người gán nhãn xác nhận và sửa; chưa tự sửa nhãn hoặc offsets trong batch gốc.

## Kiểm tra đã thực hiện

Chạy bằng uv từ thư mục gốc. Trong phiên này, đặt `UV_CACHE_DIR=tmp/uv-cache` để dùng vùng cache có quyền ghi và `PYTHONIOENCODING=utf-8` để hiển thị tiếng Việt. Không thay đổi dependency.

| Kiểm tra | Kết quả |
|---|---|
| SHA-256 của các file batch có trong manifest checksums | Khớp trước và sau khi tạo gói |
| Notice, provenance dự đoán, spans, links và câu bằng chứng trên toàn đầu vào | Qua kiểm tra cấu trúc cho 434 tài liệu, 1.630 sự kiện |
| Các spans/câu bằng chứng được chọn và 59 trích dẫn bổ sung | Khớp `text[start:end]` |
| Tập con task so với task gốc | Các object không đổi; không thêm `annotations` |
| Tập con Notice so với nguồn | Giữ nguyên bytes của các dòng được chọn |
| Quyết định người duyệt và approvals | Để trống/chưa xác nhận; không sinh xác nhận của con người |
| Tái tạo gói sang thư mục mới | 11 file nội dung ổn định khớp từng byte |
| File metadata khi tái tạo | `run.json` ghi thời điểm và đường dẫn script/selection của lần chạy mới; `checksums.json` phản ánh các bytes tương ứng |

Lệnh tái tạo đã chạy thành công:

```powershell
uv run --offline python data/annotations/event-grouping-pilot-2026-11-05/prepare_sample.py --selection data/annotations/event-grouping-pilot-2026-11-05/selection.json --output-dir reports/generated/event-grouping-pilot-recheck
```

Đầu ra đối chiếu tổng hợp ở `reports/generated/event-grouping-pilot-2026-11-05/verification.json`. Gói mẫu và đầu ra tái tạo đều bị Git bỏ qua. Mã package và schema chính không thay đổi; không chạy lại bộ kiểm thử phần mềm cho công việc chuẩn bị dữ liệu này.

## Việc con người cần hoàn thành

Người duyệt kiểm tra riêng tư trên đúng văn bản, sửa trích xuất, xác nhận các cặp và giữ các trường chưa rõ ở trạng thái chưa giải quyết. Bốn tài liệu không có dự đoán cần được đọc để xác định có bỏ sót hay không. Những quyết định này chưa được thực hiện trong lần chuẩn bị mẫu. Chỉ xây nhóm chính thức sau khi giải quyết các tham chiếu bị ảnh hưởng bởi việc sửa ACTION và các mâu thuẫn trong nhóm.
