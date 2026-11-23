# So sánh các pipeline trích xuất và phân loại của SmartNotice v3.3

**Ngày tổng hợp 23/11/2026.** Với ba tác vụ tìm ranh giới cụm, gán kiểu cụm và nối quan hệ trong thông báo học vụ tiếng Việt, **BamiBERT hai giai đoạn theo từng công việc** đạt kết quả tốt nhất trong các pipeline đã chấm trên test thường. Mô hình đạt **47,07% F1 ranh giới**, **46,11% F1 cụm đúng cả ranh giới và kiểu**, và **21,85% F1 liên kết đúng cả hai đầu mút và vai trò**. Khi yêu cầu khôi phục trọn sự kiện, mô hình chỉ khớp **15 trong 468 sự kiện**. Với mục tiêu nhắc hạn, pipeline dùng mẫu thông báo vẫn tìm đúng nhiều ngày tường minh hơn một trường hợp. [Điểm Kaggle chấm cục bộ](../results/08-local_scores.json) · Điểm pipeline mẫu (`reports/generated/drive-improvement-20261123/test.json`)

## 1. Dữ liệu và đơn vị so sánh

Các lần chạy dùng bản Drive `split_65_15_20_v3_3_2026-11-15`. Đầu vào là văn bản email và thông báo web đã chuẩn hóa, che thông tin cá nhân và tách câu. Mỗi cụm giữ mã tài liệu và khoảng ký tự trên văn bản đã chuẩn bị. Phân bổ dùng seed 42 và ngưỡng tương đồng 0,8 để gom tài liệu theo nhóm. Cửa sổ token, sự kiện và cặp sự kiện–hồ sơ kế thừa tập của thông báo gốc. Bản phát hành Drive · Biên bản phân bổ

**Bảng 1. Số đơn vị dùng để huấn luyện, chọn mô hình và tính điểm.**

| Tập | Thông báo | Email / web | Nhóm | Cụm có kiểu | Liên kết | Sự kiện |
|---|---:|---:|---:|---:|---:|---:|
| Train | 403 | 281 / 122 | 281 | 4.664 | 3.847 | 1.516 |
| Validation | 93 | 65 / 28 | 77 | 1.078 | 873 | 357 |
| Test thường | 126 | 88 / 38 | 118 | 1.412 | 1.149 | 468 |
| Test chuyển miền | 62 | 0 / 62 | 29 | Chưa chấm | Chưa chấm | Chưa chấm |

Tổng cộng có 684 thông báo thuộc 505 nhóm. Nhãn tham chiếu trích xuất là chú giải lịch sử có máy hỗ trợ. Bản phát hành ghi `gold_ready=false` và `manual_group_review_completed=false`. Nhãn áp dụng là nhãn *silver* do luật sinh với hồ sơ tổng hợp. Các phép so sánh đã sử dụng lại cùng test thường. Vì vậy thứ hạng dưới đây mô tả mức khớp với bản chú giải v3.3. Độ chính xác theo đánh giá độc lập của người chú giải và khả năng chuyển sang nguồn web mới còn là hai câu hỏi mở. Nguồn gốc chú giải và hash đầu vào (`reports/generated/kaggle-action-v33-20261123/run.json`) · [Giao thức đánh giá](../../../docs/evaluation.md)

## 2. Đầu ra và cách tính điểm

Ví dụ tổng hợp để minh họa cách chấm. Trong câu “Sinh viên K24 đăng ký trước 20/11 và nộp phí trước 25/11”, hệ thống phải tìm riêng hai công việc, nhận đúng hai cụm thời gian và gắn từng hạn vào đúng việc. Nếu nhận ra cả hai ngày nhưng gắn ngày 25/11 cho việc đăng ký, điểm cụm có thể giữ nguyên trong khi liên kết hạn chót và sự kiện đăng ký bị tính sai.

