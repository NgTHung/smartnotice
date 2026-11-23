# Dữ liệu, pipeline và kết quả BamiBERT trên SmartNotice v3.3

SmartNotice đọc thông báo học vụ tiếng Việt để tìm việc cần làm, thời hạn và đối tượng áp dụng. Lần chạy ngày 23/11/2026 kiểm tra ba thành phần là nhận diện cụm bằng chứng, nối đối số và gán vai trò thời gian, và phân loại mức áp dụng với hồ sơ sinh viên. Báo cáo này mô tả dữ liệu, các bước thực hiện trong notebook và kết quả so sánh trên validation. Pipeline đạt Macro-F1 65,87% khi phân loại mức áp dụng từ sự kiện chú giải, còn F1 sự kiện đúng toàn bộ từ văn bản đầu vào là 0,59%.

## Phiên bản và phạm vi dữ liệu

Thí nghiệm dùng bản `split_65_15_20_v3_3_2026-11-15` từ thư mục Google Drive được chỉ định. Bản phát hành gồm 684 thông báo đã chuẩn bị, trong đó có 434 email và 250 thông báo web. Có 534 tài liệu kế thừa từ bản trước và 150 thông báo web bổ sung. Dữ liệu đầu vào đã qua quy trình chuẩn hóa văn bản, tách câu và che thông tin cá nhân của SmartNotice. Quy trình thu thập dùng email do người tham gia tự nguyện cung cấp và thông báo công khai trên web. Bản phát hành v3.3, [quy trình thu thập](../../../docs/collection.md).

Bản phát hành dành riêng 62 thông báo web để kiểm tra khả năng chuyển miền. Phần còn lại có 622 tài liệu, được chia theo nhóm với mục tiêu 65/15/20. Nhóm dùng để giữ thư cùng luồng, mẫu và bản gần trùng trong cùng tập. Biên bản ghi ngưỡng tương đồng 0,8, seed chia 42, seed chọn web giữ riêng 42 và 505 nhóm. Bảng 1 báo cáo số thực tế của bản phát hành. Cột nhóm đếm `group_id` phân biệt trong tệp phân bổ. Số email/web của test thường được suy ra từ tổng theo nguồn và các tập còn lại. Biên bản phân bổ, [quy trình chia dữ liệu](../../../docs/data-splitting.md).

| Tập | Thông báo | Email / web | Nhóm | Dùng trong lần chạy |
|---|---:|---:|---:|---|
| Train | 403 | 281 / 122 | 281 | Huấn luyện và sinh hồ sơ tổng hợp |
| Validation | 93 | 65 / 28 | 77 | Chọn checkpoint, ngưỡng và hiệu chỉnh xác suất |
| Test thường | 126 | 88 / 38 | 118 | Giữ riêng để đánh giá cuối |
| Web domain test | 62 | 0 / 62 | 29 | Giữ riêng để đánh giá chuyển miền |
| Tổng | 684 | 434 / 250 | 505 | |

Bảng 1. Phân bổ theo nguồn và nhóm của SmartNotice v3.3.

Notebook đọc bốn tệp `notices.jsonl` và `annotations.jsonl` của train và validation, cùng với `assignments.jsonl`, `record.json` và `checksums.json`. Khi nạp dữ liệu, notebook kiểm tra SHA-256 của tệp và văn bản, khớp `doc_id`, kiểm tra cụm và đối số theo schema và kiểm tra nhóm không trùng giữa các tập. Cửa sổ token, sự kiện và cặp sự kiện/hồ sơ giữ tập của tài liệu gốc. [Mã nạp dữ liệu](../../../src/modeling/data.py), [hợp đồng dữ liệu](../../../docs/interface.md).

Bảng 2 mô tả dữ liệu gửi vào mô hình. Số cụm phân biệt đếm theo bộ gồm tài liệu, khoảng ký tự và kiểu. Số liên kết phân biệt đếm theo các đầu mút và vai trò chú giải.

