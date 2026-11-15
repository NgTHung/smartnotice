# Chuẩn bị mẫu gộp sự kiện

Quy trình này giúp người duyệt xác định hai mục thông báo có nói về cùng một sự kiện hoặc cùng đợt công việc hay không, rồi phân biệt lời nhắc, đầu việc bổ sung và cập nhật thông tin trong nhóm. Mẫu lấy từ dự đoán cần giữ bằng chứng nguồn và trạng thái chưa được con người xác nhận. Đây là bước chuẩn bị cho thử nghiệm gộp sự kiện, không phải kết quả đánh giá chất lượng.

## Xác định đơn vị gộp

Một lần nhắc gồm một ACTION cùng các argument và ngữ cảnh nguồn cần để xác định công việc. Khóa của lần nhắc trong mẫu là `doc_id:action_span_id`, gắn với hash dự đoán và hash văn bản. `event_id` chỉ có ý nghĩa trong annotation của tài liệu tương ứng; không dùng riêng nó làm khóa toàn corpus.

Khi duyệt, phân biệt ba đơn vị:

| Đơn vị | Ý nghĩa |
|---|---|
| Nhóm sự kiện | Một sự kiện hoặc đợt công việc được nhận diện bằng bằng chứng nguồn; có thể chứa nhiều đầu việc, vòng hoặc phiên |
| Đầu việc | Việc sinh viên cần làm trong nhóm, chẳng hạn đăng ký, nộp bài hoặc check-in; giữ riêng thời hạn, phiên và điều kiện áp dụng của từng việc |
| Mục thông báo | Phần nguồn nói về sự kiện hoặc đầu việc đang so sánh; có thể chứa một hoặc nhiều lần nhắc ACTION |

Đăng ký tham gia, tham dự và nộp báo cáo của cùng một đợt chương trình là những đầu việc riêng trong cùng nhóm khi có đủ bằng chứng nhận diện. Với chương trình có nhiều vòng hoặc phiên, giữ dấu hiệu nhận diện từng vòng/phiên và nghĩa vụ tương ứng. Một tên chương trình dùng qua nhiều năm không đủ để gộp các đợt độc lập.

Cùng một chương trình cũng chưa đủ để xác nhận cùng sự kiện. Các chuyên đề có nội dung, lịch tham dự và lựa chọn đăng ký độc lập có thể là các sự kiện riêng, dù thuộc cùng khóa hoặc đợt chương trình. Chỉ dùng `DIFFERENT_SESSION` bên trong một nhóm sau khi đã xác định được danh tính sự kiện chung; không dùng quan hệ cùng chương trình để thay bước xác định đó. Khi người duyệt chọn tách rõ từng chuyên đề, lưu các nhóm riêng và giữ tên chương trình trong bằng chứng nguồn.

Một email có thể chứa nhiều mục thông báo thuộc các nhóm khác nhau. So sánh từng mục cùng ngữ cảnh liên quan, không gán toàn bộ email vào một nhóm chỉ vì một mục khớp. Giữ nguyên Notice nguồn và các khóa lần nhắc; cách phân biệt trên phục vụ duyệt, không thêm trường vào định dạng annotation hoặc đầu ra bản thử nghiệm.

## Ra quyết định cho một cặp

Trả lời hai câu hỏi theo thứ tự, rồi chọn một trong bốn nhãn:

| Câu hỏi | Tiêu chí và cách xử lý |
|---|---|
| Hai mục có cùng sự kiện hoặc cùng đợt công việc không? | Đối chiếu tên hoặc bí danh có căn cứ, đơn vị tổ chức, mã hoặc đường dẫn riêng của đợt, năm/đợt tổ chức và tham chiếu trực tiếp đến thông báo trước. Tên chung như “Hội thảo kỹ năng” hoặc biểu mẫu dùng lại hằng kỳ chỉ có giá trị hỗ trợ. Có bằng chứng cho thấy hai sự kiện hoặc hai đợt độc lập thì chọn `DIFFERENT_EVENT`; thiếu căn cứ hoặc còn mâu thuẫn thì chọn `UNCLEAR`. |
| Trong nhóm đó, quan hệ giữa hai mục là gì? | Nhắc lại cùng việc thì giữ một đầu việc và các lần nhắc. Bổ sung việc khác thì giữ đầu việc riêng trong nhóm. Hai trường hợp này dùng `SAME_EVENT` nếu không sửa thông tin cũ. Nếu sửa thông tin cũ, dùng `UPDATE_OF` cho đúng đầu việc, phiên hoặc trường thông tin bị sửa. |

