# Tổng hợp gom nhóm sự kiện SmartNotice

Tài liệu này ghi công việc gom nhóm sự kiện trên nhánh `gouping` và các lượt đo theo ngày. Dùng các mục dưới đây để đối chiếu dữ liệu, quyết định và số đo của từng lượt.

## Quy trình đã xây dựng

| Bước | Đầu ra và cách sử dụng |
|---|---|
| Chuẩn bị dự đoán | [Bộ chuyển đổi Label Studio](../src/labeling/studio.py) kiểm tra hash, offsets và quan hệ. Dự đoán giữ tác giả `model_prediction`, quyết định của trợ lý giữ `ai_assistant`. |
| Gợi ý cặp và dựng nhóm | [Quy trình gom nhóm](../docs/event-grouping.md) phân biệt cùng sự kiện, nhắc lại, cập nhật, khác sự kiện và chưa rõ. Giữ các đầu việc, phiên, điều kiện và giá trị cũ/mới trong từng nhóm. |
| Duyệt và áp dụng góp ý | [Trang duyệt và hợp đồng](../docs/interface.md#apply-local-group-review-notes) nối ghi chú với đúng fingerprint của bản đã xem. Đề xuất tách hoặc gộp cần phạm vi tường minh và bằng chứng nguồn. |
| Chia tập và đánh giá | [Quy trình đánh giá](../docs/evaluation.md#plan-group-k-fold-from-reviewed-events) giữ nguyên nhóm tài liệu khi lập Group K-fold. [Mục huấn luyện](../docs/evaluation.md#fit-and-test-a-grouping-baseline) hướng dẫn chạy hồi quy logistic và đánh giá trên cặp đã duyệt. |

Danh tính sự kiện và danh tính đầu việc là hai tầng. Thư đính chính chỉ thay trường có bằng chứng và giữ chiều từ bản mới về bản cũ. Cặp chưa rõ cần duyệt. Không lấy nhóm tài liệu dùng để chia tập làm nhãn sự kiện. Mã chia fold, công cụ huấn luyện, template và dữ liệu tổng hợp đi cùng mã nguồn. Corpus thực, HTML nhúng email, ghi chú duyệt, dự đoán, checkpoint và đầu ra chạy thử được lưu cục bộ. Các đường dẫn dưới `data/annotations/` và `reports/generated/` bên dưới cần gói dữ liệu tương ứng để mở.

## 05–15/11/2026 · Mẫu phát triển và quy trình duyệt

Các lượt trong bảng 1 chưa dùng Group K-fold. Chúng xác minh quy trình và ghi phạm vi của dữ liệu phát triển.

| Lượt | Kết quả ghi nhận | Bằng chứng cục bộ |
|---|---|---|
| 05/11 · Pilot và prototype | Pilot có 34 tài liệu, 33 lần nhắc và 20 cặp. Mẫu `hien.json` chọn 10 tài liệu bằng seed 42 và có 26 sự kiện, 97 span do trợ lý gán nhãn. Prototype xét 1.327.635 cặp của 1.630 lần nhắc từ 434 email. Chọn 364 ứng viên, đề xuất 10 cùng sự kiện, 7 khác sự kiện và 347 chưa rõ. Dựng 8 nhóm có nhiều lần nhắc và 1.613 nhóm đơn. | `data/annotations/event-grouping-pilot-2026-11-05/`, `reports/generated/event-grouping-prototype-2026-11-05/` |
| 06/11 · Rà soát nguồn và dựng nhóm | Sửa ACTION bị cắt, vai trò thời gian và phạm vi cập nhật. Bản đầy đủ có 170 sự kiện trên 34 tài liệu. Gắn 38 cờ riêng tư trên 17 tài liệu để con người kiểm tra. Dựng 33 lần nhắc từ 20 quyết định AI thành 19 nhóm và 23 đầu việc hoặc phiên. Áp dụng hai cập nhật thời hạn. | `data/annotations/event-grouping-review-2026-11-06/`, `reports/generated/event-grouping-assembly-verification/verification.json` |
| 09/11 · Áp dụng ghi chú | Nhập 10 ghi chú, gồm 8 đồng ý và 2 đề nghị tách. Tách các chuyên đề độc lập và các mục Festival khác sự kiện trong cùng thư. Dựng 35 lần nhắc và 22 quyết định cặp thành 22 nhóm, 25 đầu việc. Giữ hai cập nhật thời hạn. Ghi nhận thêm xác nhận 13 nhóm có đúng một email của người dùng. | `data/annotations/event-grouping-review-2026-11-06/user-reviewed-2026-11-09/`, `reports/generated/group-feedback-2026-11-09-verification/` |
| 09/11 · Đề xuất tự động | Với 35 lần nhắc, xét 595 cặp và đề xuất 65 cặp. Dựng 26 nhóm, 30 đầu việc và áp dụng một cập nhật thời gian. Bao phủ 19/22 cặp tham chiếu và có 11 cặp khớp mọi trường được so sánh. Bản tham chiếu đã tham gia phát triển. | `reports/generated/automatic-grouping-2026-11-09-final/` |
| 10/11 · Duyệt lần hai và chốt mẫu | Mua vé và nhận vé thuộc cùng sự kiện, giữ hai đầu việc. Festival giữ riêng. Bổ sung tên chiến dịch có trích dẫn. Người dùng chấp nhận bản 25 nhóm, 35 lần nhắc và 30 đầu việc ở cấp nhóm. Giữ ledger và fingerprint để truy đúng bản đã duyệt. | `reports/generated/group-review-2026-11-10-accepted/`, receipt trong `data/annotations/event-grouping-review-2026-11-06/accepted-2026-11-10/` |
| 15/11 · Mở rộng và bàn giao | Chạy batch 434 email với 1.630 lần nhắc, 1.327.635 cặp có thể xét và 10.787 đề xuất. Dựng 1.611 nhóm và 1.626 đầu việc. Hàng chờ có 74 nhóm ưu tiên và bốn tài liệu có dự đoán rỗng. Kiểm tra chín hành vi của giao diện bằng DOM mô phỏng. | `reports/generated/automatic-grouping-full-2026-11-15/`, `reports/generated/grouping-handoff-2026-11-15/` |

Các mốc đầu được ghi trong lịch sử `0e85f88` và `5fa00b3`. `4db50b6` hoàn thiện đề xuất và duyệt tự động, `0f1782a` bổ sung chạy cả batch và `78b3a93` ghi kết quả bàn giao. Phần tiền xử lý trước grouping đã được tích hợp vào `main` qua `704ad62`. Kết quả theo ngày là số đếm của các phạm vi khác nhau. Xác nhận của người dùng ở cấp nhóm không tạo nhãn cặp độc lập hay clearance riêng tư.

## 16/11/2026 · Kiểm tra v3.3 và khóa 5 fold

Bộ v3.3 có 684 tài liệu, 505 nhóm tài liệu và 88 nhóm nhiều tài liệu chờ duyệt. Khớp 25 checksum. Chưa có tài liệu `gold_ready` trong 188 tài liệu ở hai tập kiểm tra ban đầu. Schema hiện tại từ chối 456/496 annotation train và validation do `audience_constraints` mới, gồm 367 ở train và 89 ở validation. Khi bỏ riêng phần điều kiện trong bộ nhớ để kiểm tra, 5.766 span và 1.873 event vẫn nối được với nguồn. Lượt này không xuất annotation rút gọn.

Tệp ghi chú lượt 3 khớp 30 tài liệu của assembly phát triển và có 26 nhóm `looks_ok`, gồm chín nhóm nối nhiều email. Hai cụm liên kết đã duyệt vượt ranh giới train/test. Bản chia thử giữ nguyên snapshot v3.3, loại hai tài liệu train trong các cụm này khỏi kiểm định và cho 401 tài liệu trên 5 fold, mỗi fold 80–81 tài liệu. Seed là 42. Hàng chờ còn bốn đề xuất qua split gốc và một đề xuất qua hai fold.

Rà lại năm đề xuất ưu tiên cho kết quả ba cùng sự kiện, một khác sự kiện và một `UNCLEAR`. Hai đề xuất cùng cặp email ghi hai mốc riêng của một chiến dịch. Hai thư hội nghị thuộc cùng sự kiện và giữ riêng việc đổi phòng và nghỉ lớp. Chuyển cặp kế hoạch năm học chưa rõ vào validation để kiểm soát rò rỉ. Kiểm tra thêm tám cặp âm ở train.

| Bản chia | Train | Validation | Test | Domain test | Excluded |
|---|---:|---:|---:|---:|---:|
| v3.3 gốc | 403 | 93 | 126 | 62 | 0 |
| Bản grouping khóa fold | 400 | 94 | 120 | 62 | 8 |

Bản khóa có 80 tài liệu trong mỗi fold. Sáu tài liệu test đã xuất hiện trong lượt phát triển hoặc rà soát và hai tài liệu train liên quan được đưa vào excluded. Không có liên kết nào trong 25 ràng buộc giữ nhóm vượt split hoặc fold. Tập cặp ban đầu gồm 7 `SAME_EVENT`, 1 `UPDATE_OF` và 8 `DIFFERENT_EVENT`. Đầu ra khóa fold và nhãn nằm tại `data/annotations/grouping-training-v3_3-2026-11-16/`. Bản chia thử và audit nằm tại `reports/generated/group-cv-2026-11-16/` và `reports/generated/group-cv-2026-11-16-validation/`. Các mốc kiểm thử trong hai lượt là 361 và 362 ca đạt. Commit công cụ chia và đóng băng là `1b2a3ac`.

## 16/11/2026 · Hồi quy logistic và bản bổ sung dấu hiệu nhận diện

Bản đầu fit hồi quy logistic L2 trên 16 cặp, với `C=1.0`, `lbfgs`, ngưỡng 0,5 và seed 42. Mỗi lượt Group K-fold chuẩn hóa đặc trưng trong phần fit rồi chấm cặp có cả hai đầu trong fold đánh giá. Chấm được 14 cặp. Tập kiểm tra email có 23 cặp do trợ lý đọc, gồm 22 cặp chấm được và một cặp `UNCLEAR`.

Rà soát 10 lỗi gộp nhầm và một cặp bị bỏ sót cho thấy các thư dùng chung mẫu câu dù khác sự kiện. Thư yêu cầu và thư trả lời có thể khác cách diễn đạt. Bản v2 bổ sung tám đặc trưng từ câu lân cận, như học kỳ, ngày đầy đủ và biểu mẫu chung. Khi thiếu căn cứ, v2 có thể chuyển cặp sang duyệt. Bổ sung 11 cặp có nhãn, nâng tập fit lên 27 cặp, gồm 10 `SAME_EVENT`, 1 `UPDATE_OF` và 16 `DIFFERENT_EVENT`. Các fold được giữ nguyên.

| Mẫu chấm | Cặp chấm, dương / âm | Macro-F1 v1 | Macro-F1 v2 | Kết quả gộp v1 → v2 |
|---|---:|---:|---:|---|
| Group K-fold trên 16 cặp gốc | 14, 8 / 6 | 0,785 | — | V1 gộp đúng 6/8 và gộp nhầm 1/6 |
| Group K-fold trên 27 cặp mở rộng | 25, 11 / 14 | — | 0,826 | V2 gộp đúng 7/11 và gộp nhầm 0/14 |
| Email giữ lại ban đầu, dùng rà lỗi v2 | 22, 2 / 20 | 0,400 | 0,821 | Gộp đúng 1/2 ở cả hai bản. Gộp nhầm giảm 10 → 0. |
| Mẫu test bổ sung | 13, 0 / 13 | — | — | Gộp nhầm giảm 10 → 0. Không có cặp dương. |
| Mẫu validation riêng | 9, 3 / 6 | 0,325 | 0,679 | Gộp đúng giảm 2/3 → 1/3. Gộp nhầm giảm 5 → 0. |

Macro-F1 trung bình F1 của hai lớp. Hai dòng kiểm định chéo dùng mẫu khác nhau. So khớp từ đạt 0,844 trên 14 cặp kiểm định, 0,575 trên 22 cặp test ban đầu và 0,718 trên 25 cặp kiểm định của bản mở rộng. V2 chuyển duyệt thư đính chính lịch và dự đoán tách thư nhắc về giải thưởng, dẫn đến hai ca bỏ sót trên validation. Bộ v1 nằm tại `reports/generated/grouping-logistic-2026-11-16/`, cùng mã runner tại commit `4108d83`. Bộ mở rộng và số đo v2 nằm tại `data/annotations/grouping-training-evidence-2026-11-16/`, `reports/generated/grouping-evidence-model-2026-11-16/` và `reports/generated/grouping-revision-2026-11-16/`. Các lượt dùng Python 3.12.13, scikit-learn 1.9.1 trên Windows. Mốc kiểm thử là 364 ca với v1 và 367 ca với v2.

## 17/11/2026 · Truy tên, tham chiếu và thư bổ sung gần giờ

Giữ checkpoint v2 rồi chạy ba phương án trên cùng cặp. Truy tên lấy tên sự kiện từ phần nguồn liên quan. Truy tham chiếu kiểm tra liên kết với thư trước và dấu hiệu cập nhật. Giờ gửi có múi giờ và người gửi được đối chiếu cục bộ từ email gốc đã kiểm tra hash. Cùng người gửi trong 15 phút là tín hiệu tìm ứng viên, cần thêm nội dung về phần bổ sung để đề xuất gộp.

| Mẫu | Cặp dương / âm | V2 | Thêm tên | Thêm tham chiếu | Kết hợp |
|---|---:|---:|---:|---:|---:|
| Validation cũ đã dùng rà lỗi | 3 / 6 | 1 / 0 | 2 / 0 | 2 / 0 | 3 / 0 |
| Mẫu thử thách thuộc phân vùng train, không dùng để fit | 5 / 3 | 1 / 0 | 1 / 0 | 2 / 1 | 2 / 1 |
| Validation và test mới | 0 / 10 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

Mỗi ô phương án ghi số cặp gộp đúng rồi đến số gộp nhầm. Bản kết hợp nhận ra thư nhắc giải thưởng, thư đính chính lịch và thư gửi lại tệp lịch thi sau 186 giây. Hai cặp khác gửi cách nhau 1 và 177 giây được giữ riêng. Còn một lỗi gộp thư đăng ký giáo dục quốc phòng với thư đăng ký học phần chung dù khác đầu việc. Nhánh kết hợp phù hợp để ưu tiên cặp cần duyệt. Các mẫu mới có chủ đích và dùng nhãn đối chiếu của trợ lý, chưa đủ để quyết định dùng làm bản chính.

Nhãn, offsets, tham số, dự đoán và hash của năm lượt đo nằm tại `reports/generated/grouping-followup-2026-11-17/`. Chạy lại mẫu thử thách tạo hai tệp giống từng byte. Bộ kiểm thử có 370 ca đạt. Ruff, demo tổng hợp và đối chiếu nhóm tài liệu đạt.

## 17/11/2026 · Tách thông báo cùng mẫu theo học kỳ và đợt

Bổ sung quy tắc phạm vi học kỳ trên cùng checkpoint v2 để đo riêng tác dụng của thay đổi. Đọc tiêu đề đã xác minh và câu liên quan của email, chuẩn hóa cách ghi như `HK2/2526`, `học kỳ II năm học 2025–2026` và mã lớp nhúng học kỳ. Hai lịch thi có học kỳ, năm học, mã môn hoặc giai đoạn thi xung đột rõ được giữ riêng. Chỉ khác ngày trong cùng vai trò thì có thể chuyển duyệt. Giờ gửi xác định thứ tự thư. Khi thư sau tham chiếu trực tiếp và nói rõ thay đổi, hai mốc có cùng vai trò hỗ trợ gắn quan hệ cập nhật.

Chạy lại 64 cặp đã rà soát. Sau khi bỏ hai cặp có nhãn tham chiếu `UNCLEAR`, cả hai phương án tìm đúng 6/10 cặp cùng sự kiện, gộp nhầm 1/52 cặp khác sự kiện và bỏ sót 4/10 cặp đúng. Kết quả trên mẫu đã rà soát không đổi. Trên batch 434 email, công cụ chấm 10.787 cặp ứng viên đã lưu từ 430 email có lần nhắc. Quy tắc mới đổi 54 cặp từ `UNCLEAR` sang `DIFFERENT_EVENT` và một cặp từ `SAME_EVENT` sang `UNCLEAR`. Đây là thay đổi dự đoán trên batch chưa có nhãn cặp tham chiếu.

Bộ gán nhãn cục bộ `reports/generated/grouping-academic-2026-11-17/grouping-human-review-2026-11-17.json` có 30 cặp chính và một cặp kiểm tra riêng quy tắc học kỳ. Mẫu chính loại các nhóm đã dùng để fit hoặc rà soát. Có 25 cặp từ các nhóm chưa dùng trong phân vùng train và 5 cặp từ validation. Test chỉ còn một email đủ điều kiện sau khi loại các nhóm đã xem, nên chưa thể tạo cặp test mới trong phạm vi này. Mẫu chính có 9 cặp có tham chiếu hoặc gửi gần giờ, 10 cặp giống mẫu và 11 cặp nền chọn bằng seed 691. Kết quả phải báo theo phạm vi lấy mẫu. Cặp kiểm tra riêng được chọn vì quy tắc đổi quyết định và chấm riêng.

Tệp gửi người duyệt lưu trích đoạn đã che, ngày gửi, chênh lệch giờ gửi, cờ cùng người gửi và tham chiếu. Nhãn để trống. Dự đoán được cố định trong ledger riêng để so sánh sau khi nhận nhãn người. `run.json` của các phép đo và batch nằm trong `reports/generated/grouping-academic-2026-11-17/`. Quy trình chạy lại và phạm vi đo nằm trong [hướng dẫn đánh giá](../docs/evaluation.md#fit-and-test-a-grouping-baseline).

Kiểm tra 373 ca đạt. Ruff và demo offline đạt. Kiểm tra trùng ID, nhãn để trống và hash giữa tệp duyệt với ledger dự đoán đều đạt.

## 17/11/2026 · Đối chiếu dự đoán với nhãn người dùng

Tệp người dùng gửi lại khớp đủ 31 mã cặp và toàn bộ trường bằng chứng của biểu mẫu. Mẫu chính có 30 cặp do một người gán nhãn, gồm 5 `SAME_EVENT`, 2 `UPDATE_OF` có chiều hợp lệ, 20 `DIFFERENT_EVENT` và 3 `UNCLEAR`. `HS-01`, cặp kiểm tra riêng quy tắc học kỳ, đang để trống. Mẫu chính chọn trước bằng seed 691 và dự đoán đã khóa trước khi nhận nhãn. Cả 25 cặp thuộc phân vùng train đều từ nhóm chưa dùng để fit hoặc rà soát. Năm cặp validation đều có nhãn khác sự kiện. Mẫu chính không có cặp từ phân vùng test. Nhãn lần này chỉ dùng để chấm.

Khi chấm quyết định gộp, `SAME_EVENT` và `UPDATE_OF` thuộc lớp cần gộp. Ba cặp có nhãn người `UNCLEAR` được báo riêng. Dự đoán `UNCLEAR` giữ cặp ở hàng chờ duyệt và được tính là chưa gộp. Bảng dưới cho thấy quy tắc học kỳ cho kết quả giống bản kết hợp truy tên và tham chiếu trên toàn bộ 30 cặp chính.

| Phương án | Gộp đúng | Gộp nhầm | Bỏ sót | Recall gộp | F1 gộp | Macro-F1 nhị phân | Khớp nhãn gốc |
|---|---:|---:|---:|---:|---:|---:|---:|
| V2 kết hợp truy tên và tham chiếu | 1/7 | 0/20 | 6/7 | 14,3% | 0,250 | 0,560 | 18/30 |
| V2 kết hợp, thêm quy tắc học kỳ | 1/7 | 0/20 | 6/7 | 14,3% | 0,250 | 0,560 | 18/30 |

Cả hai phương án đều gộp một cặp. Precision gộp vì vậy chỉ dựa trên một dự đoán. Độ chính xác của quyết định gộp là 21/27. Trong sáu cặp cần gộp bị bỏ sót, bốn cặp bị tách và hai cặp được chuyển duyệt. Cả năm cặp cần gộp thuộc mẫu có tham chiếu hoặc gửi gần giờ đều bị bỏ sót. Mô hình tìm được một trong hai cặp cần gộp ở mẫu giống mẫu câu. Mẫu nền gồm 11 cặp khác sự kiện. Mô hình bỏ sót cả hai nhãn `UPDATE_OF`, trong đó một cặp được gộp với nhãn `SAME_EVENT`. Cả ba cặp có nhãn người `UNCLEAR` đều bị tách.

Ưu tiên kiểm tra xem thư trả lời đang nói đến đúng đối tượng, đầu việc và phạm vi nào của thư trước. Ví dụ trong mẫu có thư xác nhận lịch sau khi thông báo lịch dự kiến và thư xác nhận hệ thống hoạt động trở lại sau sự cố. Các cặp này cần xử lý được cả hai trường hợp giữ `SAME_EVENT` và dùng `UPDATE_OF` theo trường thay đổi. Lượt cải thiện nên xét cả liên kết đăng ký và trạng thái, ghi bằng chứng cùng chiều mới về cũ, và chuyển duyệt khi thư trước có nhiều mục mà thư sau chưa chỉ rõ mục liên quan. Tham chiếu trực tiếp hoặc gửi gần giờ chỉ tạo ứng viên. Giữ kiểm tra xung đột học kỳ và đo riêng trên các cặp được quy tắc đổi quyết định sau khi có nhãn người. Dùng các nhóm tài liệu mới có nhãn để đo lại khả năng tìm cặp cần gộp, gộp nhầm và nhận diện cập nhật. Kết quả hiện tại phù hợp với việc hỗ trợ duyệt thủ công.

Số đo, checksum của biểu mẫu, nhãn người, dự đoán và công cụ chấm nằm trong `reports/generated/grouping-academic-2026-11-17/human-evaluation/metrics.json`. Tệp `comparison.jsonl` cùng thư mục ghi kết quả theo mã cặp. `human_review_run.json` ở thư mục cha ghi bản chia, seed lấy mẫu và hash của checkpoint. Chạy lại `score_human_review.py` trên cùng tệp bằng Python của môi trường `uv` cho hai đầu ra giống từng byte.

## 17/11/2026 · Đối chiếu để chọn bản grouping chính

Chạy lại bản V2 kết hợp truy tên và tham chiếu cùng bản thêm quy tắc học kỳ trên checkpoint `grouping-logistic-v2` đã lưu. Giữ nguyên ngưỡng, split và các cặp đầu vào. Lần chạy lặp tạo dự đoán giống từng byte với các lượt đã ghi. Trên 30 cặp chính được người dùng gán nhãn và 64 cặp do trợ lý rà soát, không có cặp nào đổi quyết định. Hai nguồn nhãn được đọc riêng trong bảng dưới.

| Mẫu đối chiếu | Cặp chấm được | Gộp đúng, trước → sau | Gộp nhầm, trước → sau | F1 lớp gộp, trước → sau |
|---|---:|---:|---:|---:|
| Người dùng | 27 | 1/7 → 1/7 | 0/20 → 0/20 | 0,250 → 0,250 |
| Trợ lý rà soát | 62 | 6/10 → 6/10 | 1/52 → 1/52 | 0,706 → 0,706 |

Trong 10.787 cặp ứng viên ở batch 434 email, bản mới đổi 55 dự đoán thuộc 14 cặp email. Quy tắc đổi 42 cặp có học kỳ xung đột và 12 cặp có năm học xung đột từ `UNCLEAR` sang `DIFFERENT_EVENT`. Một cặp có phạm vi học kỳ mơ hồ đổi từ `SAME_EVENT` sang `UNCLEAR`. Số cặp ứng viên chờ duyệt giảm từ 675 xuống 622. Các trường hợp đổi quyết định chưa có nhãn đối chiếu, bao gồm `HS-01`, nên chưa đo được bao nhiêu quyết định mới là đúng.

Bản thêm quy tắc học kỳ phù hợp để thử trong luồng có người duyệt. Cả hai bản bỏ sót 6/7 cặp cần gộp trong mẫu người dùng và chưa nhận diện đúng nhãn `UPDATE_OF` ở hai cặp cập nhật. Lượt so sánh này đánh giá quyết định trên ứng viên đã có. Công cụ dựng nhóm tự động vẫn gọi bộ quy tắc riêng, nên chưa đo được tác động của bản mới lên nhóm sự kiện cuối cùng. Để xem xét chọn bản chính, duyệt các ca đổi theo học kỳ, đo thư tiếp nối và cặp dễ gộp nhầm trên nhóm tài liệu mới có nhãn người, rồi kiểm tra kết quả ở cấp nhóm sau khi tích hợp.

Các lượt lặp nằm trong `reports/generated/grouping-academic-2026-11-17/release-comparison-batch/`, `release-comparison-human/` và `release-comparison-assistant/` cùng thư mục cha. Kiểm tra phần mềm riêng đạt 60 ca cho grouping, bộ dựng nhóm tự động và email.

## 18/11/2026 · Mở rộng tập huấn luyện và đo luồng dựng nhóm

Trợ lý đối chiếu 70 cặp với nguồn đã chuẩn bị. Lượt chọn đầu dùng seed 42 để lấy thư có dấu hiệu gia hạn, nhắc lại hoặc tiếp nối, cùng các cặp dùng lại mẫu câu. Lượt tìm bổ sung xếp hạng bằng tiêu đề, liên kết và tham chiếu thư đã xác minh. Các lượt chọn không dùng điểm mô hình. Trong 60 cặp dành cho huấn luyện, có 12 `SAME_EVENT` (gồm bảy ca nhắc lại và bốn ca tiếp nối), bốn `UPDATE_OF`, 38 `DIFFERENT_EVENT` và sáu `UNCLEAR`. Loại sáu cặp chưa rõ và hai cặp đã có trong tập cũ. Tập fit tăng từ 27 lên 79 cặp trên 95 tài liệu, gồm 20 `SAME_EVENT`, năm `UPDATE_OF` và 54 `DIFFERENT_EVENT`. Mỗi nhãn mới lưu bằng chứng hai phía, quyết định do trợ lý, và chiều cập nhật khi có.

Giữ split gốc, khóa lại năm fold với seed 42 và giữ chung fold cho hai đầu của từng cặp dương. Mẫu người dùng 17/11 và mười cặp chẩn đoán mới có nhóm tài liệu tách khỏi tập fit. Test chỉ có một email đủ điều kiện trong lượt chọn nên không tạo được cặp test mới. Fit hồi quy logistic V2 với L2, `C=1.0`, `lbfgs`, ngưỡng 0,5, Python 3.12.13 và scikit-learn 1.9.1 trên Windows. Kiểm định chéo chấm được 46 cặp có hai đầu trong cùng fold đánh giá. Mô hình gộp đúng 14/25 cặp dương, gộp nhầm 0/21 cặp âm, đạt F1 lớp gộp 0,718. Tổng cộng 33 cặp có hai đầu khác fold nên không có dự đoán kiểm định chéo.

Trên cùng mẫu 30 cặp người dùng chấm ngày 17/11, cả mốc cũ và bản huấn luyện lại có 21/27 quyết định gộp hoặc không gộp đúng, tìm đúng 1/7 cặp cần gộp và gộp nhầm 0/20 cặp khác sự kiện. Số nhãn khớp chính xác giảm từ 18/30 xuống 17/30. Cả hai bỏ sót hai nhãn `UPDATE_OF`, kể cả một cặp được gộp với nhãn `SAME_EVENT`. Trên mẫu chẩn đoán của trợ lý, bản mới xác định đúng việc cần gộp đối với một cặp gia hạn thuộc phân vùng train được giữ riêng, nhưng cũng trả `SAME_EVENT`. Giữ riêng đúng tám cặp âm trong hai phân vùng. Một cặp validation có nhãn tham chiếu `UNCLEAR` được báo riêng.

Chạy hai luồng dựng nhóm trên cùng 60 email và 237 lần nhắc của mẫu người dùng. `--checkpoint` bổ sung ứng viên từ thư trả lời hoặc gửi gần giờ và kiểm tra thêm bằng chứng nhận diện. Hạn cũ và mới phải truy được về các span nguồn cùng đầu việc để ghi một gia hạn.

| Chỉ số trên các cặp đã duyệt | Quy tắc cũ | Quy tắc kèm checkpoint mới |
|---|---:|---:|
| Cặp cần gộp có trong danh sách ứng viên | 3/7 | 7/7 |
| Cặp cần gộp vào cùng nhóm cuối | 0/7 | 1/7 |
| Cặp khác sự kiện vào cùng nhóm cuối | 0/20 | 0/20 |
| Cập nhật đúng chiều được áp dụng | 0/2 | 0/2 |

Cả sáu cặp còn bỏ sót đã có trong danh sách ứng viên và dừng ở bước xác định danh tính sự kiện. Năm cặp có tham chiếu trả lời trực tiếp đã được xác minh. Lượt kế tiếp cần xác định thư trả lời đang bổ sung hoặc sửa mục nào của thư trước và đưa đúng mốc hạn vào annotation. Giữ ca thiếu mốc hoặc có nhiều mục chưa phân giải trong hàng chờ duyệt. Bản thử nghiệm đã chạy trên 434 email, tạo 11.836 đề xuất, 25 nhóm nhiều lần nhắc và chưa áp dụng cập nhật nào. Batch này chưa có nhãn đối chiếu cho toàn bộ đầu ra.

Tập dữ liệu và checksum nằm tại `data/annotations/grouping-training-followup-2026-11-18/`. Thư mục `reports/generated/grouping-expansion-2026-11-18/` giữ cách chọn, nhãn, checkpoint, dự đoán và số đo. Xem `human-benchmark/metrics.json` cho bộ chấm cặp, `final/assembly-metrics.json` cho kết quả dựng nhóm và `final/full-batch/run.json` cho lượt chạy toàn batch. Chạy lại huấn luyện cho checkpoint và dự đoán kiểm định chéo giống từng byte. 384 kiểm thử, Ruff và demo tổng hợp đạt. Các tệp nguồn và trang duyệt có nội dung corpus cần được giữ trong workspace riêng.

## 18/11/2026 · Khôi phục nhãn ở cặp dùng chung mẫu bảo hiểm

Đối chiếu dự đoán trước và sau khi fit trên 79 cặp cho thấy hai nhãn thay đổi trên mẫu 30 cặp người dùng. Cặp `HE-12` có nhãn tham chiếu `DIFFERENT_EVENT`. Điểm của cặp tăng từ 0,1746 lên 0,2621, vượt ngưỡng 0,25 của nhánh phân biệt `DIFFERENT_EVENT` và `UNCLEAR` khi thiếu dấu hiệu nhận diện. Ngữ cảnh cục bộ của hai lần nhắc có cùng tập từ và cụm từ, còn phần mở đầu xác nhận hai thao tác riêng là mua và gia hạn bảo hiểm y tế. Cặp `HE-11` đổi từ `UNCLEAR` sang `DIFFERENT_EVENT`. Cả hai đều lệch nhãn `SAME_EVENT` của người dùng. Vì hai cặp đều không được tự động gộp, độ chính xác nhị phân giữ ở 21/27.

Bản sửa giữ checkpoint 79 cặp và các ngưỡng. Khi bằng chứng quanh đầu việc nói về bảo hiểm và phần mở đầu mỗi thư xác nhận một thao tác đã hoàn tất, bộ kiểm tra ghi nhận mua và gia hạn là hai sự kiện riêng. Thư trả lời trực tiếp giữa hai thao tác chuyển sang duyệt. Hướng dẫn chung, thao tác chưa thực hiện và nội dung đề cập cả hai thao tác không cung cấp quyết định cho kiểm tra này. Luồng dựng nhóm đính kèm câu nguồn xác nhận thao tác với offset gốc.

Chạy lại 30 cặp với đúng điểm mô hình đã lưu. `HE-12` là nhãn duy nhất thay đổi sau khi thêm kiểm tra, từ `UNCLEAR` về `DIFFERENT_EVENT`. Số nhãn khớp tăng từ 17/30 trở lại 18/30. Quyết định nhị phân vẫn đúng 21/27, nhận ra 1/7 cặp cần gộp và nhận diện đúng 0/2 nhãn cập nhật. Luồng dựng nhóm giữ nguyên thành viên của các nhóm trên mẫu 60 email và batch 434 email. Trên batch, 15 cặp lần nhắc chuyển từ `UNCLEAR` sang `DIFFERENT_EVENT`. Batch chưa có nhãn đối chiếu đầy đủ.

Bảy cặp đối chứng do trợ lý đã gán nhãn trước đó nằm ngoài nhóm fit và nhóm của mẫu người dùng. Chúng giữ nguyên dự đoán sau bản sửa, với 2/7 nhãn khớp. Rà 434 email để tìm cặp đối chứng mới chỉ còn một thư bảo hiểm đủ điều kiện, nên chưa có cặp độc lập cùng phân vùng để đo quy tắc riêng. Phép đo trên 30 cặp kiểm tra hồi quy của ca đã phân tích. Lượt tiếp theo cần đối chiếu thư trả lời với đúng mục và đầu việc của thư trước, rồi xác định trường thay đổi. Cặp có tham chiếu nhưng khác mục cần được lấy làm ca đối chứng.

Đường dẫn `reports/generated/grouping-scope-regression-2026-11-18/` giữ `replay-delta.json`, `final/assembly-delta.json` và hồ sơ lấy mẫu đối chứng `insurance-review/`. Năm ca tổng hợp mới kiểm tra phạm vi của quy tắc. Bộ kiểm thử đạt 389 ca, cùng Ruff, demo offline và lượt chạy trên toàn batch.

## 18/11/2026 · Kiểm chứng việc nối thư tiếp theo mục nguồn

Commit `392360c` lưu mã, kiểm thử tổng hợp và báo cáo của mốc trước. Lượt này so sánh cùng checkpoint V2 fit trên 79 cặp và cùng bộ annotation của từng mẫu. Giữ ngưỡng 0,5. Chạy `tools/run_automatic_grouping.py` có và không có `--align-followup`. Bản bật tùy chọn đối chiếu các ACTION của cả hai thư. Một cặp cần có bằng chứng nội dung phù hợp và xác định được duy nhất giữa các mục cạnh tranh. Tín hiệu gồm mã sự kiện, phạm vi kỳ thi đủ cụ thể, cụm từ trong bằng chứng hoặc biểu mẫu đi kèm nội dung phù hợp. Liên kết nguồn bổ sung căn cứ về sự kiện. Quan hệ đầu việc và cập nhật vẫn qua kiểm tra riêng.

Gói đối chứng gồm 74 cặp đã được trợ lý gán nhãn trong các lượt trước, nằm ngoài các nhóm đã dùng để fit checkpoint và ngoài mẫu người dùng. Chạy riêng 14 cặp thuộc train, 21 cặp validation và 39 cặp test. Nhóm tài liệu và chuỗi trả lời đã biết được giữ nguyên. Sau khi loại các nhóm từng sử dụng, không còn cặp trả lời trực tiếp mới đủ điều kiện. Trợ lý duyệt thêm tám cặp chọn theo tiêu đề hoặc mẫu câu ở phần train giữ riêng. Trong đó có ba cặp khác sự kiện và năm cặp chưa rõ. Việc chọn và ghi nhãn diễn ra trước khi xem dự đoán của A.

| Mẫu đối chiếu | Cặp cần gộp vào cùng nhóm, mốc → A | Cặp khác sự kiện gộp nhầm, mốc → A |
|---|---:|---:|
| 30 cặp người dùng đã chấm | 1/7 → 1/7 | 0/20 → 0/20 |
| 74 cặp trợ lý đã duyệt trước | 2/10 → 3/10 | 0/59 → 0/59 |
| 13 cặp trả lời trực tiếp trong 74 cặp trên | 2/9 → 3/9 | 0/3 → 0/3 |
| 8 cặp mới dùng mẫu hoặc tiêu đề tương tự | Không có cặp dương | 0/3 → 0/3 |

Ca gộp đúng thêm đến từ phần train giữ riêng và có cụm từ chung trong bằng chứng của hai ACTION. Các cặp validation và test đã duyệt trước giữ nguyên kết quả. Trên mẫu người dùng, ba cặp dương tiếp tục chờ duyệt do không xác định được mục nguồn duy nhất, ba cặp còn lại thiếu căn cứ nhận diện. Cả hai lượt có 21/27 quyết định gộp hoặc giữ riêng đúng và 0/2 cập nhật đúng chiều. Mẫu mới chỉ đo được gộp nhầm. Chưa có đánh giá độc lập về khả năng tìm thêm cặp dương trong các chuỗi thư mới.

Trên batch 434 email, A chuyển 12 đề xuất từ `SAME_EVENT` sang `UNCLEAR` và sáu đề xuất theo chiều ngược lại. Các cặp kiểm tra tính nhất quán trong thành phần liên thông cũng thay đổi. Số nhóm chứa nhiều lần nhắc tăng từ 25 lên 32, số xung đột giảm từ 85 xuống 81. Batch thiếu nhãn đối chiếu cho các thay đổi này nên số đếm chỉ mô tả hành vi. A phù hợp để giữ ở chế độ thử nghiệm. Sáu ca người dùng còn bỏ sót cần đối chiếu nội dung diễn đạt khác nhau và hiểu đối tượng được nhắc tới, đặc biệt các thư trả lời ngắn.

Lưu cách chọn dữ liệu, mốc và số đo tại `reports/generated/grouping-alignment-2026-11-18/`. `comparison-summary.json` tổng hợp số đo và checksum. Các thư mục `results/` lưu hai lần chạy theo từng mẫu. `full-batch/` giữ hai trang duyệt cục bộ. 400 kiểm thử trong workspace, Ruff, demo tổng hợp và kiểm tra diff đạt.

## 19/11/2026 · Chọn mục nguồn và xác minh cập nhật

Chuẩn bị 82 cặp email thực trên 41 tài liệu với 12 nhãn đúng mục, 17 nhãn sai mục và 53 ca chưa rõ. Mười ba nhãn sai mục mới đến từ đối chiếu nguồn ở các chuỗi đã xem. Ghi nhãn mục nguồn riêng với nhãn sự kiện, vì hai mục khác nhau có thể thuộc cùng một sự kiện. Tài liệu, nhóm chia tập và các chuỗi trả lời đã biết được cách ly giữa train, validation và test. Giữ mẫu 30 cặp người dùng đã xem làm kiểm tra hồi quy. Kho hiện có chưa cung cấp chuỗi trả lời mới đủ điều kiện kiểm chứng độc lập. Chuẩn bị thêm 42 cặp tổng hợp trên 42 tài liệu, giữ riêng từng phân vùng. Tất cả 124 cặp được kiểm tra offset, mã sự kiện, nguồn và chiều thư trả lời.

D dùng 11 đặc trưng về ACTION, đoạn bằng chứng, từ và cụm ký tự, dấu hiệu khái niệm và phạm vi nguồn. Fit hồi quy logistic L2 có cân bằng lớp trên 19 cặp train có đích rõ, gồm tám đúng mục và mười một sai mục. D yêu cầu bằng chứng nội dung, điểm tối thiểu 0,60 và biên 0,10 so với mục kế tiếp. Giữ seed 42 và không đổi tham số sau khi chấm. Lượt fit lại tạo checkpoint giống từng byte. B kiểm tra trích dẫn cũ và mới của hạn hoặc trạng thái sau khi xác nhận được mục nguồn duy nhất. Luồng dựng nhóm vẫn kiểm tra mâu thuẫn trước khi áp dụng.

| Mẫu và chỉ số | A | A + D | A + D + B |
|---|---:|---:|---:|
| Train email thực, chọn đúng mục | 3/8 | 5/8 | 5/8 |
| Validation email thực, chọn đúng mục | 2/2 | 2/2 | 2/2 |
| Test email thực, chọn đúng mục | 1/2 | 1/2 | 1/2 |
| Mẫu người dùng, gộp đúng cặp cần gộp | 1/7 | 1/7 | 1/7 |
| Test tổng hợp, áp dụng đúng trường và chiều cập nhật | 0/3 | 0/3 | 1/3 |

Trên validation và test email thực, ba phương án cùng chọn nhầm hai trong sáu mục sai đã biết. Đây là lỗi xác định mục, có thể xảy ra khi hai đầu việc cùng sự kiện. Mẫu người dùng giữ 21/27 quyết định gộp hoặc giữ riêng đúng và 0/2 cập nhật đúng chiều. D đưa một cặp có nhãn người `UNCLEAR` vào cùng nhóm. Báo riêng trường hợp này vì nhãn chưa rõ nằm ngoài mẫu số nhị phân. Cải thiện của D trên các cặp dùng để fit chưa xuất hiện ở hai tập đánh giá.

B đề xuất đúng trường và đúng chiều cho cả ba ca cập nhật ở test tổng hợp. Bộ dựng nhóm áp dụng ca khôi phục `STATUS` và giữ lại hai ca `DEADLINE` do thành phần sự kiện có quyết định mâu thuẫn. Kiểm thử tích hợp tách riêng xác nhận hạn mới thay thế đúng hạn cũ khi nhóm nhất quán. B chưa áp dụng được ca cập nhật nào trong các mẫu email thực có nhãn. Trên batch 434 email chưa có đối chiếu đầy đủ, A, A + D và A + D + B dựng lần lượt 32, 49 và 49 nhóm nhiều lần nhắc. Không có cập nhật được áp dụng. Các số đếm batch mô tả hành vi của hệ thống. D và B được giữ dưới tùy chọn thử nghiệm để chờ phép đo trên chuỗi thư mới.

Lưu dữ liệu, checksum, checkpoint và phép đo tại `reports/generated/grouping-cdb-2026-11-19/`. `data/source-audit.json` ghi kiểm tra nguồn. `comparison-summary.json` tổng hợp 18 lượt chạy. Các kiểm thử phần mềm, Ruff và demo offline đạt.

## Ghi lần chạy tiếp theo

Thêm mục có ngày, mục tiêu lỗi cần xử lý, phiên bản dữ liệu và checksum của run. Ghi số tài liệu hoặc cặp, nguồn gốc nhãn, split, seed, tham số, số gộp đúng, gộp nhầm và bỏ sót theo từng mẫu. Giữ kết quả kiểm thử phần mềm riêng với số đo chất lượng. Dùng lệnh trong [quy trình đánh giá](../docs/evaluation.md) để tái tạo, và dẫn đến đường dẫn cục bộ của bằng chứng thay vì tạo thêm một báo cáo validation grouping.
