# Kiểm chứng bộ thông báo HCMUS-focused, 06/11/2026

Bộ dữ liệu chính gồm 100 thông báo web: 40 HCMUS, 30 UIT và 30 UEH. Chỉ tiêu từng trường được giữ cố định; việc thiếu mẫu HCMUS không được bù bằng trường khác. Báo cáo này ghi nhận kiểm chứng phần mềm và thu thập, không xác nhận gán nhãn hay rà soát thủ công của nhóm.

## Đối chiếu yêu cầu đồ án

[Đề xuất gốc](../docs/reference/proposal.pdf) xác định hai bài toán trích xuất tác vụ và xác định đối tượng áp dụng, trên thông báo web và email tự nguyện. Bộ này cung cấp một pilot web có nguồn, văn bản tiếng Việt, vị trí câu và bằng chứng ngày đăng. 100 tài liệu chưa đạt mục tiêu 200-300 thông báo web, 150-250 email và khoảng 1.000-2.000 sự kiện của đề xuất.

Nhãn ACTION/TIME/AUDIENCE/CONDITION/CHANNEL/DOCUMENT, ràng buộc đối tượng và ngày chuẩn hóa chưa được gán. Nhóm cần gán thử, đo thời gian gán, gán độc lập ít nhất 20% tài liệu được gán nhãn, và dành 40-50 thông báo web cho kiểm tra liên miền trước khi phát triển mô hình. Chưa chia train/validation/test; cần kiểm tra nhóm gần trùng và mẫu cập nhật trước khi chia. Các bước này thuộc [quy trình gán nhãn](../docs/annotation.md) và [đánh giá](../docs/evaluation.md).

[Yêu cầu môn học](../docs/reference/ml-project-3.pdf) còn có so sánh ít nhất ba mô hình, đánh giá, ứng dụng web và triển khai công khai. Kết quả crawl không chứng minh hoàn thành các phần đó.

## Kết quả thu thập

| Nguồn | Được giữ | Lượt thử trang chi tiết | Trạng thái |
|---|---:|---:|---|
| hcmus-student | 40 | 59 | complete |
| uit-student | 30 | 37 | complete |
| ueh-student | 30 | 34 | complete |

Ngày đăng ứng viên của bộ được chọn trải từ 12/03/2021 đến 05/11/2026. Không giới hạn nguồn trong năm 2026. Cả 100 tài liệu có ngày đăng ứng viên nhưng chưa được nhóm xác minh; `reference_date` vẫn để trống. Ngày đăng không được thay bằng ngày crawl hay hạn nộp.

Bộ lọc chọn tiêu đề học vụ, yêu cầu văn bản có hành động, bỏ bài chỉ dẫn sang tệp không có tác vụ độc lập, và bỏ bảng danh tính người học. Đã tái hiện bằng kiểm thử rồi sửa các lỗi: nhắc quy định làm loại nhầm bài đăng ký; đoạn chứa tác vụ có hạn nộp bị loại do nhắc tệp đính kèm; lấy quá nhiều trang danh sách trước khi đủ bài; nhầm đóng góp với đóng phí; lẫn thể loại giải đáp/cảnh báo/quyết định và việc dành cho cán bộ; bảng danh tính không được phát hiện qua tiêu đề; thiếu ngày UEH do selector sai vị trí.

Trong lượt rà phạm vi, 7 bài ban đầu được thay bằng bài cùng trường: 3 bài UIT về thể loại/đối tượng, 2 bài UIT có bảng danh tính, 2 quyết định cấp học bổng UEH. HTML nguồn không bị sửa; log giữ lý do loại và các tệp `audit_exclusions.jsonl` ghi mã tài liệu cùng lý do. Bộ cuối không còn các bài bị loại đó.

## Kiểm chứng toàn bộ 100 bản ghi

Đã chạy `tools/check_notice_dataset.py` sau khi dọn kết quả cũ. Kiểm tra lại toàn bộ:

- đúng 40/30/30 và 100 mã tài liệu, 100 mã băm văn bản khác nhau;
- trạng thái nguồn hoàn chỉnh, manifest và log nhận bài khớp chỉ mục tổng;
- đường dẫn nguồn nằm trong thư mục cho phép, tệp tồn tại và HTML/snapshot có đúng SHA-256;
- tiêu đề, phần nội dung, chuẩn hóa, số lần che thông tin và độ dài khớp khi phân tích lại HTML;
- bằng chứng ngày đăng và các cờ cảnh báo khớp nguồn; không tự bỏ yêu cầu rà soát;
- mọi vị trí câu khớp chính xác lát cắt trong văn bản; không có ký tự thay thế Unicode.

Kết quả phần mềm: 154 kiểm thử đạt; Ruff lint/format đạt; `uv lock --check` đạt; demo offline đạt trên 9 tài liệu giả lập. HTTP tự động trong kiểm thử dùng MockTransport; lượt crawl thật là bằng chứng riêng. Môi trường Python 3.12.13, phụ thuộc khóa bằng `uv.lock`; mã băm code và catalog dùng UTF-8/LF để khớp Git, ghi ở [collection.json](../data/catalogs/hcmus-focused-100/collection.json).