| Quyết định | Điều kiện | Xử lý đề xuất |
|---|---|---|
| `SAME_EVENT` | Cùng sự kiện hoặc cùng đợt công việc, kể cả khi các email đề cập đến các bước hoặc nhóm người tham gia khác nhau; bằng chứng nhận diện phù hợp; không có thay đổi thông tin cũ cần quản lý phiên bản | Đề xuất cùng nhóm; ghi rõ nhắc lại cùng đầu việc hay bổ sung đầu việc/phiên riêng; giữ mọi lần nhắc |
| `UPDATE_OF` | Nguồn nêu rõ thay đổi, gia hạn, hoãn, hủy hoặc mở lại và nhận diện được sự kiện/đợt cùng phần thông tin tương ứng ở nguồn trước | Đề xuất cùng nhóm; lưu chiều từ bản cập nhật đến bản trước, phạm vi bị sửa và giá trị cũ/mới khi xác định được |
| `DIFFERENT_EVENT` | Có bằng chứng cho thấy đây là hai sự kiện hoặc hai đợt công việc độc lập | Giữ hai nhóm riêng và ghi bằng chứng phân biệt |
| `UNCLEAR` | Thiếu căn cứ nhận diện, ACTION bị cắt, ngữ cảnh không đủ hoặc có mâu thuẫn chưa giải thích được | Chưa gộp; ghi rõ bằng chứng còn thiếu |

Trong `UPDATE_OF`, phía trái là lần nhắc cập nhật, phía phải là lần nhắc trước. Các quyết định còn lại đối xứng. Email cập nhật có thể chỉ nêu giá trị mới, không cần lặp lại giá trị cũ nếu đã nhận diện được bản trước và phần bị sửa. Truy giá trị cũ từ nguồn trước khi có bằng chứng; nếu không xác định được thì ghi rõ thiếu, không suy đoán. Nếu chỉ có thông báo gia hạn mà chưa tìm thấy bản trước, giữ trong danh sách chờ, không tạo một bản trước giả định.

`SAME_EVENT` xác nhận cùng nhóm, không có nghĩa là mọi ACTION trong nhóm cùng một đầu việc. Ghi rõ quan hệ đầu việc trong lý do duyệt cùng bằng chứng nguồn. Nếu một mục vừa sửa hạn đăng ký vừa bổ sung hướng dẫn check-in, ghi cập nhật ở phần đăng ký và đầu việc riêng ở phần check-in; không áp dụng thay đổi cho toàn nhóm.

Đọc nguồn theo thứ tự sau:

1. Xác định công việc và chương trình/vấn đề mà ACTION nói đến. ACTION chung như “đăng ký” hoặc “liên hệ” cần ngữ cảnh bổ sung.
2. Đối chiếu năm học, học kỳ, đợt, số phiên, mã chương trình và đối tượng. Phân biệt phiên trong cùng đợt với lần tổ chức độc lập. Việc thu hẹp người nhận theo trạng thái tham gia không đủ để tách nhóm. Chỉ quy đổi tên viết tắt khi có căn cứ; giữ riêng danh sách sinh viên và danh tính cá nhân.
3. Đối chiếu START, DEADLINE và EVENT_TIME theo đúng vai trò, đầu việc và phiên. Hạn đăng ký khác ngày diễn ra không phải mâu thuẫn; hai DEADLINE của hai đầu việc cũng có thể khác nhau. Ngày gửi email chỉ là thời điểm nguồn, không phải ngày tổ chức hay thứ tự có hiệu lực của mọi thay đổi.
4. Đối chiếu liên kết và tài liệu liên quan. Cổng học vụ, biểu mẫu dùng lại và chữ ký giống nhau chỉ là tín hiệu hỗ trợ. Không dùng placeholder như `[NAME]` hay `[EMAIL]` để nhận diện sự kiện.
5. Tìm phát biểu nhắc lại, gia hạn, thay thế, hoãn, hủy hoặc mở lại. Chỉ đề xuất cập nhật khi xác định được đợt và phần thông tin bị thay đổi, gồm cả lịch, địa điểm hoặc trạng thái. Hai nguồn ghi giá trị khác nhau cho cùng phần thông tin mà thiếu bằng chứng cập nhật thì dùng `UNCLEAR`.

