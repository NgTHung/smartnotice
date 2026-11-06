# Kiểm chứng bản thử nghiệm gộp sự kiện, ngày 05/11/2026

Lần chạy này tạo `hien.json` theo cấu trúc Label Studio của file người dùng cung cấp và thử nghiệm gộp các lần nhắc từ dự đoán Featherless hiện có. Mười tài liệu được trợ lý đọc và gán nhãn; chưa có annotation hoặc adjudication của con người cho phần nhãn mới. Các nhóm đầu ra là đề xuất quy tắc, chưa có đo độ chính xác.

## Chọn và gán nhãn mười tài liệu

Tập lấy mẫu gồm toàn bộ 434 document ID trong `data/annotations/drive-auto-label-2026-11-04/tasks.json`, sắp tăng dần. Lựa chọn dùng `random.Random(DEFAULT_SEED).sample(..., 10)` với seed 42, không hoàn lại và không đổi mẫu khi gặp tài liệu khó. Mười ID được chọn không trùng mười ID trong file tham chiếu do người dùng cung cấp. Lựa chọn này là mẫu phát triển, không phải tập kiểm tra độc lập.

| Đầu ra cục bộ | Nội dung |
|---|---|
| `data/annotations/assistant-labels-2026-11-05/hien.json` | 10 task, 26 sự kiện và 97 span do trợ lý tạo từ nguồn |
| `assistant_annotations.jsonl` trong cùng gói | Annotation canonical với `annotator_id="ai_assistant"` |
| `selection.json` | Seed, quần thể, thứ tự lấy mẫu và các document ID |
| `annotation_notes.md` | Ghi chú ngày mâu thuẫn, khoảng thời gian, cụm từ bị xuống dòng và phạm vi công việc |
| `reference/phat.json` | Bản tham chiếu do người dùng cung cấp, giữ nguyên bytes |
| `original_predictions.json` | Các task dự đoán gốc tương ứng, tách khỏi nhãn mới |
| `create_hien.py`, `run.json`, `checksums.json` | Script tái tạo, provenance và hashes |

`hien.json` giữ layout task/annotation/result, binding `entities`/`notice` và quan hệ ACTION tới argument của file tham chiếu. Không sao chép người dùng Label Studio, project, thời lượng gán nhãn hay trạng thái ground truth. `completed_by` để null, `ground_truth=false`, meta và draft origin ghi rõ AI. Cấu trúc và offsets đã kiểm tra cục bộ; chưa xác nhận hiển thị hoặc import trong giao diện Label Studio thực.

Trường hợp một nguồn ghi cả năm 2014 và 2024 được giữ nguyên hai giá trị để người duyệt giải quyết. Không dùng ngày gửi email để tự sửa năm, không chuẩn hóa lại prepared text và không gán mọi mốc sự kiện thành hạn đăng ký. Các lời mời của kẻ lừa đảo trong một tài liệu cảnh báo không được chuyển thành công việc hợp lệ của sinh viên.

## Cấu hình bản thử nghiệm

Mã quy tắc ở [`grouping.py`](../src/labeling/grouping.py), phiên bản `event-grouping-prototype-v1`. Hàm chuyển đổi dự đoán kiểm tra Notice, provenance, spans và links trước khi chạy. Lệnh gọi nằm trong [README](../README.md); [tiêu chí gộp](../docs/event-grouping.md) giải thích các điều kiện và giới hạn.

Mặc định dùng Jaccard tối thiểu 0,8 và ít nhất ba từ có thông tin chung để chọn cặp ứng viên. Quy tắc tự đề xuất nhóm chỉ khi ACTION và các câu bằng chứng chuẩn hóa trùng nhau, ACTION có đủ thông tin, mốc ngày hoặc kỳ học khớp và không gặp các xung đột đã định nghĩa. Mọi cặp trong cùng nhóm phải được quy tắc chấp nhận. Cặp chưa rõ và đề xuất cập nhật giữ riêng. Không khớp có nghĩa là chưa có bằng chứng đủ mạnh, không phải một nhãn phủ định của con người.

Không dùng `phat.json`, `hien.json` hoặc các đề xuất cặp trước đó để tối ưu ngưỡng hay tính metric. Thuật toán không có tham số được fit hoặc thành phần ngẫu nhiên. Giữ nguyên source text, mọi mốc thời gian và split assignments; không tạo API, giao diện web hoặc mô hình huấn luyện.

## Đầu vào và lần chạy

Môi trường Windows, Python 3.12.13 và uv 0.11.1, sử dụng khóa dependency hiện có. Mã trong lần chạy được định danh bằng SHA-256 các module, script và `uv.lock` tại `run.json`. Lần chạy chính ghi nhận lúc 16:52:38 ngày 05/11/2026, múi giờ UTC+07:00.

