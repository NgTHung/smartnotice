# Báo cáo SmartNotice

SmartNotice hỗ trợ sinh viên đọc thông báo học vụ bằng cách tách công việc, thời gian và đối tượng áp dụng. Báo cáo giải thích cách xây dựng dữ liệu tiếng Việt, đánh giá hai bài toán và triển khai ứng dụng có câu nguồn để người dùng kiểm tra.

Tài liệu này là khung viết báo cáo. Điền số liệu từ dữ liệu và thí nghiệm đã lưu; dữ liệu tổng hợp trong bản demo chỉ dùng kiểm tra phần mềm.

## 1. Xác định và phân tích vấn đề

Mô tả người dùng, ví dụ thông báo nhiều công việc, các lỗi bỏ sót hạn và tiêu chí lựa chọn phạm vi. Phát biểu riêng bài toán trích xuất sự kiện và suy luận đối tượng áp dụng. Giải thích vai trò của câu bằng chứng và xác nhận từ người dùng.

## 2. Thu thập và chuẩn bị dữ liệu

Liệt kê nguồn, cách chọn mẫu, thời điểm thu thập, số tài liệu theo nguồn và quy trình đồng ý cung cấp email. Mô tả schema, công cụ gán nhãn, thời gian gán thử, tỷ lệ gán đôi, quy trình phân xử và kết quả đồng thuận kèm cỡ mẫu. Dẫn tới phiên bản manifest và dữ liệu đã ẩn danh.

## 3. Tiền xử lý và EDA

Giải thích xử lý MIME, bảng HTML, thư trích dẫn, chữ ký, Unicode, thông tin cá nhân và ngày tham chiếu. Đưa hình về độ dài, số câu, phân bố nhãn/vai trò, khoảng cách đối số và khác biệt email/web. Báo cáo dữ liệu thiếu, nhóm trùng và tác động của các quyết định làm sạch.

## 4. Lựa chọn và huấn luyện mô hình

Trình bày cơ sở lý thuyết, ít nhất ba mô hình phù hợp, đặc trưng, tham số, checkpoint và môi trường chạy. Phân biệt đầu vào văn bản của mô hình với ràng buộc dùng sinh nhãn. Nêu cách tránh rò rỉ theo chuỗi email, mẫu và cặp sự kiện/hồ sơ.

## 5. Đánh giá và tinh chỉnh

Điền kết quả từ giao thức đánh giá trong `docs/evaluation.md`. Ghi số mẫu, seed, trung bình và độ lệch chuẩn. Phân tích ma trận nhầm lẫn, loại trừ, đối tượng ngầm định, ngày suy ra và lỗi lan truyền. So sánh liên miền trên cùng tập web được giữ riêng. Không suy diễn chất lượng mô hình từ số kiểm thử phần mềm.

## 6. Giao diện ứng dụng

Mô tả luồng nhập văn bản/.eml/URL, câu nguồn, độ tin cậy, sửa hoặc bỏ dự đoán và xuất lịch. Trình bày API mô hình và cách bảo đảm nội dung, hồ sơ không được lưu sau phiên. Đưa ảnh chụp từ ứng dụng đã chạy.

## 7. Triển khai và demo

Ghi nền tảng cloud, URL công khai, phiên bản mô hình, cấu hình phục vụ và cách kiểm tra luồng người dùng. Mô tả giới hạn được quan sát và hướng cải tiến dựa trên lỗi thực tế.

## Tài liệu tham khảo và phụ lục

Trích dẫn nguồn dữ liệu, mô hình và thư viện được sử dụng. Kèm schema, hướng dẫn tái lập, ví dụ đã kiểm tra quyền riêng tư, đường dẫn mã nguồn, trọng số, slide và bảng phân công có thông tin do nhóm cung cấp.
