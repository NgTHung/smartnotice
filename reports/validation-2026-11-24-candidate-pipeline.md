# Kiểm chứng pipeline lọc ứng viên span, 24/11/2026

Lần chạy kiểm tra đường đi từ văn bản đã chuẩn bị đến dự đoán của Logistic Regression và Random Forest. Cả hai mô hình dùng chung tập ứng viên và biểu diễn feature cho phép so sánh chính. Đơn vị dự đoán là một vị trí span kèm nhãn đề xuất.

Fixture gồm 6 thông báo tự tạo, chia thành 3 train, 1 validation, 1 test và 1 domain test. Train tạo 18 mẫu dương và 89 mẫu âm. GroupKFold hoàn tất trong train. Pipeline lưu 6 cấu hình gồm rule thuần, hai bộ lọc với feature kết hợp và ba cấu hình Logistic Regression để phân tích feature. Các checkpoint nạp lại được cho test, domain test và suy luận trên notice có sẵn. Các con số này kiểm tra phần mềm với các mẫu cố ý đơn giản.

Môi trường dùng Python 3.12.13 trên macOS arm64, scikit-learn 1.9.1 và seed mô hình 42. Báo cáo JSON của lệnh train lưu cấu hình, hash mã, hash dữ liệu, hash dependency lock, ngưỡng và thời gian. Báo cáo held-out lưu thêm hash checkpoint. Tài liệu sử dụng quy trình trong [README](../README.md#train-span-candidate-filters) và cách tính chỉ số trong [quy trình đánh giá](../docs/evaluation.md#compare-span-candidate-filters).

Lệnh train được thử với snapshot `20261113-official-split` và sổ `SpanReview` rỗng. Lệnh trả lỗi thiếu bản ghi hoàn tất ở train và dừng trước khi ghi kết quả. Nghiên cứu trên corpus thật cần người rà xác nhận đủ sáu nhãn cho train và validation. Test và domain test cần annotation độc lập hoặc đã phân xử.

310 kiểm thử đạt với nhóm dependency `ml`. Ruff, kiểm tra định dạng, kiểm tra lock, kiểm tra diff và demo ngoại tuyến đều đạt. Wheel chứa điểm vào CLI. Source archive loại trừ `reports/generated/` và dữ liệu ở `data/interim/`.
