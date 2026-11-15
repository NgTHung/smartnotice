# Bộ 250 thông báo học vụ

Bộ dữ liệu gồm 190 thông báo HCMUS, 30 UIT và 30 UEH. Thư mục này lưu 100 bản ghi từ [bộ gốc](../hcmus-focused-100/README.md) và 150 thông báo HCMUS bổ sung. Mỗi thông báo có URL nguồn, nội dung tiếng Việt đã che mẫu thông tin liên hệ, vị trí câu và ngày đăng trích từ trang nguồn.

## Sử dụng và kiểm tra

Dùng `notices.jsonl` làm đầu vào rà soát và gán nhãn. Kiểm tra toàn bộ tệp chia sẻ bằng lệnh sau từ thư mục gốc repository.

```powershell
uv run python tools/check_notice_dataset.py --snapshot-dir data/catalogs/hcmus-focused-250 --expected-documents 250
```

- `sources.jsonl` ghi URL, selector, bằng chứng ngày đăng và mã băm HTML/văn bản.
- `snapshot_index.jsonl` nối mã tài liệu với trường, tiêu đề, URL và các mã băm trước/sau bước che thông tin liên hệ.
- `snapshot_summary.json` ghi số bài theo trường, phiên bản văn bản và trạng thái rà soát.
- `validation.json` ghi kết quả đối chiếu nguồn, kiểm tra tệp chia sẻ và thống kê chất lượng.

Ngày đăng trong `publication_date_candidate` giữ trạng thái ứng viên. `reference_date` chờ nhóm xác minh theo [quy trình thu thập](../../../docs/collection.md). Các cờ chờ rà soát riêng tư và nội dung tiếp tục áp dụng. Xem [báo cáo kiểm chứng](../../../reports/crawler-validation-2026-11-15.md) để biết cách chọn bài và các trường hợp cần chú ý khi gán nhãn.