| Tập | Thông báo | Email / web | Nhóm | Cửa sổ token | Sự kiện | Cụm phân biệt | Liên kết phân biệt |
|---|---:|---:|---:|---:|---:|---:|---:|
| Train | 403 | 281 / 122 | 281 | 1.221 | 1.516 | 4.664 | 3.847 |
| Validation | 93 | 65 / 28 | 77 | 284 | 357 | 1.078 | 873 |

Bảng 2. Quy mô dữ liệu train và validation đã nạp và chia cửa sổ.

Độ dài trung vị của văn bản chuẩn bị là 1.015 ký tự ở train và 1.318 ở validation. Phân vị 90 theo hạng gần nhất lần lượt là 3.356 và 3.064 ký tự. Thông báo dài nhất có 14.425 ký tự ở train và 9.105 ở validation. Bảng 3 cho biết số cụm theo kiểu. `CONDITION` là kiểu có ít ví dụ train nhất trong sáu kiểu.

| Kiểu cụm | Vai trò trong sự kiện | Train | Validation |
|---|---|---:|---:|
| `ACTION` | Việc cần làm | 1.516 | 357 |
| `TIME` | Mốc thời gian liên quan | 983 | 225 |
| `AUDIENCE` | Nhóm người được thông báo | 638 | 147 |
| `CONDITION` | Điều kiện để sự kiện áp dụng | 326 | 77 |
| `CHANNEL` | Nơi, cách thức hoặc đường dẫn thực hiện | 638 | 149 |
| `DOCUMENT` | Giấy tờ cần dùng hoặc nộp | 563 | 123 |

Bảng 3. Số cụm phân biệt theo kiểu chú giải trong dữ liệu phát triển.

Nhãn trích xuất là bản nháp đã qua rà soát. Nhãn áp dụng là nhãn silver sinh bằng luật từ ràng buộc đối tượng và hồ sơ tổng hợp. Biên bản ghi `gold_ready=false` và `manual_group_review_completed=false`. Phép kiểm tra nhóm trong notebook xác nhận phân bổ theo mã nhóm. Việc xem xét thủ công chất lượng nhóm và gán nhãn độc lập cho các tập test vẫn là điều kiện để báo cáo kết quả gold. [Quy trình chú giải](../../../docs/annotation.md), [giao thức đánh giá](../../../docs/evaluation.md).

## Pipeline thực nghiệm