Không gộp chỉ vì độ giống câu chữ cao, cùng chủ đề, cùng ngày hoặc cùng `group_id` của tài liệu. Nguồn khác nhau không tự động có nghĩa là sự kiện khác nhau.

## Xử lý các trường hợp dễ bỏ sót

Các ví dụ dưới đây là tình huống tổng hợp để kiểm tra tiêu chí duyệt, không lấy từ corpus thực.

| Trường hợp | Ví dụ | Cách xử lý |
|---|---|---|
| Khác bước trong cùng quy trình | Email yêu cầu đăng ký cuộc thi, email sau yêu cầu nộp bài vòng sơ loại | Khi xác định được cùng kỳ thi và đợt tổ chức, dùng `SAME_EVENT` ở cấp nhóm; giữ hai đầu việc với hai deadline riêng. |
| Khác đối tượng do trạng thái tham gia | Thư mời toàn khoa, thư nhắc sinh viên chưa hoàn tất đăng ký | Nếu cùng biểu mẫu riêng của đợt, cùng đợt và cùng hạn, có thể dùng `SAME_EVENT` cho lời nhắc cùng đầu việc. Giữ điều kiện người nhận của từng mục, không dùng nhóm để suy mọi sinh viên đều phải thực hiện. |
| Hai ngày có ý nghĩa khác nhau | Đăng ký trước 10/11/2026, hội thảo diễn ra ngày 15/11/2026 | Xác định DEADLINE và EVENT_TIME trước khi so sánh. Chỉ xét mâu thuẫn khi cùng vai trò, đầu việc và phiên; hai mốc khác vai trò không đủ để tách nhóm. |
| Đổi cách gọi hoặc nguồn gửi | Phòng Công tác sinh viên dùng tên tiếng Anh, khoa chuyển tiếp bằng tên viết tắt tiếng Việt | Đối chiếu mã sự kiện, biểu mẫu riêng của đợt, đơn vị tổ chức và ngày diễn ra. Khác tiêu đề hoặc người gửi là bằng chứng yếu; chỉ xác nhận bí danh khi có căn cứ. |
| Lịch, địa điểm hoặc trạng thái thay đổi | Chuyển sang phòng B203, tạm hoãn hoặc mở lại đăng ký | Dùng `UPDATE_OF` khi nhận diện được bản trước và nguồn nói rõ thay đổi, kể cả khi chỉ nêu giá trị mới. Nếu hai nguồn chỉ ghi khác nhau mà không giải thích được, dùng `UNCLEAR`. |
| Một chương trình có nhiều phiên hoặc vòng | Tuần lễ định hướng có ca sáng/chiều; chuỗi kỹ năng có nhiều chuyên đề | Phân biệt các ca của cùng hoạt động với những chuyên đề độc lập. Với cùng hoạt động có bằng chứng nhận diện, giữ nhóm và từng ca; với chuyên đề có nội dung, lịch và lựa chọn tham dự độc lập, giữ nhóm riêng. Khác ngày đơn thuần chưa đủ để tách. |
| Một email chứa nhiều sự kiện | Bản tin có mục học bổng và mục hội thảo; email sau chỉ nhắc hạn học bổng | Chỉ so mục học bổng với lời nhắc tương ứng. Mục hội thảo giữ nhóm riêng khi có bằng chứng là sự kiện độc lập. |

## Kiểm tra chuỗi nhắc và cập nhật

Dùng chuỗi tổng hợp sau làm ca kiểm tra quy trình duyệt. Giả định cả bốn mục có cùng mã hội thảo và biểu mẫu riêng của đợt; thư gia hạn chỉ rõ thay đổi hạn đăng ký của đợt đó.

| Mục thông báo | Nội dung tổng hợp | Quan hệ cần ghi | Kết quả kỳ vọng sau mục này |
|---|---|---|---|
| A: mở đăng ký | Đăng ký hội thảo trước 10/11/2026 | Tạo đầu việc đăng ký trong nhóm hội thảo | Một nhóm, một đầu việc, một thông báo |
| B: nhắc đăng ký | Nhắc sinh viên chưa đăng ký hoàn tất trước 10/11/2026 | `SAME_EVENT` với A; nhắc cùng đầu việc, giữ nguyên hạn | Một nhóm, một đầu việc, hai thông báo |
| C: gia hạn đăng ký | Gia hạn đăng ký hội thảo đến 12/11/2026 | `UPDATE_OF` từ C đến A và ghi phạm vi là DEADLINE của đầu việc đăng ký; giữ B là lời nhắc hạn cũ | Một nhóm, một đầu việc, ba thông báo; lưu hạn cũ 10/11 và hạn mới 12/11 cùng bằng chứng |
| D: hướng dẫn check-in | Người đã đăng ký check-in hội thảo trước 08:00 ngày 15/11/2026 | `SAME_EVENT` ở cấp nhóm; bổ sung đầu việc check-in với thời hạn và điều kiện riêng | Một nhóm, hai đầu việc, bốn thông báo |