Có 10 cờ ngữ cảnh tệp đính kèm và 11 cờ ô bảng gộp; các cờ có thể cùng nằm trên một tài liệu. Quét mẫu định danh ghi nhận 1 tài liệu còn chuỗi giống số điện thoại. Phát hiện này và kiểm tra tự động không xác nhận ẩn danh hoàn tất; tên không giới hạn, liên kết và thông tin cá nhân tự do vẫn cần con người rà soát.

## Một kết quả chính và phạm vi đưa vào Git

Chỉ giữ `data/raw/crawls/hcmus-focused-100-20261106/` làm kết quả thu thập hiện hành. Đã dọn 25 đường dẫn kết quả cũ/tệp thử nghiệm trong repository và 7 bản HTML không còn được chọn trong vùng raw; giữ snapshot từ chối của lượt hiện hành để truy vết. Ví dụ giả lập và báo cáo lịch sử về phần mềm được giữ riêng, không tính vào 100 mẫu.

Danh mục được chia sẻ ở [data/catalogs/hcmus-focused-100](../data/catalogs/hcmus-focused-100/README.md), gồm 100 URL nguồn, selector, mã băm và thông tin kiểm chứng. HTML, nhật ký riêng và các trang bị loại giữ cục bộ. Bản nội dung chuẩn bị được chia sẻ theo yêu cầu trực tiếp của người dùng; trạng thái rà soát của con người vẫn được giữ, không tự xác nhận đã hoàn tất. Công cụ dựng lại kiểm tra văn bản trùng mã băm và ghi ánh xạ ID khi HTML thay đổi; nguồn đã sửa nội dung sẽ gây lỗi thay vì âm thầm thay dữ liệu.

## Hạn chế cần báo cáo

Lấy theo thứ tự trang danh sách, không phải mẫu ngẫu nhiên; nguồn UEH thiên về học bổng. Bộ lọc từ khóa có thể bỏ sót cách diễn đạt khác; bộ này không đại diện toàn bộ thông báo học vụ. Không đọc PDF, ảnh hay tệp đính kèm; không tự xác minh đầy đủ tác vụ. Chưa có bằng chứng nhãn chuẩn, độ đồng thuận, chất lượng mô hình, ẩn danh hoàn tất hoặc nhóm chia tập đã được con người phê duyệt.


## Bản nội dung chia sẻ cho nhóm

Theo yêu cầu chia sẻ đầy đủ dữ liệu của người dùng, thư mục `data/catalogs/hcmus-focused-100/` có thêm `notices.jsonl`, `snapshot_index.jsonl` và `snapshot_summary.json`. Nhóm có sẵn toàn văn 100 thông báo sau khi clone, không bắt buộc crawl lại.

Bản `team-contact-redacted-v1` che thêm 128 lượt tên người liên hệ hoặc số điện thoại, giữ 40/30/30 tài liệu và tạo lại vị trí câu. Mã tài liệu vẫn truy về nguồn HTML; mã băm văn bản trước/sau che được ghi riêng để không dùng nhầm phiên bản gán nhãn. Bản chia sẻ vẫn giữ cờ chờ con người kiểm tra riêng tư, ngày đăng và nội dung. HTML gốc và trang bị loại không đưa lên Git.

Kiểm tra bản chia sẻ: 163 kiểm thử đạt; lint/format đạt; kiểm tra lại 100 mã tài liệu, tỷ lệ 40/30/30, mã băm văn bản và mọi vị trí câu. Quét lại không còn các mẫu tên liên hệ/số điện thoại được cấu hình; kết quả này không khẳng định đã loại mọi loại thông tin cá nhân.


## Rà lại cấu trúc và định dạng bản đã push

Đã đối chiếu nhánh GitHub `hcmus-web-crawler` tại commit `573c64d` và đọc dữ liệu trực tiếp từ Git. Toàn bộ 100 bản ghi khớp schema Notice, đúng 40/30/30, không trùng ID hay văn bản, và khớp nguồn, mã băm, vị trí câu. Mã băm lịch sử của code được đối chiếu với commit thu thập `6ea25fb`; metadata nguồn không bị nhầm là mã băm của code mới nhất.

Bổ sung schema TeamSnapshotIndex/TeamSnapshotSummary và lệnh `tools/check_notice_dataset.py --snapshot-dir data/catalogs/hcmus-focused-100` để kiểm tra bản chia sẻ độc lập với HTML cục bộ. Kiểm thử dùng bản sao chỉ gồm các tệp đã chia sẻ, đồng thời thử từ chối trường lạ, URL sai, thiếu bài, sửa văn bản, sai tổng kết/ngày đăng, mất phân đoạn và tự xóa cờ rà soát.

Kết quả sau bổ sung: 172 kiểm thử đạt, lint/format và demo offline đạt. Nội dung và các tệp dữ liệu đã push giữ nguyên so với `573c64d`. `validation.json` là kiểm chứng bộ crawl gốc; `snapshot_summary.json` là tổng kết bản che thêm thông tin liên hệ, tránh hiểu nhầm phát hiện điện thoại trong bản gốc là lỗi còn tồn tại trong bản chia sẻ.

Cấu trúc chia sẻ được giữ theo trách nhiệm: mã tái sử dụng trong src, lệnh chạy trong tools, kiểm thử trong tests, báo cáo trong reports, và bản dữ liệu có phiên bản trong data/catalogs. Bộ này hợp lệ cho bước rà soát/gán nhãn pilot; chưa có nhãn chuẩn, xác minh ngày đăng bởi con người hay nhóm chia train/test được duyệt.
