# Kế hoạch kiểm tra LM, context window và preprocessing, ngày 10/11/2026

Task này xác định dữ liệu SmartNotice có còn đủ nội dung để đưa vào BamiBERT và ViT5 sau preprocessing hay không. Người thực hiện cần trả lời bằng số đếm theo từng tài liệu: văn bản dài bao nhiêu token, mail nào vượt giới hạn, URL nào bị cắt và thông tin học vụ nào bị preprocessing làm sai. Đây là kế hoạch triển khai; chưa có kết quả đo token hay kết luận chất lượng corpus từ task này.

Người dùng xác nhận BamiBERT dùng giới hạn 2.048 token, ViT5 dùng 1.024 token, và cần kiểm tra cả email bị cắt lẫn URL bị mất. Hai giới hạn này là cấu hình đầu vào của phép kiểm tra. Cần cố định checkpoint/revision và kiểm chứng cách tokenizer thêm token đặc biệt trước khi đo.

## 1. Chốt câu hỏi và phạm vi

| Câu hỏi cần trả lời | Đầu ra bắt buộc |
|---|---|
| Hai LM và tokenizer có đúng với proposal không? | Model ID/revision, tokenizer, nguồn chính thức, giới hạn và kết quả smoke test |
| Phân bố độ dài là gì? | Min, P50, P75, P90, P95, P99, max theo model, nguồn và split |
| Có bao nhiêu mail không vừa context? | Số/tỷ lệ vượt giới hạn, danh sách `doc_id`, token bị bỏ và cách xử lý |
| Có bao nhiêu URL bị mất? | Số URL còn nguyên, bị cắt một phần, bị bỏ toàn bộ; tách nguyên nhân preprocessing/context |
| Việc cắt có làm mất thông tin sự kiện không? | Mức giữ ACTION, TIME/DEADLINE, AUDIENCE, CONDITION và quan hệ ACTION–đối số trên phần có nhãn hợp lệ |
| Văn bản còn ký tự bất thường hoặc bị làm sai ở đâu? | Danh sách phát hiện theo vị trí, nguyên nhân, mức ảnh hưởng và kết quả người duyệt |
| Có nên cắt, chia cửa sổ hay giữ toàn văn? | Bảng so sánh độ bao phủ và chi phí; đề xuất cấu hình dựa trên train/validation |

Phạm vi chính là email. Chạy cùng phép kiểm tra cho web và báo cáo thành nhóm riêng vì proposal dùng cả hai nguồn. Không gộp số liệu email/web thành một tỷ lệ duy nhất rồi dùng để kết luận cho mail.

Task không gồm huấn luyện đầy đủ, xây API/web hay đổi model. Smoke test chỉ xác nhận tokenizer/model nhận được đầu vào và trả đầu ra đúng kiểu. Base checkpoint chạy được không chứng minh đã trích xuất đúng sự kiện SmartNotice.

## 2. Căn cứ đã kiểm tra

### Proposal và nguồn model

Proposal người dùng đính kèm có 6 trang PDF. Mục 3.1 yêu cầu giữ văn bản, câu nguồn và ngày tham chiếu; mục 3.2 đề xuất BamiBERT cho trích xuất theo cụm và NLI, ViT5 cho sinh bản ghi có cấu trúc. Vì vậy, phép kiểm tra cần đo cả độ dài tài liệu lẫn khả năng giữ hành động và đối số cùng ngữ cảnh.