Ba mục A, B, C không tạo ba đầu việc đăng ký. Mục D không sửa hạn đăng ký của C. Các số đếm trên là kết quả kỳ vọng của ví dụ, không phải kết quả chạy `group_events` hoặc bằng chứng đánh giá chất lượng.

## Kiểm tra trích xuất trước khi gộp

Đối chiếu ACTION, argument, quan hệ và câu bằng chứng với văn bản đã chuẩn bị theo [quy trình annotation](annotation.md). Văn bản và offsets tuân theo [contract dữ liệu](interface.md).

Một khoảng ngày phải được tách thành hai TIME có vai trò phù hợp. Không coi cả khoảng là DEADLINE. Ngày thiếu năm chỉ được suy từ ngày tham chiếu theo chính sách hiện có và phải giữ cờ suy diễn; biểu thức chưa giải quyết được vẫn để trống. Không suy ngày từ thời điểm tải batch.

Kiểm tra cấu trúc không xác nhận nhãn đúng nghĩa. Nếu ACTION là “gia hạn”, người duyệt cần xác định công việc được gia hạn trước khi so với ACTION “đăng ký” ở bản gốc. Nếu hai đoạn nguồn giống nhau nhưng TIME role khác nhau, ghi lỗi trích xuất riêng; không lấy khác biệt dự đoán làm bằng chứng hai sự kiện khác nhau.

## Dùng gói mẫu cục bộ

Gói mẫu ngày 05/11/2026 nằm tại `data/annotations/event-grouping-pilot-2026-11-05/`, được Git bỏ qua. Nội dung nguồn chỉ nằm trong các file cục bộ này. Chưa có xác nhận kiểm tra riêng tư của con người thì chưa đưa gói lên dịch vụ ngoài hoặc chia sẻ.

| File | Nội dung |
|---|---|
| `README.md` | Cách đọc mẫu, tái tạo và hoàn thành review |
| `sample_events.jsonl` | Các lần nhắc được chọn, spans, argument, câu bằng chứng và provenance |
| `pair_proposals.jsonl` | Đề xuất của trợ lý, lý do và trích dẫn bổ sung có offsets; không phải nhãn chuẩn |
| `human_pair_review.jsonl` | Chỉ chứa khóa cặp và các ô quyết định/người duyệt để trống |
| `review_worksheet.md` | Phiếu đọc từng cặp, đề xuất và bằng chứng nguồn |
| `review_tasks.json` | Tập con task gốc, giữ nguyên dự đoán, không có completion giả |
| `sample_notices.jsonl` | Tài liệu đã chuẩn bị tương ứng, giữ nguyên bản ghi nguồn |
| `zero_prediction_tasks.json` | Tài liệu không có sự kiện dự đoán, cần kiểm tra bỏ sót |
| `privacy_review_queue.jsonl` | Hàng chờ riêng tư với mẫu approval chưa được điền |
| `selection.json`, `prepare_sample.py` | Lựa chọn có chủ đích, đề xuất của trợ lý và script tái tạo |
| `run.json`, `checksums.json` | Số lượng, nguồn, hash, phiên bản môi trường và kết quả kiểm tra cấu trúc |

`sample_events.jsonl` và `pair_proposals.jsonl` là định dạng nháp phục vụ review, không thay đổi `Annotation` hoặc `ReviewRecord` và không được nhập như nhãn đã kiểm duyệt. `human_pair_review.jsonl` tách khỏi đề xuất để người duyệt có thể đưa ra quyết định trước khi xem gợi ý. Người đã xem dự đoán không được tính là người gán nhãn độc lập.

Sau khi đọc nguồn và sửa trích xuất trong Label Studio, xuất completion thực và dùng `import-reviewed-labels` theo [quy trình LLM](llm-labeling.md). Nếu sửa ACTION hoặc tách sự kiện, đối chiếu lại các khóa lần nhắc và mọi cặp bị ảnh hưởng. Ghi quyết định cặp thực tế cùng người duyệt, thời điểm có múi giờ, lý do và bằng chứng; không sao chép hàng loạt đề xuất để tạo trạng thái đã duyệt.

