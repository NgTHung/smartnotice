# Kiểm tra crawler HCMUS ngày 27/10/2026

Bản ghi này giúp người review đánh giá crawler trước khi đưa thay đổi lên nhánh chia sẻ. Phạm vi gồm kiểm thử phần mềm bằng dữ liệu tổng hợp, một pilot trên website HCMUS và đối chiếu tệp nguồn với đầu ra chuẩn bị dữ liệu. Kết quả không thay thế việc người duyệt xác nhận phạm vi nghiên cứu, ngày đăng, thông tin cá nhân hoặc nhãn sự kiện.

## Xác định phiên bản và môi trường

Mã được triển khai trên nhánh local `hcmus-web-crawler`, từ commit `5e1cce8`. Lần kiểm tra ban đầu bên dưới ghi nhận trạng thái trước commit và push để người dùng review. Phần xác minh cuối ghi kết quả sau yêu cầu push của người dùng. Không thay đổi dependency, `uv.lock`, ví dụ nguồn tổng hợp hoặc schema `Notice`.

Môi trường kiểm tra là Windows, Python 3.12.13 và uv 0.11.28. Các phiên bản được đọc từ môi trường chạy: HTTPX 0.28.1, Beautiful Soup 4.15.0, Pydantic 2.14.1, pytest 9.1.1 và Ruff 0.17.1. Lệnh chạy từ thư mục gốc repository và dùng môi trường uv hiện có.

Các lệnh kiểm tra cục bộ dùng bộ nhớ đệm và thư mục tạm dưới `tmp/` vì thư mục tạm mặc định của phiên làm việc không cho ghi. Lỗi này thuộc môi trường, không được tính là lỗi collector. Lượt mạng đầu gặp lỗi DNS trong phiên hạn chế kết nối; các lượt pilot thực tế chạy trong phiên có kết nối đến nguồn công khai.