| Phép đo | Điều kiện để tính một dự đoán đúng |
|---|---|
| Ranh giới cụm | Cùng tài liệu, cùng vị trí bắt đầu và kết thúc. Các kiểu trên cùng khoảng được gộp khi đếm. |
| Cụm có kiểu | Khớp ranh giới và một trong sáu kiểu `ACTION`, `TIME`, `AUDIENCE`, `CONDITION`, `CHANNEL`, `DOCUMENT`. Một khoảng có thể mang nhiều kiểu. |
| Liên kết từ văn bản | Khớp cụm công việc, cụm đối số, kiểu của cả hai và vai trò. Với `TIME`, vai trò có thể là `START`, `DEADLINE` hoặc `EVENT_TIME`. |
| Sự kiện đúng toàn bộ | Khớp công việc, toàn bộ tập đối số, vai trò và thông tin ngày theo trình chấm. Thêm sai một đối số cũng làm mất sự kiện đúng. |
| Ngày tường minh đúng đầu cuối | Khớp liên kết thời gian và giá trị ngày đã chuẩn hóa. Mẫu số test là toàn bộ 188 liên kết có ngày tường minh. |
| Sự kiện và nhãn áp dụng đồng thời | Cùng hồ sơ, sự kiện khớp toàn bộ và nhãn áp dụng đúng. Test có 468 × 24 = 11.232 cặp tham chiếu. |

Các bảng trích xuất dùng micro-F1, cộng số dự đoán đúng trên tất cả tài liệu trước khi tính. Với M dự đoán khớp, P dự đoán và R đơn vị tham chiếu, precision = M/P, recall = M/R và F1 = 2M/(P + R). Phép chẩn đoán cấp sẵn cả hai đầu mút hoặc cấp sẵn công việc được ghi riêng vì mỗi phép loại đi một nguồn lỗi khác nhau. Macro-F1 áp dụng là trung bình F1 của ba lớp. [Mã chấm mô hình hai giai đoạn](../../../tools/score_action_conditioned.py) · [Định nghĩa đánh giá](../../../docs/evaluation.md)

## 3. Các pipeline đã triển khai

### 3.1. BamiBERT dùng chung encoder cho cụm và liên kết

Mô hình chia văn bản thành cửa sổ 256 token chồng lấn 96 token, liệt kê cụm trong từng câu với độ rộng tối đa 60 token và chấm sáu kiểu bằng các đầu sigmoid. Với từng `ACTION`, đầu liên kết xét đối số cùng thông báo, dùng biểu diễn hai đầu mút, kiểu đối số, khoảng cách có hướng và vị trí câu hoặc cửa sổ. Kiểu đối số giới hạn các vai trò hợp lệ. Mỗi công việc được giữ tạo một sự kiện. Bộ chuẩn hóa ngày xử lý các dạng ngày số và năm tham chiếu. [Notebook thực nghiệm](../legacy/01_bamibert_development.ipynb) · [Mã dựng sự kiện](../../../src/modeling/extraction.py)

- **Tinh chỉnh toàn bộ trên RTX 3050 Ti 4 GiB.** Lượt đầu dừng khi AdamW cấp phát trạng thái tối ưu. Lượt này không sinh điểm đánh giá.
- **LoRA thử nghiệm.** Không gian ứng viên bao phủ khoảng 96,0% cụm validation, nhưng ở cả ngưỡng thấp nhất đã thử là 0,25, mô hình không xuất cụm. Đầu liên kết đạt khoảng 30,6% F1 khi được cấp hai đầu mút chú giải. Điểm lượt thử (`reports/generated/bamibert/v3_3-2026-11-23-lora-seed42/extraction_metrics.json`)
- **LoRA trọng số dương 8.** Huấn luyện một epoch làm nóng đầu cụm rồi ba epoch kết hợp. LoRA dùng hạng 8, alpha 16, dropout 0,05 trên query và value. Adapter dùng learning rate 0,0001, các đầu dự đoán dùng 0,0003. Ngưỡng cụm và liên kết khi chạy từ văn bản đều là 0,65. Đầu liên kết đạt 43,06% F1 trên hai đầu mút chú giải với ngưỡng 0,50. [Thiết lập và điểm validation](bamibert-v3.3-validation-2026-11-23.md)
- **Hai biến thể.** Một biến thể giữ nguyên checkpoint rồi loại tham lam các cụm chồng lấn cùng kiểu theo thứ tự điểm giảm dần. Biến thể còn lại huấn luyện lại với trọng số dương 2 để kiểm tra sự đánh đổi giữa số cụm và liên kết đúng. Đánh giá lọc chồng lấn (`reports/generated/bamibert/v3_3-2026-11-23-final-seed42/overlap_suppression_metrics.json`) · Lượt huấn luyện trọng số 2 (`reports/generated/drive-improvement-20261123/weight2/run.json`)