## Chuẩn bị thử nghiệm tiếp theo

Chưa dùng đề xuất trong mẫu làm ground truth để tính accuracy hoặc F1. Đây là mẫu chọn có chủ đích để phát hiện lỗi, không đại diện cho tỷ lệ trùng lặp của corpus. Báo riêng lỗi trích xuất và lỗi quyết định gộp.

Giữ cả nguồn, offsets, lịch sử cập nhật và các trường còn mâu thuẫn sau khi gộp. Không xóa tài liệu trùng và không tự chọn hạn muộn nhất làm hạn có hiệu lực. Trước khi thêm thành viên vào một nhóm, kiểm tra với các thành viên hiện có: hai quyết định giống nhau qua một sự kiện trung gian chưa đủ để gộp cả chuỗi khi có mâu thuẫn.

Hàm `group_documents` trong [`split.py`](../src/preprocessing/split.py) phục vụ tránh rò rỉ giữa các tập dữ liệu, không xác nhận danh tính sự kiện. Mẫu được mở để thiết kế tiêu chí là dữ liệu phát triển; chưa chia lại để gọi là tập kiểm tra độc lập. Khi huấn luyện hoặc đánh giá, giữ các tài liệu liên quan trong cùng nhóm, không đưa web holdout vào huấn luyện và tuân theo [quy trình đánh giá](evaluation.md).

## Chạy bản thử nghiệm trên dự đoán

`group_events` trong [`grouping.py`](../src/labeling/grouping.py) tạo nhóm phẳng từ các lần nhắc ACTION, không biểu diễn đầu việc hoặc phiên bên trong nhóm. Quy tắc `event-grouping-prototype-v1` có thể đề xuất `DIFFERENT_EVENT` chỉ vì khác loại hành động, nên không thực hiện đầy đủ tiêu chí duyệt hai câu hỏi ở trên. Người duyệt cần kiểm tra lại các cặp khác bước trong cùng quy trình; không diễn giải số nhóm đầu ra thành số sự kiện hoặc số đầu việc đã xác nhận.

