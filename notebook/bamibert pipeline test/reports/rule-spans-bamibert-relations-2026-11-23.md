# Cụm theo luật và liên kết bằng BamiBERT trên SmartNotice v3.3

Với cùng các cụm bằng chứng trên 126 thông báo test thường, BamiBERT khớp 50 liên kết, còn cách gắn đối số vào công việc gần nhất khớp 32. Pipeline dùng mẫu thông báo trong lần chạy trước khớp 84 liên kết và đạt F1 cao nhất trong ba phương án. Lần đối chiếu này dùng đúng tập test đã mở ở lần trước cùng nhãn lịch sử có máy hỗ trợ. Chưa có nhãn gold được phân xử độc lập. Nguồn Drive v3.3, [lần chạy pipeline mẫu](drive-v3.3-pipeline-comparison-2026-11-23.md).

## Chọn luật và mô hình quan hệ

Bộ luật dò từ khóa tiếng Việt cho công việc, đối tượng, điều kiện, giấy tờ, kênh thực hiện và dùng biểu thức chính quy cho thời gian. Mọi cụm nằm trong một câu và giữ khoảng ký tự của văn bản nguồn. Phương án bổ sung từ điển khớp chuỗi token đã chuẩn hóa chữ thường và chữ số. Một cụm có kiểu phải xuất hiện trong ít nhất hai thông báo train khác nhau mới vào từ điển.

Thí nghiệm dùng checkpoint BamiBERT LoRA của lần chạy gốc, seed 42 và 403 thông báo train. Phương án huấn luyện lại giữ cố định encoder và biểu diễn cụm, rồi cập nhật đầu phân loại liên kết trong 12 epoch. Mẫu dương là liên kết chú giải có đầu mút biểu diễn được. Mẫu âm gồm cặp đầu mút chú giải không có liên kết và cặp do luật đề xuất. Mỗi cặp được chấm giữa các vai trò hợp lệ theo kiểu đối số và lớp không liên kết. Bảng 1 ghi kết quả chọn theo micro-F1 liên kết trên 93 thông báo validation. Cấu hình, hash và số cặp train từng vai trò (`reports/generated/rule-bami-v33-20261123/selection.json`), [mã thí nghiệm](../../../tools/evaluate_rule_bami.py).

| Cụm đầu vào | Công việc gần nhất | BamiBERT gốc | Huấn luyện lại đầu liên kết |
|---|---:|---:|---:|
| Luật viết tay | 0,98% | 1,15% | 2,15% |
| Luật và từ điển từ train | 1,53% | 0,39% | 2,77% |

Bảng 1. F1 liên kết đúng cả hai đầu mút và vai trò trên 873 liên kết validation. Phương án được chọn dùng từ điển và đầu liên kết huấn luyện lại, với ngưỡng 0,70 cho cả thời gian và các kiểu khác. Kết quả validation (`reports/generated/rule-bami-v33-20261123/select.json`).

## Đối chiếu trên test thường

| Phương án | Liên kết đúng / dự đoán | F1 liên kết | F1 sự kiện đúng toàn bộ | Ngày tường minh đúng |
|---|---:|---:|---:|---:|
| Luật và từ điển, gắn công việc gần nhất | 32 / 3.223 | 1,46% | 0,12% | 2 / 188 |
| Cùng cụm, BamiBERT nối đối số | 50 / 2.435 | 2,79% | 0,19% | 7 / 188 |
| Pipeline mẫu thông báo đã chốt trước đó | 84 / 536 | 9,97% | 1,48% | 16 / 188 |

Bảng 2. Kết quả trên 1.149 liên kết và 468 sự kiện tham chiếu của 126 thông báo thuộc 118 nhóm. Hai hàng đầu chỉ cho phép nối các đầu mút mà checkpoint biểu diễn được. Pipeline BamiBERT dùng luật khớp 3 sự kiện trọn vẹn trên 2.766 sự kiện dự đoán. Chỉ số test theo vai trò và kiểu cụm (`reports/generated/rule-bami-v33-20261123/test.json`).

Bộ luật và từ điển tạo 6.331 cụm, khớp 430/1.412 cụm tham chiếu. Trong 1.149 liên kết tham chiếu, chỉ 118 có cả hai đầu mút đúng kiểu và ranh giới trong tập cụm dự đoán. Sau khi khớp các đầu mút với cửa sổ và giới hạn độ rộng của BamiBERT, còn 92 liên kết có thể thu hồi. Mô hình khớp 50 trong số này. Vì vậy, nếu giữ nguyên cách tạo và biểu diễn cụm, recall liên kết tối đa trên tập này là 8,01%. Phép đo dùng một seed cho đầu liên kết và chỉ đánh giá phần trích xuất sự kiện.
