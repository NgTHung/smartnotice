# Trích xuất sự kiện theo từng công việc trên Kaggle với SmartNotice v3.3

Thí nghiệm đánh giá khả năng tìm bằng chứng và nối đối số khi một thông báo có nhiều công việc. Bộ trích xuất thứ nhất dự đoán sáu kiểu cụm. Bộ thứ hai nhận một công việc cụ thể cùng từng cửa sổ văn bản và có thể tìm thêm đối số ngoài danh sách cụm của bộ thứ nhất. [Mã huấn luyện](../../../tools/run_action_conditioned.py), [phiên bản Kaggle riêng tư](https://www.kaggle.com/code/phattruongpo344/smartnotice-action-conditioned-v33-1123/version/2).

## Dữ liệu và cách chấm

Gói thí nghiệm giữ nguyên phân bổ từ bản Drive v3.3, với 403 thông báo train và 93 thông báo validation. Kaggle nhận văn bản của 126 thông báo test thường để suy luận. Mã chấm cục bộ đối chiếu dự đoán với chú giải lịch sử có máy hỗ trợ sau khi đã chọn checkpoint và ngưỡng trên validation. Đây là tập test đã sử dụng trong các phép so sánh trước. Tập web chuyển miền gồm 62 thông báo nằm ngoài thí nghiệm này. Bản ghi gói dữ liệu và mã chạy (`reports/generated/kaggle-action-v33-20261123/submission.json`), [mã chấm](../../../tools/score_action_conditioned.py).

Hai bộ trích xuất dùng BamiBERT và hàm điểm biaffine, tức là mô hình học tương tác giữa biểu diễn token đầu và token cuối cho từng kiểu hoặc vai trò. Cửa sổ có tối đa 192 token nội dung, bước dịch 128 token và cụm rộng tối đa 64 token. Hai biên phải nằm trong cùng câu. Công việc và đối số có thể nằm ở hai câu hay hai cửa sổ khác nhau. Trên validation, các giới hạn này cho phép biểu diễn 1.037/1.078 cụm và 855/873 liên kết khi dùng công việc chú giải. Kiểm tra độ bao phủ (`reports/generated/kaggle-action-v33-20261123/window_audit.json`).

Ở giai đoạn hai, mô hình nhận cụm công việc ở đầu chuỗi và dùng khoảng cách câu tới công việc để phân biệt các mốc trong cùng thông báo. Khi huấn luyện, một phần công việc được rút ngắn thành ví dụ âm. Bộ mã hóa được tinh chỉnh ở cả hai giai đoạn. Mỗi giai đoạn có bốn epoch, batch 8 và seed 42. Trình chấm giữ tối đa 24 cụm cho mỗi kiểu hoặc vai trò trong mỗi cửa sổ trước khi áp ngưỡng. Với cùng một công việc và một khoảng đối số, trình dựng sự kiện bỏ cặp nếu có nhiều vai trò cùng vượt ngưỡng. Cách này giữ đúng hợp đồng mỗi đối số có tối đa một vai trò trong sự kiện.

## Kết quả trích xuất

Lần chạy hoàn tất trên một Tesla T4 sau 555 giây, tính từ đầu script tới khi ghi dự đoán. Bảng 1 so sánh trên cùng 126 thông báo test thường. Chỉ số cụm đòi hỏi khớp vị trí bắt đầu, kết thúc và kiểu. Chỉ số liên kết đòi hỏi khớp cả hai đầu mút có kiểu và vai trò. Sự kiện đúng toàn bộ còn đòi hỏi đầy đủ tập đối số và ngày chuẩn hóa. Cấu hình và ngưỡng (`reports/generated/kaggle-action-v33-20261123/run.json`), [kết quả chấm cục bộ](../results/08-local_scores.json).

| Chỉ số trên test thường | Mẫu thông báo | Cụm theo luật + BamiBERT | BamiBERT theo công việc |
|---|---:|---:|---:|
| F1 cụm có kiểu | 19,54% | 11,11% | 46,11% |
| F1 liên kết | 9,97% | 2,79% | 21,85% |
| Liên kết đúng / dự đoán | 84 / 536 | 50 / 2.435 | 232 / 975 |
| F1 sự kiện đúng toàn bộ | 1,48% | 0,19% | 3,09% |
| Sự kiện đúng / dự đoán | 6 / 343 | 3 / 2.766 | 15 / 502 |
| Ngày tường minh đúng trên 188 mốc | 16 | 7 | 15 |

Bảng 1. Ba hệ thống cùng dùng 1.412 cụm, 1.149 liên kết và 468 sự kiện tham chiếu. Hai phép so sánh có [biên bản pipeline mẫu](drive-v3.3-pipeline-comparison-2026-11-23.md) và [biên bản nối cụm theo luật](rule-spans-bamibert-relations-2026-11-23.md).

Nếu chỉ xét ranh giới, 718/1.412 khoảng tham chiếu khớp chính xác trong 1.639 khoảng dự đoán, tương ứng F1 47,07%. Trong 718 khoảng khớp, 699 khoảng có toàn bộ tập kiểu đúng (97,35%). Theo từng kiểu, F1 là ACTION 39,59%, TIME 49,14%, AUDIENCE 54,25%, CONDITION 43,01%, CHANNEL 50,45% và DOCUMENT 44,44%.

Khi cung cấp công việc chú giải trên validation, bộ chọn đối số đạt F1 liên kết 46,21% trước bước loại xung đột vai trò. Khi dùng công việc dự đoán và dựng sự kiện, F1 liên kết validation là 24,97% và F1 sự kiện là 7,81%. Trên test, bộ nhận diện công việc khớp 192/468 công việc. Trong 232 liên kết đúng, 133 liên kết đi qua câu và 16 liên kết dùng đối số bị bỏ sót ở giai đoạn một. Trong 38 liên kết khớp có ngày tường minh, bộ chuẩn hóa trả đúng 15 ngày. Thí nghiệm dùng một seed, đánh giá phần trích xuất và chưa đo mức áp dụng với hồ sơ.

Cả hai checkpoint tải từ Kaggle nạp được trên RTX 3050 Ti. Khi chạy lại năm thông báo validation đầu tiên, toàn bộ 53 cụm của giai đoạn một và 25 liên kết xuất hiện trên cả hai máy. Máy cục bộ phát thêm một liên kết. Bảng 1 dùng tệp dự đoán gốc của Kaggle. Hash checkpoint và kết quả chạy lại (`reports/generated/kaggle-action-v33-20261123/checkpoint_replay.json`).
