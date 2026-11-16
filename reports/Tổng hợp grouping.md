# Tổng hợp gom nhóm sự kiện SmartNotice

Tài liệu này ghi công việc gom nhóm sự kiện trên nhánh `gouping` và kết quả đến ngày 17/11/2026. Dùng các mục có ngày bên dưới để đối chiếu dữ liệu, quyết định và số đo của từng lượt. Thêm kết quả mới thành mục có ngày trong chính tài liệu này.

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

## Ghi lần chạy tiếp theo

Thêm mục có ngày, mục tiêu lỗi cần xử lý, phiên bản dữ liệu và checksum của run. Ghi số tài liệu hoặc cặp, nguồn gốc nhãn, split, seed, tham số, số gộp đúng, gộp nhầm và bỏ sót theo từng mẫu. Giữ kết quả kiểm thử phần mềm riêng với số đo chất lượng. Dùng lệnh trong [quy trình đánh giá](../docs/evaluation.md) để tái tạo, và dẫn đến đường dẫn cục bộ của bằng chứng thay vì tạo thêm một báo cáo validation grouping.