## Kiểm tra phần mềm

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) 'tmp/uv-cache'
uv run --offline --no-sync pytest --basetemp tmp/pytest-crawler-handoff -q
uv run --offline --no-sync ruff check .
uv run --offline --no-sync ruff format --check .
uv run --offline --no-sync smartnotice demo
git diff --check
```

Tùy chọn `--offline --no-sync` dùng môi trường đã được cài theo README, không yêu cầu tải thêm thư viện. Khi chạy lại pytest, chọn thư mục `--basetemp` dành riêng cho lần chạy đó vì pytest quản lý nội dung thư mục này.

Bảng 1. Kết quả kiểm tra phần mềm ở lần bàn giao ban đầu.

| Kiểm tra | Quan sát |
|---|---|
| Toàn bộ pytest | 120 ca đạt |
| Ruff kiểm tra mã | Đạt |
| Ruff kiểm tra định dạng | 55 tệp đúng định dạng |
| Demo ngoại tuyến | 9 tài liệu tổng hợp, 25 câu, 30 cặp sự kiện/hồ sơ; không có nhóm vượt ranh giới split |
| Kiểm tra diff | Không có lỗi khoảng trắng |

Các ca tự động dùng HTML tổng hợp và HTTP giả lập, không gọi website thật. Phạm vi gồm robots và chuyển hướng, khoảng nghỉ Crawl-delay/Request-rate, gzip, giới hạn kích thước sau giải nén, loại nội dung, URL tương đối/query/fragment, selector, ngày thiếu hoặc xung đột, phạm vi tiêu đề, đoạn giới thiệu file đính kèm, văn bản ngắn, bảng, Unicode, lọc trùng, hết ứng viên, CLI và trạng thái lỗi.

Lỗi gzip được tái hiện trước khi sửa: phản hồi hợp lệ gây `httpx.DecodingError` vì header nén được giữ lại sau khi nội dung đã giải nén. Sau sửa, cả ca streaming gzip và giới hạn nội dung giải nén đều đạt. Các ca hồi quy cho đoạn giới thiệu tài liệu và bộ đếm lượt xem cũng đã thất bại trước khi sửa hành vi tương ứng.

Kiểm tra lưu trữ mô phỏng lỗi thay manifest và xác nhận manifest trước đó cùng nguồn vừa tải còn đọc được. Kiểm tra điều phối xác nhận lỗi mạng, HTTP bị từ chối, lỗi chuẩn bị, lỗi lưu trữ, lỗi bất ngờ và Ctrl+C không bị báo thành công. Kiểm thử không mô phỏng việc tắt máy, hỏng ổ đĩa hoặc phối hợp nhiều tiến trình.

## Đối chiếu pilot thực tế

Nguồn là chuyên mục [Thông tin dành cho người học](https://hcmus.edu.vn/thong-tin-danh-cho-nguoi-hoc/). Tập được xác định bởi thư mục local `data/raw/crawls/hcmus-academic-pilot-20261027/`, chứa manifest, hash nguồn, cấu hình và thời điểm lấy. Các lượt khảo sát trước đó không được cộng vào kết quả pilot này.

```powershell
uv run --offline --no-sync smartnotice crawl-web --run-id hcmus-academic-pilot-20261027 --limit 10 --max-candidates 40
```

Lệnh trên ghi nhận lần chạy ngày 27/10/2026 từ 19:07:50 đến 19:08:43, UTC+07:00. Khi thu thập lại, phải chọn run ID mới; trạng thái website và hash HTML có thể thay đổi. Lượt này dùng khoảng nghỉ cấu hình 2 giây, ngưỡng cảnh báo văn bản ngắn 100 ký tự, `domain_holdout=false` và không gán nhóm thủ công.

Bảng 2. Kết quả thu thập và đối chiếu của pilot HCMUS.

| Đại lượng của lượt chạy | Kết quả |
|---|---:|
| Link chi tiết khác nhau trong một trang danh sách | 1.000 |
| Tiêu đề qua bộ lọc học vụ | 457 |
| Trang chi tiết đã thử / ngân sách | 22 / 40 |
| Trang bị loại vì thiếu đoạn hành động độc lập | 12 |
| Văn bản được chọn tự động, khác nhau | 10 |
| Snapshot HTML, gồm trang danh sách | 23 |
| Hash nguồn và văn bản được đối chiếu | 10 / 10 |
| Câu có offset được đối chiếu | 261 |
| Độ dài văn bản sau chuẩn bị | 252–10.359 ký tự |
| Bài có cảnh báo ngữ cảnh đính kèm | 2 |
| Bài có cảnh báo ô bảng gộp | 1 |
| Ngày đăng ở trạng thái `unverified` | 10 |
| Quyết định duyệt của con người đã ghi nhận | 0 |

Đối chiếu kiểm tra SHA-256 của HTML, bản snapshot và `raw_sha256`; kiểm tra `doc_id`, URL nguồn, manifest và văn bản qua đúng selector. Hash văn bản được tính lại sau chuẩn hóa, che định danh. Toàn bộ 261 câu có offset trong giới hạn, không chồng lấn và thỏa `text[start:end] == sentence.text`. Bộ đếm lượt xem không xuất hiện trong đầu ra được chọn.

Tệp local `audit_run.py` lưu thao tác đối chiếu và tạo lại `audit.json` cùng `review.md`. Chạy lại trên đúng bộ dữ liệu được lưu bằng:

```powershell
uv run --offline --no-sync python data/raw/crawls/hcmus-academic-pilot-20261027/audit_run.py
```

Các tệp này nằm cùng corpus bị Git bỏ qua, không có trong bản clone chỉ chứa mã nguồn. Người kiểm tra cần quyền truy cập bộ dữ liệu local tương ứng. Bản đọc `review.md` chứa nguồn, ngày ứng viên, cảnh báo, văn bản đầy đủ và các ô duyệt còn trống cho từng bài.

## Những quyết định còn chờ review

Mười bài là kết quả chọn tự động để người dùng review, không phải mười tài liệu đã được duyệt dùng cho nghiên cứu. Cần kiểm tra riêng các trường hợp sau trước khi gán nhãn:

1. Bài kế hoạch Giáo dục Quốc phòng có phần hướng dẫn nằm trong file đính kèm. Cảnh báo `attachment_context_review` yêu cầu quyết định phần chữ HTML có đủ cho mục tiêu gán nhãn hay phải thay bằng bài khác.
2. Bài nghỉ học do cúp điện có nội dung hành động trong HTML nhưng danh sách lớp nằm ở link ngoài. Người duyệt cần phân biệt thông tin đã có với thông tin không được crawler tải.
3. Bài xét tốt nghiệp có ô bảng gộp. Parser giữ các ô xuất hiện trong từng hàng, không trải giá trị `rowspan` sang các hàng sau. Không suy luận rằng mốc thời gian ở một hàng tự áp dụng cho mọi hàng còn lại trước khi đối chiếu HTML.
4. Bài đăng ký học phần có ô ngày kết thúc ghi năm 2025 trong lịch năm học 2026. Nguồn và giá trị được giữ nguyên; crawler không tự sửa lỗi nội dung nguồn. Người duyệt cần ghi nhận cách xử lý trước khi chuẩn hóa nhãn ngày.
5. Một số tên người, số liên hệ và nội dung tự do còn trong văn bản sau che định danh tự động. Không coi cờ lọc tự động hoặc tệp bị Git bỏ qua là bằng chứng đã ẩn danh.

Tất cả `reference_date` trong manifest và Notice giữ null. Ngày đọc từ nguồn nằm trong index, không bị dùng thay cho ngày đã xác minh. Các cờ privacy/date/content review giữ true; bản ghi này không phê duyệt thay người dùng.

## Bàn giao để review mã

Đọc [quy trình thu thập](../docs/collection.md), [tham chiếu crawler](../docs/crawler.md) và [hợp đồng dữ liệu](../docs/interface.md). Lệnh mới nằm trong [README](../README.md). Diff gồm điều phối crawler, adapter HCMUS, thay đổi HTTP liên quan, kiểu bản ghi, ghi JSONL, loại bộ đếm lượt xem, kiểm thử và tài liệu.

Chỉ có một nguồn HTML, một trang danh sách, xử lý tuần tự và lọc trùng trong lượt chạy. Chưa có phân trang, tải PDF/OCR, trình duyệt JavaScript, tự tiếp tục lượt lỗi hoặc phối hợp nhiều tiến trình. Không chạy huấn luyện, đo chất lượng mô hình, gán nhãn con người hoặc chia bộ pilot này thành tập nghiên cứu.

Dữ liệu thật và bản đọc local nằm dưới đường dẫn bị Git bỏ qua; không đưa vào phần mã và tài liệu chia sẻ. Lần bàn giao ban đầu chờ người dùng review; lần xác minh cuối phục vụ yêu cầu đẩy mã lên nhánh `hcmus-web-crawler` sau đó.

## Xác minh cuối trước khi push, ngày 27/10/2026

Người dùng yêu cầu kiểm tra code, tài liệu và push lên nhánh công việc. Việc cho phép push mã không được coi là phê duyệt ngày đăng, thông tin cá nhân hoặc nội dung của corpus.

Đối chiếu remote xác nhận `main` trên GitHub ở commit gốc `5e1cce8` và chưa có nhánh `hcmus-web-crawler` tại thời điểm kiểm tra. Nhánh công việc được xuất bản riêng, không merge vào `main`.

Rà soát bổ sung tái hiện hai trường hợp bằng dữ liệu tổng hợp trước khi sửa. Cổng URL `0` bị coi như thiếu cổng, khiến giới hạn origin không phân biệt được đích chuyển hướng đó; mã giữ nguyên mọi cổng khác cổng mặc định. Một metadata thời gian sát giới hạn năm làm chuyển múi giờ phát sinh `OverflowError`; adapter ghi `invalid` và giữ bằng chứng ngày thay vì làm hỏng lượt thu thập. Các ca hồi quy kiểm tra cả chuẩn hóa origin, chuyển hướng, tìm link và metadata ngày.

Các lệnh dưới đây chạy từ repository với môi trường uv đã cài:

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) 'tmp/uv-cache'
uv run --offline --no-sync pytest --basetemp tmp/pytest-final-before-push-20261027 -q
uv run --offline --no-sync ruff check .
uv run --offline --no-sync ruff format --check .
uv run --offline --no-sync smartnotice demo
```

Bảng 3. Kết quả xác minh phần mềm cuối trước khi xuất bản nhánh.

| Kiểm tra | Kết quả |
|---|---|
| Kiểm thử liên quan collector, crawler, lưu trữ và HTML | 99 ca đạt |
| Toàn bộ pytest | 123 ca đạt |
| Ruff kiểm tra mã | Đạt |
| Ruff kiểm tra định dạng | 56 tệp đúng định dạng |
| Demo ngoại tuyến | 9 tài liệu tổng hợp, 25 câu, 30 cặp; không có nhóm vượt ranh giới split |

Tài liệu được đối chiếu với các tham số CLI và cấu trúc đầu ra. Quy trình review dùng bản manifest riêng cùng thư mục nguồn, giữ manifest tự động làm bằng chứng. Các giới hạn đã ghi về từ khóa chọn bài, tài liệu đính kèm, bảng gộp, ngày nguồn và riêng tư tiếp tục áp dụng. Lần xác minh này không tải lại website và không thay đổi corpus của người dùng.