### 3.2. Gán nhãn token và tìm mẫu trong train

1. **Mô hình ngữ cảnh.** Sáu bộ phân loại tuyến tính học nhãn bắt đầu, bên trong và ngoài cụm (BIO) riêng cho từng kiểu. Đặc trưng gồm từ lân cận, cặp từ, kiểu chữ và nguồn email/web. Bộ nối đối số dùng hồi quy logistic với hướng, khoảng cách câu và ngữ cảnh giữa công việc với đối số.
2. **Bổ sung mẫu câu.** Đối với mỗi câu, hệ thống tìm câu train gần nhất theo cosine trên chuỗi con 3–5 ký tự. Từ ngưỡng 0,65, hệ thống chuyển kiểu cụm nếu ánh xạ được hai biên token. Với câu dưới ngưỡng, hệ thống dùng dự đoán BIO.
3. **Bổ sung mẫu thông báo.** Khi độ tương đồng toàn văn đạt 0,60, hệ thống căn chỉnh token và chuyển cả liên kết có hai đầu mút tương ứng. Các cặp còn lại dùng bộ nối ngữ cảnh, với ngưỡng đã chọn 0,65. Ba cấu hình lần lượt cho biết giá trị của đặc trưng cục bộ, mẫu câu và cấu trúc lặp lại ở cấp thông báo. [Mã so sánh](../../../tools/compare_notice_pipelines.py) · Cấu hình đã chốt (`reports/generated/drive-improvement-20261123/selected.json`)

### 3.3. Cụm theo luật và quan hệ bằng BamiBERT

Hai cách sinh cụm được ghép với ba cách nối, tạo **sáu cấu hình**. Cách thứ nhất dùng từ khóa tiếng Việt cho công việc, đối tượng, điều kiện, kênh, giấy tờ và biểu thức chính quy cho thời gian. Cách thứ hai bổ sung từ điển cụm có kiểu xuất hiện trong ít nhất hai thông báo train, sau khi chuẩn hóa chữ thường và chữ số.

Ba bộ nối lần lượt gắn đối số vào công việc gần nhất, dùng đầu liên kết LoRA gốc, hoặc huấn luyện lại đầu liên kết trong 12 epoch với encoder cố định. Cách huấn luyện lại dùng liên kết chú giải làm mẫu dương và bổ sung cặp âm từ các cụm do luật đề xuất. Trên cùng nguồn cụm, phép so sánh giữ cố định đầu mút để đo riêng hiệu quả đổi bộ nối. Cấu hình được chọn theo micro-F1 liên kết validation dùng từ điển và đầu huấn luyện lại, với ngưỡng 0,70 cho cả đối số thời gian lẫn các kiểu khác. [Mã đánh giá luật và BamiBERT](../../../tools/evaluate_rule_bami.py) · Bản ghi chọn cấu hình (`reports/generated/rule-bami-v33-20261123/selection.json`)

### 3.4. BamiBERT hai giai đoạn theo từng công việc

**Giai đoạn một tìm và gán kiểu cụm.** BamiBERT tính điểm cho mỗi cặp token đầu–cuối theo từng kiểu bằng hàm biaffine, tức hàm học tương tác giữa hai biểu diễn biên. Các kiểu được chấm độc lập để giữ được cụm chồng lấn. Cửa sổ có tối đa 192 token nội dung, bước dịch 128 token. Một cụm rộng tối đa 64 token và nằm trong một câu.

