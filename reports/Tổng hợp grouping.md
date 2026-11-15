# Tổng hợp công việc trên nhánh grouping, ngày 10/11/2026

Tài liệu tổng hợp phần công việc đã đẩy lên GitHub để nhóm dùng khi báo cáo tiến độ và bàn giao chức năng gom nhóm sự kiện của SmartNotice. Nội dung được đối chiếu với lịch sử Git, mã nguồn và các bản ghi kiểm chứng tại commit `5fa00b3`, gồm bản thử nghiệm gom nhóm, bộ dựng nhóm sự kiện và đầu việc, cùng quy trình xem nguồn và áp dụng góp ý.

## 1. Phạm vi commit đã xác minh

Tên nhánh thực tế trên GitHub là `gouping`. Ngày 10/11/2026, lệnh `git ls-remote` xác nhận đầu nhánh là `5fa00b3f50776ca3e0bd2e8181742494a61e7016`; nhánh cục bộ đang ở cùng commit.

Phần bổ sung sau mốc `clean-data` (`b2056e5`) gồm ba commit dưới đây. Cả ba ghi tác giả Git là Trần Minh Hiển; tác giả commit được phân biệt với tác giả của từng annotation hoặc quyết định duyệt dữ liệu.

| Ngày commit, UTC+07:00 | Commit | Công việc chính |
|---|---|---|
| 06/11/2026 | [`805f3ba`](https://github.com/NgTHung/smartnotice/commit/805f3ba694124a5b209490581c2068b67cc07314) | Bổ sung dependency Label Studio và cập nhật khóa môi trường |
| 06/11/2026 | [`0e85f88`](https://github.com/NgTHung/smartnotice/commit/0e85f88ee629bb0846446dd8eeb88b3f786a3907) | Xây dựng bản thử nghiệm gom nhóm, chuyển đổi dự đoán và tài liệu hướng dẫn duyệt |
| 09/11/2026 | [`5fa00b3`](https://github.com/NgTHung/smartnotice/commit/5fa00b3f50776ca3e0bd2e8181742494a61e7016) | Bổ sung bộ dựng nhóm và đầu việc, lịch sử cập nhật, áp dụng góp ý và trang HTML duyệt cục bộ |

Nhánh còn chứa sáu commit tiền xử lý kế thừa. Phần này đã có trên `main` qua commit squash `704ad62`, tương ứng PR #20. So sánh cây mã nguồn giữa `b2056e5` và `704ad62` không có khác biệt. Vì lịch sử squash dùng commit ID mới, chỉ đếm `origin/main..origin/gouping` sẽ thấy chín commit nhưng không có nghĩa cả chín đều là chức năng mới so với `main`. Mục 5 liệt kê phần kế thừa để giữ đầy đủ lịch sử và tác giả.

## 2. Công việc đã thực hiện

### Chuẩn bị công cụ và dữ liệu đầu vào

- Thêm `label-studio>=1.23.2` vào [pyproject.toml](../pyproject.toml) và cập nhật [uv.lock](../uv.lock).
- Bổ sung `annotation_results` và `import_prediction_tasks` trong [studio.py](../src/labeling/studio.py). Các hàm hỗ trợ xuất spans và quan hệ, đọc dự đoán đã lưu, kiểm tra mã băm nguồn, văn bản, dự đoán và tính hợp lệ của annotation trước khi gom nhóm.
- Giữ nguồn gốc nhãn: dự đoán dùng tác giả `model_prediction`; bản nháp do trợ lý tạo dùng `ai_assistant`. Quá trình chuyển đổi không tạo xác nhận của con người.
- Ghi lại mẫu pilot gồm 34 tài liệu, 33 lần nhắc và 20 cặp để khảo sát các tình huống nhắc lại, cập nhật, khác đợt và chưa rõ. Chuẩn bị thêm `hien.json` từ 10 tài liệu được chọn bằng seed 42, gồm 26 sự kiện và 97 span do trợ lý gán nhãn.

Các gói dữ liệu thực và script chuẩn bị riêng cho mẫu nằm cục bộ, ngoài Git. Commit lưu mã dùng chung, hướng dẫn và báo cáo kiểm chứng. Chi tiết nằm trong [bản ghi pilot](validation-2026-11-05-grouping-pilot.md) và [bản ghi prototype](validation-2026-11-05-grouping-prototype.md).

### Xây dựng bản thử nghiệm gom nhóm bằng quy tắc

[grouping.py](../src/labeling/grouping.py) triển khai `group_events`; [run_event_grouping.py](../tools/run_event_grouping.py) cung cấp lệnh chạy trên các dự đoán đã lưu.

- Dùng độ tương đồng Jaccard, tức tỷ lệ số từ chung trên tổng số từ phân biệt, để chọn cặp ứng viên. Cấu hình mặc định là ngưỡng `0.8` và ít nhất ba từ có thông tin chung.
- Đưa ra bốn loại đề xuất: `SAME_EVENT`, `DIFFERENT_EVENT`, `UNCLEAR` và `UPDATE_CANDIDATE`. Trường hợp cập nhật cần được xác định thêm mục tiêu và chiều cập nhật.
- Chỉ tự đề xuất cùng nhóm khi ACTION và bằng chứng sau chuẩn hóa trùng nhau, có mốc ngày hoặc kỳ học phù hợp và vượt qua kiểm tra mâu thuẫn. Mọi cặp giữa các thành viên được gộp phải có quyết định `SAME_EVENT`.
- Giữ toàn bộ lần nhắc và nhóm đơn, kèm nguồn, offsets, lý do quyết định và tham số chạy. Đầu ra gồm `events.jsonl`, `groups.jsonl`, `pair_decisions.jsonl`, phiếu đọc nhóm và metadata tái tạo.

Bản thử nghiệm tạo nhóm phẳng và có thể tách hai hành động khác loại dù chúng thuộc cùng một sự kiện. Vì vậy, phần tiếp theo bổ sung cấu trúc sự kiện và đầu việc riêng, sử dụng quyết định đã được cung cấp. Giới hạn này được ghi trong [quy trình gom nhóm](../docs/event-grouping.md).

### Hoàn thiện tiêu chí và rà soát mẫu phát triển

Tài liệu hướng dẫn phân biệt nhóm sự kiện, đầu việc và mục thông báo. Một sự kiện có thể có việc đăng ký, tham dự và nộp báo cáo với thời hạn riêng; một email cũng có thể chứa nhiều sự kiện độc lập.

Lượt rà soát ngày 06/11 ghi lại việc sửa ACTION bị cắt, tách mốc thời gian, điều chỉnh vai trò thời gian và gắn hạn gia hạn về đúng đầu việc. Bản nháp sau sửa có 170 sự kiện trong 34 tài liệu; 136 sự kiện lân cận được giữ nguyên, ngoài phạm vi rà soát nghĩa. Có 38 cờ kiểm tra riêng tư trên 17 tài liệu, là các vị trí cần con người xem xét.

Các đề xuất cặp và sửa trích xuất ở lượt này có tác giả AI. Nguồn, dự đoán gốc và các ô xác nhận của con người được giữ riêng. Xem [bản ghi rà soát mẫu](validation-2026-11-06-grouping-review.md).

### Dựng nhóm sự kiện, đầu việc và lịch sử cập nhật

[event_groups.py](../src/labeling/event_groups.py), [schemas.py](../src/schemas.py) và [build_event_groups.py](../tools/build_event_groups.py) bổ sung bộ dựng nhóm từ các quyết định cặp có tác giả và bằng chứng nguồn.

- Biểu diễn quan hệ cùng sự kiện, cập nhật, khác sự kiện hoặc chưa rõ. Trong một nhóm, giữ riêng cùng đầu việc, khác đầu việc, khác phiên và nghĩa vụ theo điều kiện.
- Kiểm tra mã băm của nguồn và annotation, đoạn trích và offsets trước khi dựng nhóm; từ chối tham chiếu cũ, bản ghi trùng và vòng cập nhật.
- Lưu cập nhật theo chiều từ bản mới đến bản trước, giới hạn trong đúng đầu việc. Giữ giá trị cũ, giá trị mới và liên kết thay thế để truy vết.
- Ghi nhận mốc cuối khoảng thời gian bằng `END` ở tầng gom nhóm, giữ nguyên bộ nhãn thời gian của Annotation.
- Xuất ba loại mâu thuẫn: `group_contradiction`, `task_contradiction` và `competing_values`. Các giá trị chưa giải quyết được được giữ lại để duyệt; bộ dựng nhóm không tự chọn hạn muộn nhất.
- Tạo `assembly.json`, `groups.jsonl`, `conflicts.jsonl`, phiếu đọc và metadata. Mỗi lần nhắc thuộc đúng một nhóm và một đầu việc hoặc phiên.

Bộ dựng nhóm xử lý các quyết định đầu vào, không tự phân loại những cặp chưa được cung cấp. [Contract dữ liệu](../docs/interface.md) và [bản ghi dựng nhóm](validation-2026-11-06-grouping-assembly.md) mô tả định dạng và lần chạy.

### Tạo trang duyệt nguồn và áp dụng góp ý

[group_viewer.py](../src/labeling/group_viewer.py), [render_group_review.py](../tools/render_group_review.py) và [template HTML](../tools/templates/group_review.html.template) tạo trang xem cục bộ. Trang cho phép đọc email nguồn, xem đầu việc và thời gian, đối chiếu lý do và bằng chứng, ghi trạng thái duyệt và xuất ghi chú JSON.

[group_feedback.py](../src/labeling/group_feedback.py) kiểm tra `assembly_fingerprint`, là mã băm xác định đúng bản kết quả người dùng đã xem, trước khi áp dụng góp ý. Yêu cầu tách nhóm cần phương án tường minh; phần mềm giữ ghi chú gốc, thời điểm, hash file và nhật ký áp dụng. Khi tách, các quyết định gộp băng qua phần đã tách được thay tương ứng để tránh giữ chuỗi liên kết cũ.

Lượt áp dụng ngày 09/11 xử lý 10 ghi chú, gồm tám `looks_ok` và hai `suggest_split`, cùng các chỉ dẫn làm rõ. Kết quả tách các chuyên đề độc lập, giữ riêng các mục khác sự kiện trong cùng email và bảo toàn hai cập nhật hạn. Một lượt tiếp theo ghi nhận chỉ đạo đồng ý 13 nhóm có đúng một email nguồn; tiêu chí này gồm 12 nhóm một lần nhắc và một nhóm có hai lần nhắc trong cùng email.

Xác nhận ở cấp nhóm được lưu riêng với quyết định cặp do trợ lý suy ra. Trang HTML đã nhúng dữ liệu, bản lưu trình duyệt và ghi chú xuất được loại khỏi Git; template nguồn được lưu để tái tạo. Xem [bản ghi áp dụng góp ý](validation-2026-11-09-group-feedback.md) và [bản ghi xác nhận nhóm đơn](validation-2026-11-09-singleton-approval.md).

## 3. Kết quả đã được ghi nhận

Các số dưới đây lấy từ báo cáo đã nằm trong commit `5fa00b3`. Chúng mô tả khối lượng và đầu ra của từng lần chạy, không phải độ chính xác gom nhóm. Lần lập tài liệu này không chạy lại corpus hoặc bộ kiểm thử.

| Lần chạy | Phạm vi và đầu ra | Bằng chứng |
|---|---|---|
| Prototype ngày 05/11 | 434 tài liệu, 1.630 lần nhắc; xét 1.327.635 cặp, chọn 364 ứng viên; 10 đề xuất cùng sự kiện, 7 khác sự kiện, 347 chưa rõ; tạo 8 nhóm nhiều thành viên và 1.613 nhóm đơn | [Bản ghi prototype](validation-2026-11-05-grouping-prototype.md) |
| Dựng nhóm ngày 06/11 | 33 lần nhắc và 20 quyết định AI; tạo 19 nhóm, 23 đầu việc hoặc phiên; áp dụng 2 cập nhật hạn; không báo mâu thuẫn trong lần chạy | [Bản ghi dựng nhóm](validation-2026-11-06-grouping-assembly.md) |
| Sau góp ý ngày 09/11 | 35 lần nhắc, 22 quyết định cặp; tạo 22 nhóm và 25 đầu việc; giữ 2 cập nhật hạn; không báo mâu thuẫn trong lần chạy | [Bản ghi góp ý](validation-2026-11-09-group-feedback.md) |
| Ghi nhận đồng ý nhóm một email ngày 09/11 | 13 nhóm hiển thị `looks_ok`; cả 22 nhóm có thông tin góp ý đã áp dụng; thành viên và quyết định cặp không đổi | [Bản ghi xác nhận](validation-2026-11-09-singleton-approval.md) |

Lần prototype dùng toàn batch dự đoán; các lượt dựng nhóm và góp ý dùng tập con phát triển đã chọn. Không so trực tiếp số nhóm giữa hai phạm vi này để kết luận chất lượng tăng hoặc giảm.

## 4. Kiểm thử và khả năng truy vết

Ba mốc kiểm chứng phần mềm đã được ghi nhận lần lượt là 281 ca đạt cho prototype, 302 ca đạt khi có bộ dựng nhóm và 314 ca đạt ở bản quy trình góp ý. Các báo cáo tương ứng ghi Ruff check, Ruff format check và demo ngoại tuyến đạt. Đây là số kiểm thử của toàn repository tại mỗi mốc, không phải số ca mới của riêng chức năng grouping.

Các kiểm tra có ý nghĩa cho phần gom nhóm gồm:

- Chuỗi đăng ký, nhắc, gia hạn và check-in; nhiều đầu việc, nhiều phiên và nghĩa vụ theo điều kiện.
- Cập nhật thời gian, địa điểm và trạng thái; mâu thuẫn qua liên kết trung gian; cập nhật cạnh tranh và chuỗi quay lại giá trị cũ.
- Từ chối mã băm hoặc đoạn trích sai, kiểm tra offsets khớp nguồn và bảo toàn mỗi lần nhắc đúng một lần.
- Tái tạo 13 file nội dung, gồm HTML, khớp từng byte trong lượt áp dụng góp ý ngày 09/11.
- Kiểm tra cú pháp JavaScript và dữ liệu hiển thị; bản ghi ngày 09/11 chưa có kiểm chứng giao diện trực tiếp trong trình duyệt.

Nguồn đầu vào, mã chạy, dependency lock và kết quả được liên kết bằng hash và metadata của từng lần chạy. Mẫu pilot là dữ liệu phát triển được chọn có chủ đích. Số ca kiểm thử đạt, việc không báo mâu thuẫn hoặc góp ý đồng ý nhóm chưa thiết lập accuracy/F1, độ đồng thuận gán nhãn độc lập hay hoàn tất kiểm tra riêng tư.

## 5. Công việc tiền xử lý kế thừa trong lịch sử nhánh

Sáu commit này có trong lịch sử `gouping` và đã được tích hợp vào `main` qua [`704ad62`](https://github.com/NgTHung/smartnotice/commit/704ad62df212034e3ab218959a5f4e286cb8f1c9). Bảng giữ tác giả Git để phân biệt phần đóng góp, thay vì quy toàn bộ lịch sử nhánh cho một người.

| Commit | Ngày | Tác giả Git | Nội dung |
|---|---|---|---|
| `a0a1ad2` | 03/11/2026 | Trần Minh Hiển | Tích hợp làm sạch email vào quy trình chuẩn bị; giữ URL sau che thông tin và bổ sung công cụ rà soát chính sách email cũ |
| `112655a` | 03/11/2026 | Trần Minh Hiển | Sửa quy trình chuẩn bị để bảo toàn nội dung thông báo và xử lý riêng tư |
| `8451263` | 04/11/2026 | NgTHung | Thêm hàng chờ duyệt riêng tư và kiểm soát bàn giao dữ liệu sang bước gán nhãn |
| `995ae80` | 04/11/2026 | NgTHung | Sửa che tên sinh viên, cán bộ và giữ văn bản dễ đọc; bổ sung kiểm tra consent, offsets và metadata chia tập |
| `23df942` | 04/11/2026 | NgTHung | Ghi nhận kiểm chứng tiền xử lý trên dữ liệu chạy thử cục bộ |
| `b2056e5` | 04/11/2026 | NgTHung | Định danh đầu vào, đầu ra, commit và hash của lần chạy tiền xử lý |

## 6. Ranh giới của bản tổng hợp

Tại thời điểm lập tài liệu, workspace có các thay đổi chưa commit sau `5fa00b3`, gồm module `automatic_grouping.py`, các công cụ `run_automatic_grouping.py`, `apply_group_review.py`, các chỉnh sửa hỗ trợ và báo cáo lượt duyệt ngày 10/11. Những phần này không được tính vào công việc đã đẩy lên nhánh trong bản tổng hợp.

File đang mở trong IDE, `reports/generated/automatic-grouping-2026-11-09-final/conflicts.jsonl`, thuộc đầu ra sinh cục bộ. File này không được dùng làm bằng chứng cho nội dung đã push. Kết quả chốt của phạm vi commit được tổng hợp là mốc 22 nhóm và 25 đầu việc ngày 09/11 ở mục 3.

Phần đã push cung cấp công cụ chuẩn bị, đề xuất, dựng và duyệt nhóm sự kiện cục bộ. Các đầu ra giữ yêu cầu duyệt nguồn và riêng tư. Phạm vi này chưa cung cấp mô hình gom nhóm đã huấn luyện, phép đo chất lượng trên tập kiểm tra độc lập, API ứng dụng hoặc bản triển khai công khai.

Để đối chiếu lại đúng phạm vi ba commit, chạy từ thư mục gốc:

```powershell
git log --reverse --oneline b2056e5..5fa00b3
git diff --stat b2056e5 5fa00b3
git show 5fa00b3:reports/validation-2026-11-09-singleton-approval.md
```

Các liên kết file tương đối mở bản trong workspace hiện tại. Khi cần kiểm tra nội dung tại thời điểm đã push, dùng `git show 5fa00b3:<đường-dẫn-file>` để tránh lẫn với các chỉnh sửa cục bộ về sau.