Mô hình trích xuất dùng chung một bộ mã hóa BamiBERT cho đầu nhận diện cụm và đầu phân loại liên kết. Mô hình áp dụng dùng một BamiBERT riêng để mã hóa chung hai chuỗi là bằng chứng sự kiện và hồ sơ sinh viên. Bản chạy ghim checkpoint `Qualcomm-AI-Research/BamiBERT` ở revision `57bc1340debbe4e348ec549047a763caebe4a977`. [Bài báo BamiBERT](https://arxiv.org/abs/2607.02259), [notebook nguồn](../legacy/01_bamibert_development.ipynb).

1. Tạo ứng viên cụm. Tokenizer trả khoảng ký tự để đối chiếu với văn bản chuẩn bị. Notebook bỏ khoảng trắng ở biên token trước khi khớp chú giải. Văn bản được chia thành cửa sổ 256 token, chồng lấn 96 token. Trong mỗi câu, notebook liệt kê các khoảng token liền nhau có độ rộng tối đa 60 token. Giới hạn lấy từ phân vị 99 của độ rộng cụm train có thể khớp với token. Một khoảng xuất hiện ở nhiều cửa sổ được gán về cửa sổ có biên phù hợp hơn. [Tạo ứng viên từ token](../../../src/modeling/data.py).
2. Chấm điểm kiểu cụm. Mỗi ứng viên dùng biểu diễn token đầu, token cuối, trung bình biểu diễn token trong cụm và embedding độ rộng. Một mạng nhỏ tạo sáu điểm sigmoid độc lập cho sáu kiểu cụm. Huấn luyện giữ các cụm dương có thể biểu diễn và lấy mẫu cụm âm, gồm cả khoảng có một biên gần với nhãn đúng. Khi suy luận trên validation, notebook xếp hạng ứng viên có kiểu, giữ tối đa 160 ứng viên mỗi thông báo rồi áp ngưỡng. [Đầu nhận diện cụm](../../../src/modeling/extraction.py).
3. Nối đối số và gán vai trò. Với mỗi `ACTION`, notebook xét các cụm đối số trong cùng tài liệu, kể cả cặp ở hai cửa sổ khác nhau. Đầu liên kết dùng biểu diễn hai đầu mút, kiểu đối số, khoảng cách ký tự có hướng, và tín hiệu cùng câu hoặc khác cửa sổ. Cặp với `TIME` được phép nhận `START`, `DEADLINE`, `EVENT_TIME` hoặc `NO_RELATION`. Với các kiểu còn lại, cặp được phép nhận vai trò tương ứng hoặc `NO_RELATION`. Mô hình học liên kết từ các đầu mút chú giải và chấm điểm cả đầu mút chú giải lẫn đầu mút dự đoán khi đánh giá.
4. Dựng sự kiện và ngày. Mỗi `ACTION` giữ lại tạo một sự kiện. Đối số có liên kết được gắn cùng câu nguồn. Bộ chuẩn hóa xử lý dạng ngày số phù hợp và dùng năm tham chiếu nếu thiếu năm. Trường hợp không phân giải được giữ ngày rỗng. Notebook kiểm tra câu bằng chứng và khoảng ký tự của sự kiện. [Bộ chuẩn hóa ngày](../../../src/preprocessing/dates.py), [hàm dựng sự kiện](../../../src/modeling/extraction.py).
5. Phân loại mức áp dụng. Mô hình nhận công việc, đối tượng, điều kiện đã liên kết và các câu bằng chứng. Chuỗi thứ hai ghi khóa tuyển sinh, bậc học, ngành, chương trình và trạng thái. Mục thiếu được biểu diễn bằng `chưa cung cấp`. Nhãn đích là `APPLIES`, `NOT_APPLIES` hoặc `UNCLEAR`. Ràng buộc có cấu trúc và mã lý do chỉ dùng sinh nhãn hoặc phân tích. [Bộ phân loại sự kiện và hồ sơ](../../../src/modeling/applicability.py).

Ví dụ minh họa tổng hợp. Với câu “Sinh viên K24 đăng ký học phần trước 20/11 và nộp học phí trước 25/11”, bước 1 tạo ứng viên cho hai công việc, hai ngày và đối tượng. Bước 3 xét cả bốn cặp công việc/ngày để tách hạn đúng của từng việc. Cụm đối tượng có thể được dùng chung. Khi đã có sự kiện cùng bằng chứng, bước 5 đối chiếu với hồ sơ, chẳng hạn một sinh viên K24.

## Huấn luyện và chọn checkpoint

Full fine-tuning cập nhật toàn bộ bộ mã hóa. LoRA giữ cố định các trọng số gốc và huấn luyện các ma trận hạng thấp cùng đầu phân loại. Bảng 4 ghi cấu hình hoàn thành thí nghiệm. Cả hai mô hình dùng AdamW với weight decay 0,01, lịch tăng learning rate trong khoảng 10% bước đầu rồi giảm tuyến tính, và chặn chuẩn gradient ở 1. [Cấu hình huấn luyện trong mã](../../../src/modeling/experiment.py), [tài liệu LoRA](https://huggingface.co/docs/peft/en/package_reference/lora).

| Thiết lập | Trích xuất cụm và liên kết | Phân loại mức áp dụng |
|---|---|---|
| Bộ mã hóa | BamiBERT dùng chung cho hai đầu | BamiBERT phân loại cặp chuỗi |
| LoRA | Hạng 8, alpha 16, dropout 0,05 trên query và value | Cùng cấu hình |
| Learning rate | Adapter 0,0001, đầu phân loại 0,0003 | Cùng cấu hình |
| Epoch | 1 epoch học cụm, 3 epoch học kết hợp | 2 epoch |
| Tích lũy gradient | 8 tài liệu, trừ lô cuối có thể ngắn hơn | 2 lô × 6 cặp, trừ lô cuối có thể ngắn hơn |
| Hàm mất mát | Binary cross-entropy theo từng kiểu cụm, trọng số dương 8. Giai đoạn kết hợp cộng cross-entropy liên kết. | Cross-entropy ba lớp |
| Chọn checkpoint | Micro-F1 liên kết từ cụm dự đoán, dùng F1 sự kiện khi cần phân định | Macro-F1 áp dụng từ sự kiện chú giải |
| Seed | 42 | 42 |

Bảng 4. Thiết lập của hai mô hình trong lần chạy LoRA hoàn thành.

Full fine-tuning dừng ở bước AdamW cấp phát trạng thái trên GPU RTX 3050 Ti Laptop 4 GiB. Lần chạy LoRA đầu tiên dùng seed 42, đạt độ bao phủ ứng viên cụm 96,0% trên validation và F1 liên kết 30,6% với cụm chú giải. Với ngưỡng thấp nhất 0,25, đầu nhận diện cụm không xuất dự đoán. Điều này làm F1 từ cụm dự đoán bằng 0. Lần chạy kế tiếp tăng trọng số dương trong hàm mất mát cụm lên 8, thêm các ngưỡng thấp hơn, và dùng một epoch làm nóng đầu cụm cùng ba epoch huấn luyện kết hợp. Đây là các thay đổi dựa trên kết quả validation.

Môi trường cục bộ dùng Python 3.14.2, PyTorch 2.12.1+cu132, Transformers 4.57.6, PEFT 0.17.1 và scikit-learn 1.8.0. Cấu hình và mã băm (`reports/generated/bamibert/v3_3-2026-11-23-weighted-seed42/run.json`), kết quả chẩn đoán ban đầu (`reports/generated/bamibert/v3_3-2026-11-23-lora-seed42/extraction_metrics.json`).

Release ghi `provider_use_approved=false`. Thí nghiệm dùng dữ liệu Drive trên máy cục bộ. Dữ liệu không được tải lên Kaggle. Biên bản release.

Tập hồ sơ gồm 1.051 hồ sơ tổng hợp sinh từ ràng buộc train. Sau lấy mẫu tối đa hai hồ sơ cho mỗi lớp trong mỗi sự kiện, tập train có 4.062 cặp. Mỗi sự kiện validation được ghép với cùng 24 hồ sơ chọn theo seed, tạo 8.568 cặp gồm 2.254 APPLIES, 1.560 NOT_APPLIES và 4.754 UNCLEAR. Phương án dự đoán lớp phổ biến nhất trong train cho tất cả cặp đạt accuracy 55,5% và Macro-F1 23,8% trên panel này.

## Cách tính điểm

- Độ bao phủ ứng viên là tỷ lệ cụm chú giải có thể biểu diễn bằng token, hoặc tỷ lệ liên kết chú giải có đủ hai đầu mút trong các cặp đã tạo. Chỉ số này đo tập ứng viên trước bước quyết định nhãn tương ứng.
- Cụm đúng khi trùng tài liệu, ký tự bắt đầu, ký tự kết thúc và kiểu. Liên kết đúng khi trùng cả hai cụm và vai trò. Precision chia số đúng cho số dự đoán. Recall chia số đúng cho số chú giải. Micro-F1 lấy trung bình điều hòa của precision và recall sau khi cộng các đếm trên toàn tập.
- Sự kiện đúng toàn bộ khi trùng `ACTION`, tập đối số, vai trò và ngày chuẩn hóa. Sai hoặc thiếu liên kết TIME làm giảm điểm ngày đầu cuối. Độ chính xác của riêng bộ chuẩn hóa được tính trên liên kết TIME đã khớp.
- Macro-F1 áp dụng là trung bình F1 của ba lớp. Trên sự kiện dự đoán, báo cáo thêm Macro-F1 chỉ tính trên những `ACTION` khớp chính xác. Điểm đồng thời đúng sự kiện và nhãn áp dụng tính cả các sự kiện sai hoặc bị bỏ sót.

Notebook chọn ngưỡng cụm, ngưỡng liên kết và checkpoint trên validation. Bộ so sánh loại chồng lấn dùng lại trọng số và chọn ngưỡng riêng trên cùng validation, nên chênh lệch phản ánh hai cấu hình chọn đầu ra. Nó không đo riêng tác động của một phép lọc ở ngưỡng cố định. [Mã tính điểm](../../../src/modeling/metrics.py), [giao thức đánh giá](../../../docs/evaluation.md).

## Kết quả trích xuất trước khi loại cụm chồng lấn

Notebook chọn checkpoint epoch 2 theo F1 liên kết từ cụm dự đoán trên validation. Mô hình chọn ngưỡng cụm 0,65 và ngưỡng liên kết 0,65 cho toàn pipeline. Phép đo với cụm chú giải chọn ngưỡng liên kết 0,50 riêng. Mô hình trích xuất có 824.110 tham số được cập nhật. Huấn luyện và các lượt validation mất 406 giây, với mức cấp phát CUDA cao nhất ghi bởi PyTorch khoảng 743 MiB. Kết quả trích xuất (`reports/generated/bamibert/v3_3-2026-11-23-weighted-seed42/extraction_metrics.json`).

| Chỉ số | Precision | Recall | F1 | Đúng / dự đoán / chú giải |
|---|---:|---:|---:|---:|
| Cụm đúng kiểu và vị trí | 4,11% | 44,06% | 7,52% | 475 / 11.558 / 1.078 |
| Liên kết dùng cụm chú giải | 50,23% | 37,69% | 43,06% | 329 / 655 / 873 |
| Liên kết dùng cụm dự đoán | 1,00% | 0,69% | 0,82% | 6 / 599 / 873 |
| Sự kiện đúng toàn bộ | 0,32% | 3,92% | 0,59% | 14 / 4.426 / 357 |

Bảng 5. Chỉ số validation của cấu hình giữ cụm theo ngưỡng, trước khi loại chồng lấn.

759.496 ứng viên theo vị trí bao phủ 96,01% cụm chú giải. Phép ghép từ các cụm chú giải có thể biểu diễn bao phủ 91,87% liên kết. Khi thay bằng cụm dự đoán, độ bao phủ cặp giảm còn 23,60%. Pipeline chưa khớp được liên kết TIME nào trên 135 mốc có ngày tường minh, 3 mốc có ngày suy ra và 99 mốc chưa chuẩn hóa. Do không có liên kết TIME khớp, không thể tính độ chính xác chuẩn hóa ngày có điều kiện trên liên kết đúng.

Bảng 6 tách kết quả của đầu liên kết theo vai trò khi dùng cụm chú giải. Điều kiện này giúp phân biệt lỗi tìm cụm với lỗi gán vai trò. Cả ba vai trò thời gian đều có ví dụ validation. Với ngưỡng liên kết 0,50, đầu liên kết không phát ra dự đoán nào cho ba vai trò đó.

| Vai trò liên kết | Train | Validation | Đúng / dự đoán trên validation | F1 với cụm chú giải |
|---|---:|---:|---:|---:|
| `START` | 277 | 60 | 0 / 0 | 0,00% |
| `DEADLINE` | 412 | 87 | 0 / 0 | 0,00% |
| `EVENT_TIME` | 364 | 90 | 0 / 0 | 0,00% |
| `AUDIENCE` | 1.057 | 247 | 183 / 380 | 58,37% |
| `CONDITION` | 525 | 93 | 61 / 95 | 64,89% |
| `CHANNEL` | 643 | 158 | 0 / 0 | 0,00% |
| `DOCUMENT` | 569 | 138 | 85 / 180 | 53,46% |

Bảng 6. Phân bố liên kết và F1 theo vai trò trên các đầu mút chú giải.

## Kết quả phân loại áp dụng trên sự kiện chú giải

Với cùng 8.568 cặp validation, Macro-F1 tăng từ 55,21% ở epoch 1 lên 65,87% ở epoch 2. Notebook chọn epoch 2. Mô hình phân loại đúng 6.352 cặp (74,14%). Bảng dưới tính chỉ số trước khi áp dụng ngưỡng xác nhận. Chỉ số phân loại và ma trận nhầm lẫn (`reports/generated/bamibert/v3_3-2026-11-23-final-seed42/applicability_annotated_metrics.json`).

| Lớp | Precision | Recall | F1 | Số cặp chú giải |
|---|---:|---:|---:|---:|
| APPLIES | 76,97% | 70,90% | 73,81% | 2.254 |
| NOT_APPLIES | 68,70% | 31,09% | 42,81% | 1.560 |
| UNCLEAR | 73,78% | 89,80% | 81,01% | 4.754 |

Bảng 7. Precision, recall và F1 theo lớp áp dụng trên 8.568 cặp có sự kiện chú giải.

Mô hình dự đoán UNCLEAR cho 897 trong số 1.560 cặp NOT_APPLIES. Đây là lỗi cần theo dõi khi đánh giá khả năng phát hiện các trường hợp sinh viên nằm ngoài phạm vi áp dụng.

Temperature scaling trên validation cho hệ số 0,811 và giảm negative log-likelihood từ 0,5714 xuống 0,5628. Ở ngưỡng xác suất 0,60, mô hình giữ 6.213 trên 8.568 cặp (72,51%). Accuracy trên các cặp được giữ là 85,26%. Các giá trị này dùng sự kiện chú giải và tập dùng để chọn ngưỡng. Mô hình áp dụng cập nhật 887.811 tham số. Huấn luyện và đánh giá mất 339 giây, với mức cấp phát CUDA cao nhất khoảng 559 MiB.

## So sánh hai cách chọn cụm dự đoán

Thí nghiệm nạp lại cùng trọng số và giữ cụm điểm cao nhất khi hai cụm cùng kiểu chồng lấn. Tập validation không có cặp cụm phân biệt cùng kiểu bị chồng lấn. Tập train có 22 cặp như vậy, đều thuộc kiểu TIME. Mỗi cách chọn cụm dùng ngưỡng liên kết và ngưỡng cụm riêng, chọn theo F1 liên kết trên validation. Chỉ số gốc (`reports/generated/bamibert/v3_3-2026-11-23-final-seed42/metrics.json`), chỉ số sau khi loại chồng lấn (`reports/generated/bamibert/v3_3-2026-11-23-final-seed42/overlap_suppression_metrics.json`).

| Chỉ số | Giữ cụm theo ngưỡng | Loại chồng lấn cùng kiểu |
|---|---:|---:|
| Ngưỡng cụm / liên kết | 0,65 / 0,65 | 0,90 / 0,50 |
| Số cụm dự đoán | 11.558 | 946 |
| F1 cụm đúng kiểu và vị trí | 7,52% | 11,07% |
| F1 liên kết từ cụm dự đoán | 0,82% | 0,47% |
| F1 sự kiện đúng toàn bộ | 0,59% | 0,00% |
| ACTION khớp chính xác trong 357 sự kiện | 187 | 33 |
| Macro-F1 áp dụng trên ACTION khớp | 40,95% (4.488 cặp) | 31,46% (792 cặp) |
| F1 đồng thời đúng sự kiện và nhãn áp dụng | 0,59% | 0,00% |

Bảng 8. So sánh hai cấu hình chọn cụm với cùng bộ trọng số.

Loại chồng lấn tăng precision cụm từ 4,11% lên 11,84% và giảm recall từ 44,06% xuống 10,39%. Hai Macro-F1 trên ACTION khớp dùng các tập con khác nhau. Chỉ số đồng thời dùng toàn bộ 8.568 cặp chú giải làm mẫu số recall cho cả hai cách. Nó tính cả 106.224 cặp sự kiện/hồ sơ dự đoán ở cách gốc và 4.752 cặp ở cách loại chồng lấn vào mẫu số precision. Hai cách đều chưa khớp liên kết TIME nào.

Bảng 9 cho thấy hiệu quả lọc theo từng kiểu cụm. Cấu hình lọc cho điểm `TIME` cao hơn dù số cụm `TIME` đúng giảm từ 167 xuống 39. Số dự đoán `TIME` giảm từ 3.427 xuống 141. Đầu liên kết thời gian vẫn không tìm đúng vai trò, kể cả khi dùng cụm chú giải như ở Bảng 6.

| Kiểu cụm | Số cụm chú giải | F1 giữ theo ngưỡng | F1 loại chồng lấn |
|---|---:|---:|---:|
| `ACTION` | 357 | 7,82% | 11,89% |
| `TIME` | 225 | 9,15% | 21,31% |
| `AUDIENCE` | 147 | 5,52% | 10,61% |
| `CONDITION` | 77 | 0,00% | 0,00% |
| `CHANNEL` | 149 | 6,47% | 0,00% |
| `DOCUMENT` | 123 | 8,76% | 0,00% |

Bảng 9. F1 cụm khớp chính xác theo kiểu và cấu hình chọn đầu ra.

## Hạn chế và bước ưu tiên

Khâu chọn đúng kiểu và ranh giới cụm đang giới hạn pipeline. Với cụm chú giải, F1 liên kết đạt 43,06%. Từ văn bản đầu vào, pipeline chỉ khớp chính xác 14 trên 357 sự kiện trước khi loại chồng lấn. Nên dùng các mẫu âm gần biên và các cụm điểm cao nhưng sai kiểu để kiểm tra lại đầu nhận diện. Sau đó kiểm tra riêng cặp `ACTION`–`TIME` có đầu mút chú giải, gồm phân bố điểm và các lỗi nhầm với `NO_RELATION`, trước khi đánh giá lại ngày chuẩn hóa.

Macro-F1 áp dụng 65,87% mô tả khả năng phân loại cặp có sự kiện chú giải đối với nhãn silver. Điểm này cao hơn 42,08 điểm phần trăm so với phương án dự đoán lớp phổ biến, tính trên cùng panel. Khi dùng bằng chứng dự đoán, Macro-F1 trên phần có `ACTION` khớp là 40,95% với cấu hình giữ cụm theo ngưỡng. Cần đánh giá thêm khả năng nhận diện `NOT_APPLIES` trên các cặp do người chú giải đánh giá độc lập.

Các kết quả dùng một seed và validation tham gia chọn cấu hình. Thí nghiệm chưa có điểm gold-test, chưa đo chuyển miền trên 62 thông báo web giữ riêng và chưa so được chất lượng LoRA với full fine-tuning. So sánh trong báo cáo gồm hai cấu hình chọn đầu ra của cùng BamiBERT và một baseline lớp phổ biến cho tác vụ áp dụng. Các hệ trích xuất dựa trên luật và ViT5 vẫn thuộc kế hoạch so sánh. [Kế hoạch mô hình](../../../docs/bamibert-implementation-2026-11-22.md).

## Tái chạy và kiểm tra

Notebook đã chạy (`reports/generated/bamibert/v3_3-2026-11-23-final-seed42/01_bamibert_development.ipynb`) chứa đầu ra của các cell. Checkpoint trích xuất (`reports/generated/bamibert/v3_3-2026-11-23-final-seed42/extraction.pt`) và checkpoint áp dụng (`reports/generated/bamibert/v3_3-2026-11-23-final-seed42/applicability.pt`) chứa adapter và đầu phân loại. Khi nạp lại, dùng cùng BamiBERT gốc và cấu hình trong biên bản lần chạy (`reports/generated/bamibert/v3_3-2026-11-23-final-seed42/run.json`).

Trong môi trường uv đã cài thư viện huấn luyện, chạy [trình thực thi notebook](../../../tools/run_bamibert_notebook.py) với `--split`, `--checkpoint` và một `--output` mới. Chọn `--resume-extraction` với thư mục chứa checkpoint đã huấn luyện để nối lại từ khâu áp dụng. Chạy [trình so sánh cách chọn cụm](../../../tools/evaluate_bamibert_decoder.py) với cùng split, BamiBERT gốc và thư mục kết quả.

Kiểm tra xác nhận tất cả cell của notebook đã chạy, SHA-256 của hai checkpoint khớp phép so sánh, và số cặp dự đoán trong chỉ số đồng thời bằng số sự kiện dự đoán nhân 24. Bộ kiểm thử phần mềm đạt 310 bài. Các kiểm tra này xác nhận cách chạy và cách tính, còn chất lượng được đo bởi các bảng validation ở trên.