| Nguồn | SHA-256 |
|---|---|
| Batch `tasks.json` | `d4113822f703ffe9aab9f7574019d0abec52c89f7effc29b4ef2ef3b6c503f14` |
| Batch `notices.compat.jsonl` | `ba33789fb9fffdc1dffbb6e870a76dad7ca0b6eded65e6252256bbfa0881fc4c` |
| File tham chiếu `phat.json` | `95104ef0526738836f1b2cc7a30a2ce6ea70cc84ab10ec2f83954954252821e3` |

Lệnh chạy chính:

```powershell
uv run --offline python tools/run_event_grouping.py
```

Đầu ra nằm tại `data/processed/event-grouping-prototype-2026-11-05/`.

| Số đếm quy trình | Kết quả |
|---|---:|
| Tài liệu nguồn | 434 |
| Lần nhắc sự kiện từ mô hình | 1.630 |
| Cặp đã xét | 1.327.635 |
| Cặp qua ngưỡng ứng viên | 364 |
| Đề xuất `SAME_EVENT` | 10 |
| Đề xuất `DIFFERENT_EVENT` | 7 |
| Đề xuất `UNCLEAR` | 347 |
| Đề xuất `UPDATE_CANDIDATE` | 0 |
| Nhóm có nhiều thành viên | 8 |
| Lần nhắc trong các nhóm có nhiều thành viên | 17 |
| Nhóm đơn | 1.613 |
| Tổng nhóm, tính cả nhóm đơn | 1.621 |

Thời gian kiểm tra đầu vào là 0,260 giây; thời gian gộp là 1,002 giây theo `perf_counter` trong lần chạy chính. Đây là thời gian của một lần chạy cục bộ, không phải benchmark hoặc kết quả tối ưu. Chưa có ứng viên cập nhật qua ngưỡng không chứng minh corpus không có thông báo gia hạn.

## Kiểm tra và tái tạo

| Kiểm tra | Kết quả |
|---|---|
| Bộ kiểm thử đầy đủ | 281 ca đạt |
| Ruff check và format check | Đạt |
| Offline demo | 9 tài liệu tổng hợp, 5 annotation, 30 cặp; không có nhóm đi qua nhiều split |
| Format `hien.json` so với tham chiếu | Các bộ khóa task/data/annotation khớp; không sao chép reviewer |
| Các nhãn mới và toàn bộ spans/câu bằng chứng trong đầu ra gộp | Khớp văn bản prepared nguồn |
| Tái tạo lựa chọn và annotation canonical của `hien.json` | Khớp từng byte |
| Tái tạo `events.jsonl`, `groups.jsonl`, `pair_decisions.jsonl`, `review_groups.md` | Khớp từng byte |
| Bảo toàn thành viên | Đủ 1.630 lần nhắc, mỗi lần thuộc đúng một nhóm |
| Các nhóm nhiều thành viên | Mọi cặp thành viên có đề xuất `SAME_EVENT`; không có hai lần nhắc cùng tài liệu |
| Hash batch gốc, tham chiếu và mã chạy | Khớp sau khi chạy |

Chạy pytest với `--basetemp tmp/pytest-event-grouping-full -o cache_dir=tmp/pytest-cache-grouping` vì thư mục tạm mặc định của Windows bị giới hạn quyền trong phiên. Đặt `UV_CACHE_DIR=tmp/uv-cache` và `PYTHONIOENCODING=utf-8`. Không thay đổi dependency. Các ca hồi quy gồm dấu gạch năm học, mã năm học chưa được quy đổi, ngày mâu thuẫn, vai trò thời gian khác nhau, khoảng ngày chưa tách, tác vụ khác nhau và integrity của dự đoán.

Lệnh tái tạo đã chạy thành công:

```powershell
uv run --offline python tools/run_event_grouping.py --output-dir reports/generated/event-grouping-prototype-recheck
uv run --offline python data/annotations/assistant-labels-2026-11-05/create_hien.py --output-dir reports/generated/hien-recheck
```

Các script từ chối output đã tồn tại; chọn tên mới khi chạy lại. Thời điểm tạo file nhãn, metadata lần chạy và thời gian xử lý thay đổi giữa các lần chạy. Bản đối chiếu tổng hợp nằm tại `reports/generated/event-grouping-prototype-2026-11-05/verification.json`.

Các file dữ liệu và đầu ra sinh tự động được Git bỏ qua. Chưa có xác nhận riêng tư của con người hoặc Human review cho nhãn mới và nhóm đề xuất. Cần review, sửa các trường chưa rõ và đánh giá trên bộ nhãn phù hợp trước khi dùng kết quả làm bằng chứng chất lượng nghiên cứu.