Lệnh nằm trong [README](../README.md). Giá trị mặc định đọc `notices.compat.jsonl` và `tasks.json` tại `data/annotations/drive-auto-label-2026-11-04/`, rồi ghi vào `data/processed/event-grouping-prototype-2026-11-05/`. Có thể chọn đầu vào bằng `--notices`, `--predictions` và đường dẫn đầu ra mới bằng `--output-dir`. Xem các trường trong [contract](interface.md#exchange-event-grouping-proposals).

Quy tắc `event-grouping-prototype-v1` so tất cả cặp lần nhắc. Nó tìm cặp ứng viên bằng độ giao/chung của tập từ trong câu bằng chứng sau khi bỏ liên kết, placeholder và một danh sách từ chung cố định. Mặc định yêu cầu ít nhất ba từ có thông tin chung và Jaccard ít nhất 0,8; có thể ghi đè bằng `--min-shared-tokens` và `--similarity`. Các giá trị này là tham số khởi đầu được ghi lại, chưa được tối ưu bằng nhãn mẫu.

Một cặp chỉ được đề xuất gộp tự động khi câu bằng chứng và ACTION chuẩn hóa trùng nhau, ACTION còn ít nhất hai từ có thông tin và có mốc ngày đầy đủ hoặc kỳ học khớp. Quy tắc kiểm tra loại hành động, kỳ học, vai trò thời gian và khoảng ngày chưa tách trước khi gộp. Không tự diễn giải mã năm học viết tắt, suy năm còn thiếu hoặc chọn một giá trị khi cùng vai trò có nhiều ngày. Hai lần nhắc khác nhau trong cùng tài liệu được để người duyệt xử lý. Khi thêm một thành viên vào nhóm, mọi cặp giữa các thành viên phải có đề xuất `SAME_EVENT`.

`UPDATE_CANDIDATE` biểu thị có dấu hiệu cập nhật cần xác định mục tiêu và chiều; chưa phải quyết định `UPDATE_OF` của người duyệt. Mọi giá trị gốc được giữ nguyên. Do yêu cầu bằng chứng trùng khá chặt, bản thử nghiệm có thể bỏ sót các cách diễn đạt khác nhau của cùng sự kiện, thông báo gia hạn ít giống bản gốc và thông tin nhận diện nằm ngoài các câu được mô hình chọn. Cũng có thể gộp nhầm khi hai sự kiện khác nhau dùng cùng đoạn nguồn và cùng mốc ngày; mọi nhóm đầu ra vẫn cần review.

Mở `review_groups.md` để đọc các nhóm có nhiều thành viên, rồi kiểm tra `events.jsonl` và `pair_decisions.jsonl` để truy vết nguồn và lý do. Không dùng số nhóm làm độ chính xác. Thời gian chạy chỉ mô tả lần chạy có cấu hình trong `run.json`; chưa có tối ưu hay so sánh hiệu năng.

## Chạy đề xuất gom nhóm tự động

Dùng lệnh `tools/run_automatic_grouping.py` trong [README](../README.md) để nối tìm cặp ứng viên, ra quyết định, dựng nhóm và xuất trang HTML trong một lượt. Đầu vào là Notice và Annotation đã lưu; mỗi ACTION cùng bằng chứng liên quan là một mục được so sánh. Các hoạt động tham dự vẫn đi vào quy trình khi có event trong annotation, không cần thêm nhãn span `EVENT`. Lệnh không đọc hộp thư hoặc gọi nhà cung cấp mô hình.

Bản quy tắc dùng mã sự kiện, tên trong ACTION hoặc tiêu đề có cấu trúc, kỳ/đợt, mốc ngày và đường dẫn trong bằng chứng. Tên chung, một URL dùng lại hoặc nội dung giống nhau chỉ giúp tìm ứng viên. Chỉ đề xuất cùng nhóm khi có căn cứ nhận diện đủ theo [contract](interface.md#propose-and-assemble-groups-automatically). Việc khác bước, khác ca và nghĩa vụ có điều kiện được giữ riêng; các hạn khác vai trò hoặc khác đầu việc không tự tạo mâu thuẫn.

Chỉ đề xuất cập nhật thời gian khi nhận diện được sự kiện, đầu việc, phía nêu thay đổi và giá trị mới có annotation hỗ trợ. Không chọn bản mới chỉ dựa vào thời điểm gửi. Các thay đổi địa điểm/trạng thái, nhiều phiên bản cập nhật chưa rõ chiều hoặc thiếu căn cứ được để `UNCLEAR`. Bộ dựng nhóm kiểm tra cả những cặp bắc cầu chưa được bước tìm ứng viên chọn; giữ yêu cầu duyệt cho mọi nhóm.

Mở `index.html` để duyệt nguồn và `pair_proposals.jsonl` để xem căn cứ tìm cặp, lý do quyết định và xuất xứ quy tắc. Nếu có bản tham chiếu cùng snapshot, thêm `--reference-assembly` để tạo `comparison.md` và `comparison.json`. Bản tham chiếu chỉ dùng sau dự đoán. Bảng đối chiếu chỉ xét các cặp có quyết định tường minh; nhóm đơn hoặc xác nhận đồng ý nhóm không tự tạo nhãn phủ định cho mọi cặp còn lại.

Giữ kết quả tự động trong thư mục mới, tách khỏi ledger người dùng. Không kế thừa xác nhận cũ chỉ vì một nhóm tự động có cùng thành viên. Dùng các chỗ thiếu ứng viên, sai quan hệ đầu việc hoặc chưa nhận diện được cập nhật để xây ca kiểm thử tổng hợp và lập lượt duyệt kế tiếp. Đối chiếu trên mẫu đã tham gia phát triển không phải đánh giá độc lập; không báo accuracy/F1 từ đó. Lưu cấu hình và hashes cho từng lượt, không điều chỉnh ngưỡng trên tập kiểm tra dành riêng.

## Dựng nhóm từ quyết định có tác giả

Sau khi đối chiếu nguồn và sửa trích xuất, lưu quyết định theo `GroupingReview` trong [contract](interface.md#assemble-event-groups-and-tasks). Ghi tác giả thực, thời điểm, hash annotation và bằng chứng cho mỗi cặp. Xác nhận của trợ lý dùng `reviewer_id="ai_assistant"`, `reviewer_kind="ai_assistant"`; không điền thay các ô xác nhận của con người hoặc approvals riêng tư. Các quyết định AI có thể dùng để dựng nhóm đề xuất, với yêu cầu duyệt được giữ nguyên.

Phân biệt quan hệ nhóm, đầu việc và thông báo. Chọn `SAME_TASK` cho cùng việc được nhắc lại hoặc sửa; dùng `DIFFERENT_TASK`, `DIFFERENT_SESSION` hoặc `CONDITIONAL_TASK` khi cần giữ riêng nghĩa vụ. Chỉ ghi `REMINDER` khi nguồn có căn cứ nhắc lại; bản nội dung lặp nhưng không nêu lời nhắc dùng `REPEATED_NOTICE`. Mỗi `UPDATE_OF` cần chỉ rõ giá trị cũ/mới của từng trường và chiều từ bản mới tới bản trước; giá trị cũ chưa biết để trống.

Giữ cả cụm thời gian khi giờ và ngày thuộc cùng một hạn, chẳng hạn “trước 8g00 ngày 29/6/2026”. Với giờ/ngày bị tách qua hai câu, giữ spans đúng nguồn và ghi `TimeBoundaryReview.value_key` khi đã đối chiếu rằng chúng bổ sung cho cùng một mốc. Không ghép văn bản nguồn để tạo span mới. Với khoảng diễn ra hoặc tạm dừng, ghi nhận mốc cuối bằng `boundary="END"` trong đầu ra gộp nhóm. Đây là diễn giải có tác giả trên TIME hiện có, không thêm nhãn END vào Annotation hoặc Label Studio.

Lệnh dựng nhóm nằm trong [README](../README.md). Đọc `review_groups.md` cùng `assembly.json` để kiểm tra nhóm, từng đầu việc/phiên, giá trị đang được giữ và lịch sử thay đổi. Đầu ra có ba loại mâu thuẫn cần xử lý:

| Mâu thuẫn | Cách xử lý của bộ dựng nhóm |
|---|---|
| `group_contradiction` | Một chuỗi cùng nhóm chứa quyết định khác nhóm hoặc chưa rõ; giữ các thành viên thành nhóm đơn |
| `task_contradiction` | Chuỗi cùng đầu việc chứa quyết định tách việc/phiên; giữ nhóm sự kiện nhưng tách các đầu việc |
| `competing_values` | Còn nhiều giá trị thời gian, địa điểm hoặc trạng thái chưa có cập nhật giải quyết; giữ tất cả, không chọn hạn muộn nhất |

Thiếu quyết định cho một cặp không tạo nhãn phủ định. Bộ dựng nhóm giữ mọi lần nhắc đầu vào, kể cả nhóm đơn; nó không tự nhận diện thêm sự kiện, xử lý eligibility hoặc chốt nhóm chính thức. Chỉ đưa phạm vi đã chọn vào file annotation dùng cho gộp; nếu dùng tập con, tạo lại hashes của tập con và ghi rõ những dự đoán chưa được rà soát bị loại khỏi lần dựng nhóm.

Kiểm tra chuỗi mở đăng ký, nhắc và gia hạn cho kết quả một nhóm, một đầu việc, ba thông báo; thêm check-in phải giữ một nhóm và hai đầu việc. Kiểm tra thêm nhiều phiên, nghĩa vụ theo điều kiện, email nhiều sự kiện, cập nhật địa điểm/trạng thái, mâu thuẫn bắc cầu và chuỗi cập nhật quay về giá trị cũ. Các kiểm thử tổng hợp xác minh phần mềm; đánh giá chất lượng cần nhãn và thiết kế đo phù hợp theo [quy trình đánh giá](evaluation.md).

## Áp dụng ghi chú duyệt từ trang HTML

Trang HTML lưu trạng thái và ghi chú nháp trên trình duyệt; nút xuất tạo JSON gắn với `assembly_fingerprint` của đúng bản đã xem. Lưu nguyên file này trong thư mục riêng tư. Những nhóm không có trong file xuất không được tính là đã duyệt; trạng thái `looks_ok` chỉ xác nhận nhận xét ở cấp nhóm, không tự phê duyệt tất cả span, thời gian, eligibility hoặc quyền chia sẻ dữ liệu.

`apply_group_feedback` trong [`group_feedback.py`](../src/labeling/group_feedback.py) kiểm tra fingerprint và nhận phương án xử lý tường minh. Với `suggest_split`, người áp dụng phải cung cấp đầy đủ các phần của nhóm hoặc xác định nội dung bổ sung cần tách. Không đoán các phần từ câu ghi chú. Khi tách một nhóm, thay các cạnh gộp băng qua phần đã tách bằng `DIFFERENT_EVENT` để không giữ lại chuỗi gộp cũ gây mâu thuẫn.

Giữ ghi chú người dùng, thời điểm gốc, hash file và phương án áp dụng trong ledger riêng. Các quyết định cặp được suy ra từ ghi chú có tác giả áp dụng là `ai_assistant`; chúng không trở thành annotation cặp độc lập của con người. Khi bổ sung các mục từ một email nhiều nội dung, kiểm tra source spans, mở rộng tập annotation và gắn lại hashes cho những lần nhắc cũ có nội dung không đổi. Không tách phần lịch nhắc đúng sự kiện chỉ vì email đó còn có một ưu đãi khác.

Khi người dùng chỉ đạo duyệt đồng ý hàng loạt trong hội thoại, lưu nguyên chỉ đạo, tiêu chí chọn nhóm, fingerprint và danh sách ID được áp dụng trong một bản ghi riêng. Thời điểm ghi nhận là lúc áp dụng chỉ đạo, không phải thời điểm quan sát người dùng đọc từng nhóm. Có thể chuyển chỉ đạo thành ghi chú `looks_ok` để hiển thị; không suy ra xác nhận độc lập từng cặp, span hoặc clearance riêng tư. Giữ nguyên bản xuất trình duyệt trước đó.

Khi các nhóm thực chất là những bước của cùng sự kiện, ghi `GroupMergeResolution` với ID của từng nhóm và quan hệ đầu việc. Giữ riêng các bước và mốc thời gian; thay hoặc thêm đầy đủ các cặp băng qua nhóm để tránh còn cạnh `UNCLEAR`/khác sự kiện gây mâu thuẫn. Nếu số thứ tự nhóm và nội dung mô tả không khớp, đối chiếu fingerprint, ID và ACTION trước khi áp dụng. Không dùng vị trí trong danh sách làm định danh bền vững.

Giữ đúng vai trò các mốc trong nguồn: giờ nhận vé là thời gian của việc nhận vé, không phải lịch chiếu hoặc thời hạn sử dụng vé. Chỉ bổ sung bước sử dụng vé hoặc một mốc áp dụng khi nguồn có căn cứ. Khi cần tên chiến dịch để đọc nhóm, dùng nhãn hiển thị có trích dẫn nguồn; tên chương trình không tự tạo thêm nghĩa vụ tham gia của sinh viên.

Dùng `tools/apply_group_review.py` theo lệnh trong [README](../README.md) để dựng lại từ bản đã xem và phương án tường minh. Nhóm mới sau gộp hiển thị cần kiểm tra lại, kèm các ghi chú cũ và lý do xử lý. Nhãn hiển thị chỉ thay tên trên trang, không làm đổi annotation hoặc thêm task.

Xuất lại trang HTML từ kết quả đã dựng, kèm ledger áp dụng góp ý để người duyệt đối chiếu. Trang mặc định cho xem mọi nhóm và các đoạn nguồn liên quan; bật toàn văn khi cần. Các ghi chú bổ sung ở bản mới được lưu theo fingerprint mới, tách khỏi bản đã dùng làm đầu vào.

## Đọc mẫu ngẫu nhiên hien.json

File `data/annotations/assistant-labels-2026-11-05/hien.json` chứa mười tài liệu chọn không hoàn lại từ danh sách 434 ID sắp tăng dần, dùng `random.Random(DEFAULT_SEED)` với seed 42. Lựa chọn được lưu trong `selection.json`. Trợ lý đọc nguồn để tạo nhãn; đây không phải mười annotation độc lập của con người.

File tham chiếu do người dùng cung cấp được giữ nguyên tại `reference/phat.json` trong cùng gói và chỉ dùng làm mẫu cấu trúc. `hien.json` không sao chép danh tính người gán nhãn, project, thời lượng làm việc hay trạng thái ground truth của file tham chiếu. Các nhận xét về ngày mâu thuẫn, khoảng thời gian và cụm từ bị xuống dòng nằm trong `annotation_notes.md`. `assistant_annotations.jsonl` lưu bản canonical với tác giả `ai_assistant`. Không dùng mẫu này để tuyên bố đo chất lượng hoặc độ đồng thuận.

Script cục bộ `create_hien.py` trong gói nhận `--reference` và `--output-dir` để tái tạo vào thư mục mới. Cần giữ các bản ghi nguồn cùng version và dùng uv từ thư mục gốc. Việc dùng mẫu, sửa nhãn và xác nhận riêng tư tiếp tục theo [quy trình annotation](annotation.md).