- [BamiBERT model card](https://huggingface.co/Qualcomm-AI-Research/BamiBERT) mô tả context tối đa 2.048 token và đầu vào không cần tách từ bên ngoài. Model ID dùng để xác nhận với nhóm là `Qualcomm-AI-Research/BamiBERT`.
- [BamiBERT config](https://huggingface.co/Qualcomm-AI-Research/BamiBERT/raw/main/config.json) có `max_position_embeddings=2050`. Không lấy số này làm ngân sách 2.050 token: phải đối chiếu cách đánh chỉ số vị trí và token đặc biệt của implementation.
- [Repository ViT5](https://github.com/vietai/ViT5) công bố checkpoint ViT5 Base/Large 1024; nhóm cần chốt chính xác dùng base hay large và revision nào. Giữ mức 1.024 đã xác nhận để đo đầu vào encoder.
- [Tokenizer API](https://huggingface.co/docs/transformers/en/main_classes/tokenizer) phân biệt token đặc biệt, truncation, padding và ánh xạ token–ký tự. Một số tokenizer không hỗ trợ offset mapping; giá trị `model_max_length` mặc định rất lớn cũng không phải bằng chứng model nhận được ngần ấy token.

Các đường dẫn `main` có thể thay đổi. Khi triển khai phải lưu revision/hash tài nguyên tokenizer, phiên bản thư viện và ngày tra cứu; không chỉ lưu URL hiện hành.

### Repository hiện có

| Thành phần | Hành vi đã đọc trong code | Việc cần bổ sung trong task |
|---|---|---|
| [MIME parser](../src/parsers/mime.py), [email parser](../src/parsers/email.py) | Decode có fallback/warning; ưu tiên plain text; bỏ attachment, quote và boilerplate theo luật | Kiểm tra chọn MIME có bỏ sót bảng/URL không; truy nguyên lỗi trước khi văn bản bị làm sạch |
| [HTML parser](../src/parsers/html.py) | Chuyển bảng thành văn bản có ngữ cảnh cột | Đối chiếu hàng/cột, deadline và URL với nội dung nguồn |
| [Text preprocessing](../src/preprocessing/text.py) | NFC, xử lý whitespace/control, bỏ một số emoji, redact rồi tách câu | Audit ký tự còn sót, mất dấu, dính từ, mất thông tin và tính ổn định offset |
| [Preparation pipeline](../src/preprocessing/pipeline.py) | Tạo Notice, hash, câu và URL trong `attachments` | Giữ nguyên baseline, tạo kết quả audit riêng |
| [Quality summary](../src/quality.py) | Đếm corpus, câu, ngày thiếu, non-BMP, split leakage | Chưa có thống kê tokenizer của BamiBERT/ViT5 và số URL/quan hệ bị cắt |
| [LLM labeling](../src/labeling/llm.py) | Prompt có schema và danh sách câu kèm metadata | Không dùng độ dài prompt này thay cho input BamiBERT/ViT5 nếu hai model nhận định dạng khác |
| [EDA notebook](../notebooks/02_eda.ipynb) | Có độ dài ký tự và số câu | Bổ sung bảng/biểu đồ token bằng hàm dùng chung |

[Data contract](interface.md) định nghĩa `attachments` là URL còn trong prepared text, không phải tệp đính kèm MIME. Offset chuẩn là Python Unicode code point, zero-based và end-exclusive. Mọi kiểm tra phải bám theo contract này.

### Drive có nhiều phiên bản

Đã xem danh sách tệp/thư mục và README của các bản sau, chưa audit toàn bộ nội dung corpus:

- [preprocess-run-2026-11-04](https://drive.google.com/drive/folders/1IbWQaCvKeMIV_9lXZq_ZF5K9ghXsCxwM): có raw, interim, processed và reports.
- [labeled](https://drive.google.com/drive/folders/1UGPZOzh5kIs1dLdRK2bEzrT4zcOwIWCU): có notices tương thích, prediction tasks, manifest và run metadata.
- [updated_label](https://drive.google.com/drive/folders/1_AvZwswDV6hACWYiLdRHJ9nf5LSy8KFB): có email/web notices, bản review, annotation và thư mục `relabel_all_v4`.
- [README bản review](https://drive.google.com/file/d/1ruUPz1EUGcIhKTA15hbuH4yckWKkA0B3/view): ghi nhận phạm vi 434 email, 100 web, 29 annotation người đạt kiểm tra cấu trúc và 21 cần xử lý. Đây là số liệu do bản review ghi lại, chưa được task này đếm lại và không đồng nghĩa nhãn chuẩn đã adjudicate.

Không chọn corpus chỉ vì tên thư mục có chữ `updated` hoặc `v4`. Chốt snapshot bằng hash, nguồn tạo và text mà nhãn thực sự tham chiếu. Gợi ý máy, bản sửa bằng model và annotation người phải giữ nguồn gốc riêng.

## 3. Gói A: Cố định dữ liệu và cấu hình model

Thời lượng dự kiến: 0,5 ngày công. Phụ thuộc: nhóm xác định bản dữ liệu dùng cho training và checkpoint ViT5 cụ thể.

1. Lập danh mục tệp cần dùng: raw/manifest, prepared notices, splits, nhãn người hợp lệ, prediction và báo cáo lỗi lịch sử. Không cần tải mọi bản nhãn vào một tập hợp.
2. Sao chép snapshot cần thiết vào vùng private bị Git bỏ qua. Tính SHA-256 từng tệp, số dòng và số `doc_id` duy nhất. Kiểm tra trùng ID, trùng byte, text khác nhau cùng ID và nhãn trỏ sang phiên bản khác.
3. Validate Notice, sentence offsets, URL và nhãn theo contract. Nếu Drive có schema khác, xác định phép chiếu rõ ràng, lưu metadata gốc; không tự bỏ cột hay sửa text để ép validate.
4. Đối soát: số nguồn duy nhất = số Notice thành công + số nguồn thất bại, sau khi giải thích các bản nhập byte trùng. Mọi nguồn vắng mặt cần có lý do riêng, không gọi chung là bị context cắt.
5. Chốt `Qualcomm-AI-Research/BamiBERT` và checkpoint ViT5 nhóm thực sự dùng. Lưu commit/revision, tokenizer class/backend, vocabulary/config hashes, special token IDs, padding/truncation side và yêu cầu normalization.
6. Kiểm tra dependency hiện có trước khi thêm thư viện. Nếu thiếu, dùng `uv add` cho nhóm phù hợp và cập nhật lock; thử tương thích với model, không nâng cấp hàng loạt. Đo token chỉ cần tokenizer, không phải tải tất cả weights.
7. Lưu run config: dataset/split hash, code commit và trạng thái dirty, dependency lock hash, môi trường, seed, model revisions, input template, giới hạn và chính sách cắt.

Điều kiện xong: xác định được tập đang đo, số lượng hợp lệ/bị loại, nhãn đi kèm đúng text, và hai tokenizer có revision cố định. Nếu thiếu raw, vẫn đo token prepared text nhưng đánh dấu chưa thể kết luận lỗi do preprocessing ở giai đoạn trước.

## 4. Gói B: Kiểm chứng tokenizer và cách đóng gói input

Thời lượng dự kiến: 0,5 ngày công. Chỉ dùng fixture tổng hợp khi thử model.

### Kiểm tra chạy được

1. Load tokenizer từ revision cố định; ghi số token đặc biệt cho single sequence và sequence pair bằng API, không tự giả định luôn là 2.
2. Thử tiếng Việt có dấu/NFD, ngày `10/11/2026`, viết tắt `K24`, URL có query, ký hiệu `≤`, placeholder privacy và non-BMP. Kiểm tra tokenizer không lỗi, số `[UNK]` nếu có và mapping ký tự phù hợp.
3. Tạo input tổng hợp sát biên: tổng chiều dài sau đóng gói bằng `C-1`, `C`, `C+1`, trong đó `C` là 2.048 hoặc 1.024. Đếm với truncation tắt; thử riêng đường chạy có cắt để quan sát hành vi.
4. Với BamiBERT, forward ngắn và ở biên được hỗ trợ, kiểm tra shape và không có lỗi vị trí. Với ViT5, thử encoder và sinh ngắn có giới hạn output rõ ràng. Ghi thiết bị, dtype, RAM/VRAM và lỗi nếu có.
5. Kiểm tra dataloader/collator/trainer nếu đã có trong nhánh của nhóm: có `max_length` nhỏ hơn cấu hình đã chốt, cắt lần hai hoặc dùng sai tokenizer không? Nếu chưa có, ghi đó là đầu vào cần bàn giao cho người làm training.

Không cần thử model ở mọi tài liệu để đếm độ dài. Lỗi hết bộ nhớ phải báo riêng với lỗi vượt context; `C+1` được tokenizer tạo ra cũng không chứng minh model hỗ trợ vượt cấu hình.

### Các input cần đo riêng

| Input | Đếm cái gì? | Ngân sách |
|---|---|---|
| BamiBERT trích xuất | Văn bản/cửa sổ đúng template + token đặc biệt | Tổng input tối đa 2.048 |
| BamiBERT NLI | Văn bản sự kiện/evidence + hồ sơ tổng hợp + separators | Tổng cặp tối đa 2.048; profile cũng chiếm chỗ |
| ViT5 trích xuất | Prefix/schema thực sự sử dụng + notice/window + EOS/token đặc biệt | Encoder tối đa 1.024 theo cấu hình nhóm |
| ViT5 đầu ra | Target serialization của event và bằng chứng | Đo riêng theo giới hạn decoder đã chốt |

Không lấy 1.024 trừ output budget cho ViT5 như model decoder-only. Encoder và decoder có ngân sách riêng. Không đưa toàn bộ schema JSON vào input ViT5 nếu thiết kế nhóm không dùng nó. Nếu thiết kế input còn chưa chốt, báo hai kịch bản `text_only` và `proposed_template`, không gọi một kịch bản giả định là cấu hình đang chạy.

Điều kiện xong: có bảng thông số xác minh, input template hash và smoke-test log; tách rõ thông số công bố, cấu hình của nhóm và hành vi quan sát tại máy.

## 5. Gói C: Đo token trên toàn bộ snapshot

Thời lượng dự kiến: 0,5–1 ngày công.

1. Đọc `Notice.text` qua schema. Đếm toàn văn với `truncation=False`, `padding=False`; không lấy kết quả đã cắt để vẽ phân bố độ dài ban đầu.
2. Đếm riêng body không special tokens và input hoàn chỉnh có special tokens/prefix. Số thứ hai quyết định vượt context. Token hóa input hoàn chỉnh một lần: tổng số token từng mảnh cộng lại có thể lệch ở biên nối.
3. Nếu có raw và parser replay được, đếm thêm các mốc trước/sau preprocessing để phát hiện text dài bất thường hoặc giảm quá mạnh. So sánh chỉ dùng để gắn cờ, không xem giảm token là cải thiện chất lượng.
4. Với NLI, đo đúng event/profile pairs sẽ dùng, giữ profile dài nhất trong phạm vi schema; không suy ra mọi cặp đều vừa từ số token của event một mình.
5. Với ViT5 target, đếm những target hợp lệ có sẵn bằng đúng serialization. Ghi nguồn nhãn. Nếu chưa có target chuẩn, đánh dấu chưa đo; không dùng prediction máy làm nhãn chuẩn.
6. Tạo bảng theo model × input variant × email/web × split × nguồn nhãn khi liên quan. Giữ tài liệu synthetic ngoài thống kê nghiên cứu.

Các thống kê cần có:

- Số tài liệu hợp lệ, thất bại và không đo được; min, P50, P75, P90, P95, P99, max.
- Số/tỷ lệ input vượt `C`, bằng `C` và nằm sát biên. Quy tắc sát biên phải được ghi trong config, ví dụ từ 90% ngân sách.
- Histogram/ECDF độ dài theo tokenizer, có đường dọc ở giới hạn thật. Bảng độ bao phủ tại 256, 512, 1.024 và 2.048; chỉ ghi các mốc trong phạm vi model là cấu hình hợp lệ.
- Danh sách tài liệu dài nhất bằng `doc_id` và số đếm, không in nội dung mail hoặc URL chứa định danh.
- Token trên ký tự, `[UNK]` nếu tokenizer có, số placeholder và dòng bảng để tìm trường hợp token hóa phình bất thường; không so số token khác tokenizer như cùng một đơn vị ngôn ngữ.

Định nghĩa chính: `overflow(i,m) = 1` khi tổng input của tài liệu i theo model/template m lớn hơn C; tỷ lệ mail vượt context là tổng overflow của email chia số email đo được. Báo riêng số email bị giữ lại một phần, bị loại hoàn toàn và chưa có chính sách xử lý. Không gọi mọi mail overflow là “mất cả mail”.

Điều kiện xong: mọi Notice hợp lệ có số đo cho từng cấu hình bắt buộc hoặc lý do thiếu rõ ràng; tổng của bảng khớp số tài liệu snapshot.

## 6. Gói D: Đo phần mất do context window

Thời lượng dự kiến: 1 ngày công. Đây là phép mô phỏng đầu vào, chưa phải đánh giá dự đoán.

### Mail và token bị cắt

1. Xác định hành vi baseline: nếu code chưa có truncation, đặt tên `simulated_head_truncation`; không nói corpus đã thật sự bị cắt.
2. Lấy chính tokenizer và cấu hình đóng gói ở gói B, tạo input bị cắt theo giới hạn. Lưu các khoảng ký tự prepared text thực sự còn được model thấy.
3. Lưu `input_tokens_before`, `input_tokens_after`, token nguồn bị bỏ, tỷ lệ token nguồn bị bỏ, số câu giữ nguyên/một phần/mất toàn bộ và các khoảng text còn lại.
4. Thống kê cả tổng token mất trên corpus và mức mất theo tài liệu; không lấy trung bình các tỷ lệ rồi gọi là tỷ lệ token toàn corpus.
5. Không dùng `decode(truncated_ids)` để tự dựng offset chuẩn. Tokenizer có thể thay whitespace/Unicode. Dùng offset mapping đã kiểm chứng hoặc alignment tương đương được kiểm tra bằng fixture; nếu chưa làm được, chỉ báo số token, đánh dấu coverage span/URL là chưa xác định.

### URL bị mất

Đếm theo từng occurrence của URL trong một mail, đồng thời đếm URL duy nhất theo tài liệu để đối chiếu `attachments`. URL lặp hai lần, chỉ còn một lần sau cắt nghĩa là mất một occurrence nhưng chưa mất URL đó hoàn toàn.

Với occurrence có khoảng `[start,end)`, phân loại:

- `retained`: toàn bộ URL nằm trong phần nguồn còn thấy.
- `partial`: chỉ một phần URL còn lại, không đủ dùng như URL gốc.
- `lost`: không có phần URL nào còn lại.

Thống kê số/tỷ lệ `partial` và `lost` trên tổng occurrence, số URL duy nhất không còn occurrence nguyên vẹn, số mail bị ảnh hưởng và số mail mất toàn bộ URL. Mẫu số mail có URL phải được báo bên cạnh mẫu số toàn bộ mail. Với chia nhiều cửa sổ, tính trên hợp các cửa sổ để không đếm cùng URL nhiều lần.

URL trong metadata `attachments` không tự động được model thấy nếu template chỉ gửi `text`. Không coi URL còn trong metadata là đã giữ trong context. Không mở URL thật để kiểm tra khả dụng trong task này; retention của chuỗi không chứng minh đường dẫn còn hoạt động.

### Span, quan hệ và sự kiện bị ảnh hưởng

Chỉ đo khi nhãn resolve chính xác với text hiện hành. Tách số liệu annotation người, nhãn đã adjudicate và prediction; không gộp chúng thành gold.

1. Một span được giữ khi toàn bộ khoảng span nằm trong ít nhất một cửa sổ. Báo giữ/mất một phần/mất toàn bộ theo từng loại nhãn và riêng TIME vai trò DEADLINE.
2. Một quan hệ ACTION–đối số được bao phủ khi tồn tại ít nhất một cửa sổ chứa trọn cả ACTION lẫn đối số. Hai đầu nằm ở hai cửa sổ khác nhau không đủ để mô hình quan hệ trong từng cửa sổ nối được.
3. Một event được bao phủ đầy đủ khi cùng một cửa sổ chứa ACTION và toàn bộ đối số/bằng chứng mà cách training yêu cầu. Báo thêm trường hợp span đều còn nhưng không có một cửa sổ chung. Nếu thiết kế có ghép chéo cửa sổ, cần kiểm chứng bước ghép riêng.
4. Đếm `relations_not_co_visible / valid_relations`, `events_not_fully_visible / valid_events`, và số mail mất ít nhất một deadline/quan hệ. Nêu số tài liệu có nhãn dùng làm mẫu số.
5. Đo khoảng token từ đầu ACTION đến cuối đối số để giải thích trường hợp quan hệ vượt cửa sổ. Đây là phân tích coverage, không phải relation recall hoặc F1 của model.

Nếu chỉ có nhãn cho một phần corpus, vẫn báo mail/token/URL toàn corpus; phần mất sự kiện chỉ kết luận trong subset có nhãn. Không gán “không mất event” cho tài liệu chưa được gán nhãn.

Điều kiện xong: trả lời được riêng từng model có bao nhiêu mail overflow, bao nhiêu mail thật sự bị loại, bao nhiêu URL bị cắt/mất và bao nhiêu quan hệ không còn cùng context.

## 7. Gói E: Audit ký tự và sai lệch preprocessing

Thời lượng dự kiến: 1–1,5 ngày công; cần người của nhóm đọc các ca được gắn cờ.

### Quét tự động toàn corpus

| Nhóm phát hiện | Ví dụ/kiểm tra | Cách hiểu |
|---|---|---|
| Decode/charset | `U+FFFD`, parser warnings, dấu hiệu mojibake như `Ã`, `Â`, `áº` | Gắn cờ; so raw/MIME trước khi kết luận |
| Unicode vô hình | Cc ngoài newline/tab, Cf, BOM giữa chuỗi, bidi, zero-width, soft hyphen, private-use, surrogate | Ghi code point, tên Unicode, vị trí và số lần |
| Tiếng Việt | Không ở NFC, dấu tổ hợp rời, mất dấu hoặc biến dạng sau chuẩn hóa | Dấu tổ hợp không tự động là lỗi; cần đối chiếu normalization |
| HTML/MIME còn sót | Tag, `&nbsp;`, entity lỗi/lặp, boundary, `=C3=`, base64 dài, `[cid:...]` | Cần phân biệt chuỗi được tác giả cố ý viết |
| Cấu trúc bị hỏng | Dính từ, ngắt dòng giữa URL/ngày, tiêu đề cột tách khỏi giá trị, câu bị cắt sau viết tắt | Kiểm tra tác động đến ý nghĩa, không chỉ hình thức |
| Privacy che quá mức | Ngày/hạn/phòng học/khóa hoặc token URL bị che nhầm | Ưu tiên ca làm sai ACTION/TIME/AUDIENCE/CONDITION |
| Loại nội dung nhầm | Inline reply/bottom-post, quote/forward, chữ ký có nội dung nhiệm vụ | So phần tác giả hiện tại với nội dung bị bỏ |
| Sai tầng dữ liệu | `text[start:end] != span.text`, sentence ID cũ, URL metadata không có trong text | Lỗi contract, không đưa âm thầm vào training |
| Bất thường độ dài | Rỗng, lặp nhiều đoạn, token tăng/giảm quá mạnh giữa các mốc | Tín hiệu để rà soát, không tự xóa tài liệu |

Không dùng luật “mọi ký tự ngoài ASCII đều lạ”. Giữ dấu tiếng Việt, ký hiệu toán và ký hiệu BMP có ý nghĩa. Theo contract, một số emoji astral được loại có chủ đích; non-BMP còn lại cần kiểm tra offset thay vì xóa hết. Mẫu phát hiện mojibake chỉ là heuristic.

### Đối chiếu từng giai đoạn

Với ca bị gắn cờ, replay nguồn trong vùng private và ghi dấu vết:

1. Raw bytes bất biến và hash nguồn.
2. MIME decode/HTML render thành text trước khi lọc nội dung, bao gồm lựa chọn plain/HTML và warning. Nếu hàm hiện tại đã normalize sớm, cần quan sát ngay tại điểm decode; không coi output parser là raw text.
3. Phần đóng góp sau tách quote/forward và bỏ boilerplate.
4. Sau normalize và privacy filtering.
5. Prepared text, sentences, URL trước tokenizer.
6. Input còn lại sau chính sách context.

Đối chiếu thêm bản plain và HTML khi mail multipart: plain không rỗng vẫn có thể thiếu URL đích hoặc bảng so với HTML. Ghi đây là nguy cơ do chọn biểu diễn, không quy cho context. Tệp đính kèm không được parser đọc thì ghi là ngoài phạm vi body hiện tại, không tự thu thập nội dung tệp.

Với URL, tách tối thiểu các lý do: quote/boilerplate bị loại theo chính sách, có trong HTML nhưng không trong plain đã chọn, redaction có chủ đích, redaction nghi quá mức, lỗi parse/unfold, và context cắt. Không phục hồi URL chứa định danh chỉ để tăng tỷ lệ retention. Lưu ánh xạ bằng ID/hash trong bảng chia sẻ; chuỗi URL riêng tư chỉ nằm trong worklist private.

Với nội dung học vụ, kiểm tra riêng “trước/sau”, “từ/đến”, “không/trừ”, mốc ngày, giờ, năm, chương trình, cohort và header bảng. Mất một từ phủ định có thể đổi điều kiện áp dụng dù tổng số ký tự giảm rất ít. Không dùng diff ký tự đơn thuần để chứng minh bảo toàn ngữ nghĩa.

### Rà soát của con người

1. Xem tất cả ca lỗi contract, replacement character, deadline/phủ định nghi mất, URL nghi che nhầm và nhóm decode bất thường. Gom ca cùng nguyên nhân để giảm đọc lặp, nhưng vẫn lưu từng `doc_id`.
2. Chọn thêm mẫu ngẫu nhiên phân tầng email/web, ngắn/dài, plain/HTML, có/không URL và có/không warning. Đề xuất khởi đầu 30 email và 20 web chưa bị gắn cờ, lấy tối đa số sẵn có; đây là ngân sách review, không phải mẫu đủ để chứng minh tỷ lệ lỗi nhỏ.
3. Dùng RNG cục bộ từ `DEFAULT_SEED` trong [split.py](../src/preprocessing/split.py), lưu danh sách ID đã chọn. Ưu tiên train/validation để xây luật; held-out chỉ kiểm tra theo tiêu chí đã đóng băng.
4. Phiếu review gồm `doc_id`, text hash, giai đoạn phát sinh, rule ID, khoảng ký tự, quyết định `expected`/`bug`/`uncertain`, lý do, reviewer và thời điểm thật. Mẫu cảnh báo và mẫu ngẫu nhiên phải báo riêng.
5. Báo số phát hiện được xác nhận, cảnh báo nhầm và chưa quyết định. Nếu review không thấy lỗi, viết “không phát hiện trong n tài liệu đã xem”; không viết “preprocessing không còn lỗi”. Không suy tỷ lệ toàn corpus từ mẫu chủ đích.

Điều kiện xong: mỗi loại cảnh báo có ví dụ tổng hợp giải thích, mỗi lỗi quan trọng có ca nguồn truy vết và người thật xác nhận; ca chưa rõ vẫn nằm trong queue.

## 8. Gói F: So sánh cách xử lý văn bản dài

Thời lượng dự kiến: 0,5–1 ngày công sau khi có số đo. Chỉ phát triển chính sách cần thiết theo lỗi đã tìm thấy.

| Chính sách | Vai trò trong so sánh | Rủi ro cần đo |
|---|---|---|
| Giữ toàn bộ nếu vừa giới hạn | Baseline không mất do context | Vẫn có thể có lỗi preprocessing |
| Lấy đầu văn bản theo token | Baseline mô phỏng đơn giản | Mất deadline/URL/đối số ở cuối |
| Cửa sổ token có overlap | Giữ độ bao phủ ký tự | Cắt giữa câu/URL; quan hệ xa vẫn không cùng cửa sổ |
| Cửa sổ theo câu, đóng gói bằng số token thật | Ứng viên khi cần chia | Câu hoặc hàng bảng quá dài cần fallback; thiếu liên hệ với ACTION xa |

1. Với mỗi model, dùng riêng ngân sách sau token đặc biệt/prefix. Thử overlap hữu hạn trên train/validation, ví dụ 0/64/128 token; đây là lưới thử ban đầu, chưa phải lựa chọn cuối.
2. Giữ `doc_id`, `window_id`, global start/end và mapping local–global. Không nối hai đoạn rời thành một chuỗi rồi giả định offset liên tục.
3. Câu dài hơn ngân sách cần cửa sổ token có mapping chính xác. Nếu URL dài hơn ngân sách, đánh dấu không thể giữ nguyên dưới chính sách đó; không âm thầm cắt URL hoặc làm vòng lặp chia không kết thúc.
4. Bảng cần giữ header liên quan khi chia hàng. Nếu phải lặp header/prefix, tính lại token cho input hoàn chỉnh và ghi provenance của phần lặp.
5. Báo tỷ lệ giữ URL, span, quan hệ, event; số cửa sổ trên tài liệu; tổng token có overlap, hệ số tăng input và latency/RAM nếu có đo thật. Không đánh đồng tổng token với thời gian chạy.
6. Chọn cấu hình trên train/validation theo chi phí và coverage; đóng băng trước đo test/domain_test. Không chọn overlap bằng nhãn test. Nếu cần sửa lỗi corpus ở held-out, tạo version mới, ghi tác động và bàn giao theo [evaluation protocol](evaluation.md).
7. Không bỏ mail dài khỏi test để số liệu đẹp hơn. Nếu chưa hỗ trợ xử lý dài, báo coverage/abstention và mẫu số toàn bộ tập.

Điều kiện xong: một khuyến nghị cho từng model, kèm số liệu và giới hạn; không suy ra việc giữ đủ context bảo đảm model dự đoán đúng.

## 9. Tổ chức phần triển khai dự kiến

Đây là các thay đổi được đề xuất cho bước thực hiện, chưa phải file/lệnh đã tồn tại:

- `src/preprocessing/token_audit.py`: đếm token, đóng gói input, ánh xạ coverage và thống kê theo cấu hình. Không để notebook có tokenizer logic riêng.
- `src/preprocessing/text_audit.py`: phát hiện bất thường trên text và trả các khoảng/code point có lý do. Luật privacy/URL tiếp tục ở module đang sở hữu chúng.
- `src/quality.py`: tổng hợp kết quả; CLI chỉ điều phối đọc/ghi và báo số đếm an toàn.
- `src/schemas.py` và [interface.md](interface.md): bổ sung schema cho kết quả audit khi chốt persisted output; không thêm trường tùy ý vào Notice hiện hành.
- `tests/test_token_audit.py`, `tests/test_text_audit.py`: kiểm tra contract mới bằng dữ liệu tổng hợp. Ca regression thuộc parser/privacy phải đặt gần các test đang sở hữu hành vi đó.
- `notebooks/02_eda.ipynb`: đọc bảng audit và vẽ phân bố token/context. `01_data_quality.ipynb` có thể đọc tổng hợp cảnh báo, không nhúng raw mail.

Chỉ thêm hàm chia cửa sổ vào module riêng khi quyết định triển khai chính sách này. Tách audit và sửa preprocessing thành thay đổi review được riêng, tránh việc số đo baseline biến mất sau sửa.

## 10. Đầu ra bàn giao

Đầu ra dữ liệu dự kiến nằm dưới `reports/generated/lm-audit/<run_id>/`, bị Git bỏ qua. Schema/đơn vị cần được chốt trong data contract trước khi code ghi tệp thật.

| Tệp đề xuất | Nội dung |
|---|---|
| `run.json` | Dataset/file/split/code/lock hashes, seed, model revisions, template, cấu hình và môi trường |
| `model_checks.json` | Thông số công bố, thông số đã kiểm tra và smoke-test status |
| `token_lengths.csv` | `doc_id`, text hash, nguồn/split, model/template, token trước/sau, overflow và lý do thiếu |
| `context_summary.csv` | Count và mẫu số theo model/nguồn/split/chính sách, percentile và token bị bỏ |
| `url_retention.jsonl` | Occurrence ID, vị trí/hash URL, stage, retained/partial/lost và nguyên nhân |
| `evidence_coverage.csv` | Coverage span/relation/event, vai trò thời gian, nguồn nhãn và mẫu số |
| `anomalies.jsonl` | Rule ID, severity, code point/vị trí, stage và safe record ID |
| `review_queue.jsonl` | Worklist private có ngữ cảnh cần xem; không đưa vào Git hoặc báo cáo công khai |
| `review_decisions.jsonl` | Quyết định thật của người duyệt, reviewer/time và hash văn bản |
| `policy_comparison.csv` | Coverage, số cửa sổ và chi phí đo được của các chính sách |
| `figures/` | Phân bố token, coverage theo giới hạn, loại lỗi preprocessing |
| `report.md` | Phương pháp, bảng kết quả có mẫu số, ví dụ đã duyệt, khuyến nghị và hạn chế |

Mẫu hàng tổng hợp cần trả lời trực tiếp task:

| Model | N email đo được | P95 input token | Mail overflow n/N | Token nguồn bị bỏ | Mail mất URL n/N có URL | Quan hệ không cùng cửa sổ n/N có nhãn |
|---|---|---|---|---|---|---|
| BamiBERT, C=2.048 | Chờ đo | Chờ đo | Chờ đo | Chờ đo | Chờ đo | Chờ đo |
| ViT5, C=1.024 | Chờ đo | Chờ đo | Chờ đo | Chờ đo | Chờ đo | Chờ đo |

Kèm bảng riêng số lỗi preprocessing theo nguyên nhân và trạng thái review. Không điền số 0 cho một phép đo chưa chạy hoặc subset chưa có nhãn. Không dùng số tài liệu ghi trong README Drive làm kết quả audit mới.

## 11. Trình tự và ước lượng công việc

Ước lượng cho một người thực hiện kỹ thuật, không phải deadline đã thống nhất. Review của con người, download model và tài nguyên GPU có thể kéo dài thời gian lịch.

| Ngày công | Công việc | Kết quả để kiểm tra |
|---|---|---|
| 1 | Gói A–B: snapshot, schema, checkpoint, tokenizer, input template, smoke test | Run manifest và model checklist |
| 2 | Gói C và phần mail/URL của D | Bảng token, mail overflow, URL bị cắt và biểu đồ |
| 3 | Phần span/relation/event của D; quét tự động gói E | Evidence coverage và queue lỗi có provenance |
| 4 | Replay và người của nhóm review gói E | Danh sách lỗi thật, ca chưa rõ và regression cần viết |
| 5 | Gói F, viết báo cáo, kiểm tra artifact và bàn giao | Khuyến nghị cấu hình cho hai model và số liệu truy vết |
| Dự phòng 1–2 ngày | Sửa lỗi đã xác nhận, migration/regeneration nhãn bị ảnh hưởng, chạy lại | Version mới và so sánh trước/sau |

Nếu task chỉ yêu cầu kiểm tra và báo cáo, kết thúc ở ngày 5, bàn giao lỗi thành hạng mục sửa. Nếu cần sửa ngay, chỉ sửa các lỗi được xác nhận; không nhận ngầm trách nhiệm adjudication hay duyệt riêng tư thay người phụ trách.

Nhánh tối thiểu khi thiếu tài nguyên: chốt tokenizer + đếm token toàn corpus + mô phỏng mất URL + audit text; đánh dấu smoke test weights hoặc coverage nhãn là chưa hoàn tất nếu thiếu thiết bị/nhãn. Không tải được weights không cản việc đếm token nếu tokenizer đã có.

## 12. Test, sửa lỗi và tiêu chí nghiệm thu

### Các ca kiểm chứng cần có

- Ranh giới `C-1/C/C+1` sau special tokens và prefix; NLI tính cả profile/separators.
- Đếm full input không bị truncation/padding làm sai; batch và single input cho cùng kết quả.
- URL nằm trước, băng qua và sau điểm cắt; URL lặp, query/percent-encoding, URL dài hơn cửa sổ và trường hợp chỉ có metadata.
- ACTION/argument cùng cửa sổ, khác cửa sổ, băng ranh giới; shared argument và event có nhiều đối số.
- Chia cửa sổ không vượt ngân sách, không mất mapping, không đếm overlap nhiều lần và không lặp vô hạn.
- NFC/NFD, tiếng Việt hợp lệ, ký hiệu toán, emoji/non-BMP, U+FFFD, zero-width, HTML/MIME noise và mojibake giả dương.
- Ngày/giờ/khóa học/phủ định được giữ qua cleaning; quote thật và nội dung bị nhầm quote; plain/HTML khác nhau.
- Tệp đầu ra lỗi không ghi đè baseline; lỗi ghi bằng ID an toàn, không log mail, credential hoặc URL riêng tư.

Với bug, thêm ca hồi quy tổng hợp, quan sát thất bại rồi sửa. Không dùng dữ liệu người tham gia làm fixture commit. Giữ byte nguồn và hash; prepared text thay đổi cần xác định annotation, sentences, provider approval và split/grouping nào phải được tái tạo/kiểm tra. Đừng giữ nhãn cũ với offset “gần đúng”.

### Lệnh kiểm tra khi triển khai

Chạy từ root theo [README](../README.md) và [AGENTS.md](../AGENTS.md). Dùng test file liên quan trước, rồi chạy các kiểm tra sau khi thay parser/privacy/annotation/split:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run smartnotice demo
```

Nếu thay notebook hoặc hàm notebook gọi, chạy `uv run python tools/run_notebooks.py` và xem hình/bảng bị ảnh hưởng. Nếu thay dependencies, chạy `uv lock --check` và kiểm tra đường chạy dùng dependency mới. Không cần huấn luyện đủ ba hệ thống để hoàn thành audit.

### Checklist nghiệm thu

1. Snapshot và model/tokenizer revisions có hash; nêu rõ bản ViT5 base/large, template và giới hạn thực dùng.
2. Mọi tài liệu được tính hoặc có lý do loại/thất bại; số đếm qua các bảng đối soát được.
3. Báo riêng email/web, BamiBERT/ViT5, train/validation/test/domain_test và synthetic/research.
4. Có số mail overflow, bị cắt một phần, bị bỏ hoàn toàn; số token mất với mẫu số rõ.
5. Có URL occurrence/URL duy nhất/mail bị ảnh hưởng; phân biệt mất ở preprocessing và mất do context.
6. Nếu có nhãn hợp lệ, có coverage span, deadline, quan hệ và event theo nguồn nhãn; thiếu nhãn được ghi là chưa xác định.
7. Cảnh báo ký tự có vị trí/code point/nguyên nhân; lỗi ngữ nghĩa quan trọng có người xác nhận, không tự coi mọi cảnh báo là bug.
8. Chính sách văn bản dài được chọn bằng train/validation; mọi window/pair kế thừa nhóm và split tài liệu.
9. Mọi sửa text có đánh giá ảnh hưởng offset/hash/nhãn; giữ baseline và số liệu trước/sau ở run khác nhau.
10. Có báo cáo tái lập, giới hạn và hạng mục còn mở; ví dụ chia sẻ đã được duyệt, không có raw corpus hoặc định danh trong Git.

Không đặt mục tiêu “0 mail dài” hay tự cắt/bỏ mail để đạt chỉ tiêu. Tiêu chí thành công là đo đúng mức mất, truy được nguyên nhân và bàn giao cách xử lý có bằng chứng.