**Giai đoạn hai tìm đối số riêng cho từng công việc.** Bộ mã hóa thứ hai khởi tạo từ checkpoint đã chọn ở giai đoạn một. Mỗi lượt đưa cụm công việc vào đầu chuỗi, rồi quét các cửa sổ trong thông báo, dùng vị trí và khoảng cách câu tới công việc để chấm cặp biên theo vai trò. Cách này cho phép tìm đối số ở câu khác, dùng chung đối số cho nhiều công việc và tìm thêm đối số mà giai đoạn một đã bỏ sót. Tập cụm đầu ra gồm cụm giai đoạn một và đối số thu hồi ở giai đoạn hai. Bộ dựng sự kiện bỏ cặp công việc–đối số có nhiều vai trò vượt ngưỡng. Trên test có bốn cặp như vậy. [Mã huấn luyện và suy luận](../../../tools/run_action_conditioned.py) · Kiểm tra độ bao phủ cửa sổ (`reports/generated/kaggle-action-v33-20261123/window_audit.json`)

Hai giai đoạn tinh chỉnh toàn bộ encoder, mỗi giai đoạn bốn epoch, batch 8, seed 42. AdamW dùng learning rate 0,00002 cho encoder và 0,0006 cho đầu dự đoán. Mỗi cửa sổ giữ tối đa 24 ứng viên cho từng kiểu hoặc vai trò trước khi lọc theo ngưỡng. Ngưỡng đã chọn là 0,55 cho cả sáu kiểu cụm, 0,55 cho vai trò START và DOCUMENT, 0,65 cho năm vai trò còn lại. Lượt chạy riêng tư trên **một Tesla T4** mất **555 giây** từ đầu script đến khi ghi xong dự đoán. Kaggle suy luận từ văn bản test, sau đó trình chấm cục bộ ghép dự đoán với nhãn tham chiếu. [Kaggle phiên bản 2](https://www.kaggle.com/code/phattruongpo344/smartnotice-action-conditioned-v33-1123/version/2) · Tham số và môi trường thực chạy (`reports/generated/kaggle-action-v33-20261123/run.json`)

## 4. So sánh khi chọn mô hình trên validation

**Bảng 2. F1 (%) trên 93 thông báo. Cả ba cột đều bắt đầu từ văn bản.**

| Nguồn cụm | Bộ nối hoặc biến thể | Cụm có kiểu | Liên kết | Sự kiện |
|---|---|---:|---:|---:|
| BamiBERT LoRA thử nghiệm | Hai đầu dùng chung encoder | 0,00 | 0,00 | 0,00 |
| BamiBERT LoRA trọng số 8 | Bộ giải mã gốc | 7,52 | 0,82 | 0,59 |
| Cùng checkpoint trọng số 8 | Lọc chồng lấn cùng kiểu | 11,07 | 0,47 | 0,00 |
| BamiBERT LoRA trọng số 2 | Huấn luyện lại | 12,37 | 0,61 | 0,30 |
| BIO ngữ cảnh | Logistic theo kiểu đối số | 10,11 | 1,05 | 0,59 |
| BIO và mẫu câu | Logistic theo kiểu đối số | 17,70 | 7,66 | 2,75 |
| BIO, mẫu câu và mẫu thông báo | Chuyển liên kết và dùng logistic | 18,44 | 10,16 | 3,62 |
| Luật viết tay | Công việc gần nhất | 12,22 | 0,98 | 0,00 |
| Luật viết tay | BamiBERT gốc | 12,22 | 1,15 | 0,17 |
| Luật viết tay | Học lại đầu liên kết | 12,22 | 2,15 | 0,17 |
| Luật và từ điển train | Công việc gần nhất | 10,01 | 1,53 | 0,07 |
| Luật và từ điển train | BamiBERT gốc | 10,01 | 0,39 | 0,07 |
| Luật và từ điển train | Học lại đầu liên kết | 10,01 | 2,77 | 0,07 |
| BamiBERT hai giai đoạn | Tìm đối số theo từng công việc | **44,34** | **24,97** | **7,81** |

Nhóm BIO/mẫu chọn cấu hình bằng F1 sự kiện, dùng F1 liên kết khi hòa. Nhóm luật chọn bằng F1 liên kết. Hai hàng LoRA trọng số 8 dùng cùng trọng số mô hình nhưng từng cách giải mã có ngưỡng riêng. Khi lọc chồng lấn với ngưỡng cụm/liên kết 0,90/0,50, số công việc khớp giảm từ 187 xuống 33 trên 357. Vì cả ngưỡng lẫn cách lọc thay đổi, chênh lệch giữa hai hàng phản ánh tác động kết hợp. Điểm BIO và mẫu (`reports/generated/drive-improvement-20261123/validation.json`) · Sáu cấu hình luật (`reports/generated/rule-bami-v33-20261123/select.json`) · [Điểm hai giai đoạn](../results/08-local_scores.json)

## 5. So sánh trên test thường

**Bảng 3. Năm cấu hình đã chấm trên cùng 126 thông báo. Ba cột F1 tính bằng %. Hai cột số đếm ghi số đúng / số dự đoán.**

| Pipeline | F1 cụm có kiểu | F1 liên kết | F1 sự kiện | Liên kết đúng / dự đoán | Sự kiện đúng / dự đoán | Ngày đúng / 188 |
|---|---:|---:|---:|---:|---:|---:|
| BamiBERT LoRA trọng số 8 | 7,45 | 1,36 | 0,31 | 13 / 767 | 9 / 5.271 | 0 |
| BIO và mẫu thông báo | 19,54 | 9,97 | 1,48 | 84 / 536 | 6 / 343 | **16** |
| Luật và từ điển, nối gần nhất | 11,11 | 1,46 | 0,12 | 32 / 3.223 | 2 / 2.766 | 2 |
| Cùng cụm luật, học lại đầu BamiBERT | 11,11 | 2,79 | 0,19 | 50 / 2.435 | 3 / 2.766 | 7 |
| BamiBERT theo từng công việc | **46,11** | **21,85** | **3,09** | **232 / 975** | **15 / 502** | 15 |

**Luật tìm cụm và BamiBERT nối quan hệ.** Đổi bộ nối trên cùng đầu mút làm số liên kết đúng tăng từ 32 lên 50, đồng thời giảm 788 dự đoán. Giới hạn lớn hơn nằm ở bước tìm cụm. Trong 1.149 liên kết tham chiếu, chỉ 118 có đủ hai cụm đúng kiểu và ranh giới do luật tìm thấy. Sau khi căn chỉnh với tokenizer và cửa sổ của checkpoint, còn 92 cặp có thể thu hồi. Dù bộ nối phân loại hoàn hảo trên các cặp đó, recall tối đa cũng chỉ đạt 92/1.149 = 8,01%. Số đếm theo từng bước của pipeline luật (`reports/generated/rule-bami-v33-20261123/test.json`)

**Mẫu thông báo và BamiBERT theo từng công việc.** Trên cùng test, hai giai đoạn tăng 26,57 điểm phần trăm F1 cụm có kiểu, 11,88 điểm F1 liên kết và 1,61 điểm F1 sự kiện so với dùng mẫu. Riêng ngày tường minh, mẫu thông báo chuẩn hóa đúng 16 trong 20 liên kết đã khớp, còn hai giai đoạn đúng 15 trong 38. Mô hình hai giai đoạn tìm đúng nhiều liên kết thời gian hơn nhưng kết quả chuẩn hóa ngày chưa tăng theo. Kiến trúc, cách huấn luyện và cách giải mã đều thay đổi giữa các họ mô hình, nên phép so sánh này chưa tách được đóng góp của từng thay đổi. Điểm pipeline mẫu (`reports/generated/drive-improvement-20261123/test.json`) · [Điểm hai giai đoạn](../results/08-local_scores.json)

## 6. Phân tích ba tác vụ trên mô hình đạt điểm cao nhất

**Tìm ranh giới và gán kiểu.** Khi gộp các kiểu trên cùng khoảng, mô hình tìm đúng 718 trong 1.639 khoảng dự đoán trên 1.412 khoảng tham chiếu, đạt 47,07% F1. Trong 718 khoảng đã khớp, **699 có đúng toàn bộ tập kiểu (97,35%)**. Tỷ lệ 97,35% chỉ trả lời câu hỏi gán kiểu sau khi đã tìm đúng biên. Với toàn bộ văn bản, mô hình trả đúng 706 trong 1.650 cụm có kiểu, tương ứng precision 42,79%, recall 50,00%, F1 46,11%. Giai đoạn một riêng lẻ đạt 45,42% F1 cụm có kiểu. [Số đếm ranh giới và kiểu](../results/08-local_scores.json)

**Bảng 4. Kết quả theo kiểu cụm trên test thường.**

| Kiểu cụm | Đúng | Dự đoán | Tham chiếu | F1 (%) |
|---|---:|---:|---:|---:|
| ACTION – công việc | 192 | 502 | 468 | 39,59 |
| TIME – mốc thời gian | 172 | 404 | 296 | 49,14 |
| AUDIENCE – đối tượng | 115 | 234 | 190 | 54,25 |
| CONDITION – điều kiện | 40 | 90 | 96 | 43,01 |
| CHANNEL – kênh thực hiện | 111 | 250 | 190 | 50,45 |
| DOCUMENT – giấy tờ | 76 | 170 | 172 | 44,44 |

**Nối quan hệ.** Trên validation, khi cấp sẵn công việc chú giải, đầu tìm đối số đạt 46,21% F1 liên kết trước bước bỏ cặp xung đột vai trò. Khi dùng công việc dự đoán và dựng sự kiện, hệ thống đạt 24,97%. Trên test, 591/1.149 liên kết tham chiếu có công việc khớp, chỉ 354 có đủ hai cụm ở giai đoạn một. Giai đoạn hai lấy lại 16 liên kết đúng có đối số bị bỏ sót ở giai đoạn một. Hệ thống khớp 133/723 liên kết qua câu. Tính chung, precision liên kết là 23,79% và recall là 20,19%. [Số đếm theo công việc và khoảng cách câu](../results/08-local_scores.json)

**Bảng 5. Hiệu quả nối theo vai trò trên test thường.**

| Vai trò | Đúng | Dự đoán | Tham chiếu | F1 (%) |
|---|---:|---:|---:|---:|
| START – thời điểm bắt đầu | 10 | 81 | 61 | 14,08 |
| DEADLINE – hạn chót | 26 | 107 | 139 | 21,14 |
| EVENT_TIME – thời điểm diễn ra | 16 | 62 | 113 | 18,29 |
| AUDIENCE | 67 | 320 | 332 | 20,55 |
| CONDITION | 32 | 93 | 138 | 27,71 |
| CHANNEL | 55 | 166 | 192 | 30,73 |
| DOCUMENT | 26 | 146 | 174 | 16,25 |

**Sự kiện và ngày.** Chỉ 15/502 sự kiện dự đoán khớp toàn bộ, tương ứng precision 2,99% và recall 3,21%. Trong 188 mốc ngày tường minh, 150 mất trước khâu chuẩn hóa do liên kết chưa khớp. Trong 38 mốc còn lại, 23 có giá trị ngày chuẩn hóa sai. Cả ba liên kết có ngày suy ra đều bị bỏ sót. Ba số đếm này phân biệt lỗi tìm bằng chứng, lỗi gắn vai trò và lỗi chuyển ngày sang giá trị dùng để nhắc hạn. [Điểm sự kiện và ngày](../results/08-local_scores.json)

## 7. Phân loại mức áp dụng với hồ sơ sinh viên

Bộ phân loại BamiBERT riêng nhận hai chuỗi. Chuỗi thứ nhất mô tả công việc, đối tượng, điều kiện và câu bằng chứng. Chuỗi thứ hai mô tả hồ sơ sinh viên. Mô hình dự đoán `APPLIES`, `NOT_APPLIES` hoặc `UNCLEAR`. Bộ sinh nhãn dùng ràng buộc có cấu trúc để tạo nhãn silver. Đầu vào mô hình chỉ dùng bằng chứng và hồ sơ. Từ 1.051 hồ sơ tổng hợp sinh từ train, thí nghiệm lấy mẫu 4.062 cặp huấn luyện. Panel đánh giá ghép mỗi sự kiện với cùng 24 hồ sơ. [Mã phân loại mức áp dụng](../../../src/modeling/applicability.py) · [Biên bản huấn luyện](bamibert-v3.3-validation-2026-11-23.md)

**Cấp sẵn sự kiện chú giải.** Trên 8.568 cặp validation, mô hình đạt accuracy 74,14% và Macro-F1 65,87%. Dự đoán lớp phổ biến cho mọi cặp đạt lần lượt 55,5% và 23,8%. F1 theo lớp đạt 73,81% cho APPLIES, 42,81% cho NOT_APPLIES và 81,01% cho UNCLEAR. Trong 1.560 trường hợp NOT_APPLIES, mô hình trả UNCLEAR cho 897 trường hợp. Hiệu chỉnh nhiệt độ ở 0,811 và chỉ nhận dự đoán có xác suất từ 0,60 giữ lại 6.213/8.568 cặp (72,51%), với accuracy 85,26% trên phần giữ lại. Ngưỡng này được chọn và đo trên cùng validation. Điểm phân loại và ma trận nhầm lẫn (`reports/generated/bamibert/v3_3-2026-11-23-final-seed42/applicability_annotated_metrics.json`)

**Dùng sự kiện dự đoán.** Trên validation, F1 đồng thời đúng cả sự kiện và nhãn áp dụng lần lượt là 0,59% (LoRA trọng số 8), 0,00% (lọc chồng lấn), 0,30% (LoRA trọng số 2), 0,59% (BIO), 2,05% (thêm mẫu câu) và 2,24% (thêm mẫu thông báo). Trong lần so sánh test ban đầu, LoRA trọng số 8 đạt 0,31% và pipeline mẫu thông báo đạt 0,87%. Pipeline mẫu thông báo có 85 cặp đúng toàn bộ trong 8.232 cặp dự đoán và 11.232 cặp tham chiếu. Lần chạy notebook chấm thêm pipeline mẫu câu trên cùng test và cùng bộ phân loại hồ sơ, đạt 1,07%. Các lượt luật–BamiBERT và Kaggle hai giai đoạn chỉ đo trích xuất. Điểm đồng thời trên validation (`reports/generated/drive-improvement-20261123/validation.json`) · Điểm đồng thời trên test (`reports/generated/drive-improvement-20261123/test.json`) · [Kết quả chạy notebook](../README.md)

## 8. Độ ổn định và lựa chọn cho lần thử tiếp theo

Chỉ pipeline mẫu thông báo có thí nghiệm đánh giá biến thiên qua cả nhóm dữ liệu và seed. Năm lượt GroupKFold trên 496 thông báo phát triển xây lại bộ gán nhãn, bộ nối và chỉ mục mẫu từ phần train của từng fold. Giá trị sau dấu ± là độ lệch chuẩn mẫu, tính bằng điểm phần trăm. Kết quả từng fold và seed (`reports/generated/drive-improvement-20261123/stability.json`)

| Phép lặp riêng cho pipeline mẫu | F1 cụm (%) | F1 liên kết (%) | F1 sự kiện (%) |
|---|---:|---:|---:|
| 5 fold theo nhóm trên train và validation | 19,96 ± 1,71 | 7,58 ± 1,53 | 2,33 ± 0,82 |
| Giữ nguyên phân bổ 403/93, seed 42, 43 và 44 | 18,85 ± 0,36 | 10,27 ± 0,09 | 3,69 ± 0,17 |

Với riêng so sánh mẫu thông báo và LoRA trọng số 8, chênh lệch F1 sự kiện trên test là +1,17 điểm phần trăm. Bootstrap ghép cặp 5.000 lần trên 118 nhóm cho khoảng percentile 95% từ +0,09 đến +2,47 điểm. Mô hình Kaggle mới có một seed. Khi nạp lại checkpoint và chạy năm thông báo validation trên RTX 3050 Ti, máy cục bộ khớp toàn bộ 53 cụm giai đoạn một và 25 liên kết do Kaggle trả về, đồng thời phát thêm một liên kết. Các bảng trên dùng dự đoán gốc của Kaggle. Bootstrap theo nhóm (`reports/generated/drive-improvement-20261123/paired_events.json`) · Hash checkpoint và kiểm tra chạy lại (`reports/generated/kaggle-action-v33-20261123/checkpoint_replay.json`)

**Lựa chọn theo mục tiêu.** Dùng BamiBERT hai giai đoạn làm mốc cho ba tác vụ trích xuất. Giữ pipeline mẫu thông báo làm đối chứng cho ngày tường minh và cho phép đo có hồ sơ sinh viên. Dùng pipeline luật với bộ nối gần nhất và bộ nối BamiBERT khi cần tách ảnh hưởng của đổi bộ nối trên cùng tập cụm đầu vào.

**Ưu tiên cải tiến đề xuất.** Trước hết phân tích lỗi biên ACTION trên tập phát triển vì mô hình chỉ tìm đúng 192/468 công việc test và mọi sự kiện đều cần công việc đúng. Tiếp theo, chấm riêng hai bước nối TIME và chuẩn hóa ngày trên cùng mốc đã nối đúng. Cuối cùng, chạy nhiều seed với cấu hình cố định, đánh giá nhánh áp dụng từ sự kiện do mô hình hai giai đoạn dự đoán và chốt cấu hình trước khi chấm trên tập được chú giải độc lập. Đây là các phép thử tiếp theo để xác định thay đổi nào cải thiện chất lượng.

## 9. Hồ sơ tái lập

[Các notebook từ dữ liệu đến chấm điểm](../README.md) cung cấp lệnh thực thi, cấu hình dữ liệu và liên kết tới từng pipeline.

| Cần đối chiếu | Mã và bằng chứng của lượt chạy |
|---|---|
| LoRA, biến thể giải mã, mức áp dụng | [Notebook](../legacy/01_bamibert_development.ipynb) · Tham số và môi trường (`reports/generated/bamibert/v3_3-2026-11-23-final-seed42/run.json`) · [Báo cáo gốc](bamibert-v3.3-validation-2026-11-23.md) |
| BIO, mẫu câu và mẫu thông báo | [Trình so sánh](../../../tools/compare_notice_pipelines.py) · Cấu hình đã chọn (`reports/generated/drive-improvement-20261123/selected.json`) · [Quy trình chạy và chấm](drive-v3.3-pipeline-comparison-2026-11-23.md) |
| Sáu cấu hình luật và bộ nối | [Trình đánh giá](../../../tools/evaluate_rule_bami.py) · Điểm validation (`reports/generated/rule-bami-v33-20261123/select.json`) · [Báo cáo gốc](rule-spans-bamibert-relations-2026-11-23.md) |
| BamiBERT theo từng công việc | [Checkpoint BamiBERT nền đã ghim](https://huggingface.co/Qualcomm-AI-Research/BamiBERT/tree/57bc1340debbe4e348ec549047a763caebe4a977) · Bản ghi gói Kaggle (`reports/generated/kaggle-action-v33-20261123/submission.json`) · [Trình chấm](../../../tools/score_action_conditioned.py) · [Báo cáo gốc](kaggle-action-conditioned-v3.3-2026-11-23.md) |

Các đường dẫn `generated/` trỏ tới bằng chứng của lượt chạy trong workspace. Bản tổng hợp dùng số liệu đã lưu, không huấn luyện lại mô hình.
