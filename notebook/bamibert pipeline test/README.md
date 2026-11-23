# Notebook thực nghiệm SmartNotice v3.3

Mỗi notebook nạp bản phát hành `split_65_15_20_v3_3_2026-11-15` đã chuẩn bị từ Drive, học hoặc nạp checkpoint đúng theo thiết kế pipeline, chọn cấu hình bằng validation, suy luận test và tính chỉ số. Các notebook dùng cùng tập 403 thông báo train, 93 validation và 126 test thường. Test thường dùng chú giải lịch sử có máy hỗ trợ và đã được dùng trong các phép so sánh trước. [Báo cáo so sánh](reports/tong-hop-pipeline-smartnotice-v3.3-2026-11-23.md)

| Notebook | Huấn luyện và đánh giá |
|---|---|
| [01 BamiBERT LoRA](01-bamibert-lora.ipynb) | Huấn luyện bộ trích xuất LoRA trọng số dương 8 và bộ áp dụng theo hồ sơ |
| [02 LoRA và lọc chồng lấn](02-bamibert-lora-overlap.ipynb) | Dùng cùng checkpoint LoRA, chọn lại ngưỡng cho bộ giải mã lọc chồng lấn |
| [03 LoRA trọng số dương 2](03-bamibert-lora-weight2.ipynb) | Huấn luyện lại bộ trích xuất, dùng bộ áp dụng chung |
| [04 BIO ngữ cảnh](04-bio-context.ipynb) | Huấn luyện bộ gán nhãn BIO và hồi quy logistic cho quan hệ |
| [05 Mẫu câu](05-sentence-templates.ipynb) | Huấn luyện BIO và lập chỉ mục câu từ train |
| [06 Mẫu thông báo](06-document-templates.ipynb) | Huấn luyện BIO và lập chỉ mục câu, toàn thông báo từ train |
| [07 Cụm theo luật và bộ nối](07-span-rules-linkers.ipynb) | Chấm sáu cấu hình trên validation, huấn luyện đầu nối BamiBERT và so sánh cấu hình đã chốt với nối gần nhất trên test |
| [08 BamiBERT theo công việc](08-action-conditioned-kaggle.ipynb) | Huấn luyện hai giai đoạn trên GPU, suy luận từ văn bản test và chấm cục bộ |

## Chạy lại

1. Chỉ định thư mục bản Drive v3.3 đã tải bằng `SMARTNOTICE_SPLIT_ROOT`. Thư mục có `record.json`, `checksums.json`, `assignments.jsonl`, văn bản và chú giải train/validation, văn bản test và `reference_only_do_not_train_on_test/annotations.jsonl`. Mã nạp kiểm tra hash, phân bổ nhóm, schema và vị trí cụm. Các notebook mở chú giải test ở bước chấm.
2. Chỉ định `SMARTNOTICE_BAMIBERT_DIR` tới thư mục checkpoint và tokenizer BamiBERT đã ghim. Với notebook 02–07, đặt `SMARTNOTICE_BASELINE` tới thư mục checkpoint 01, hoặc dùng checkpoint LoRA đã ghi trong báo cáo. Notebook 02 giữ cố định trọng số và notebook 07 chỉ học lại đầu nối. Notebook 03–06 dùng cùng bộ phân loại áp dụng để so sánh. [Revision BamiBERT](https://huggingface.co/Qualcomm-AI-Research/BamiBERT/tree/57bc1340debbe4e348ec549047a763caebe4a977) · [Thiết lập gốc](reports/bamibert-v3.3-validation-2026-11-23.md)
3. Chạy từ thư mục gốc với môi trường Python của thí nghiệm có PyTorch CUDA, Transformers, PEFT, scikit-learn và Jupyter. Chọn số notebook cần chạy và một thư mục kết quả mới. Trình chạy khởi tạo kernel bằng chính trình thông dịch được chọn.

```powershell
$env:SMARTNOTICE_SPLIT_ROOT = 'tmp/drive-run-20261123-fresh'
$env:SMARTNOTICE_BAMIBERT_DIR = 'tmp/bamibert-checkpoint'
$env:UV_CACHE_DIR = 'tmp/uv-cache'
uv run --no-project --python tmp/bamibert-gpu/Scripts/python.exe python tools/run_report_notebooks.py 01 --output reports/generated/notebook-replay
$env:SMARTNOTICE_BASELINE = 'reports/generated/notebook-replay/run-01'
$env:SMARTNOTICE_APP_DEVICE = 'cuda'
uv run --no-project --python tmp/bamibert-gpu/Scripts/python.exe python tools/run_report_notebooks.py 02 03 04 05 06 07 --output reports/generated/notebook-replay
```

Với notebook 08, chọn một trong ba nguồn GPU được mô tả trong notebook. Có thể gửi mã lên một kernel Kaggle riêng tư đã cấu hình, nạp các dự đoán vừa tải từ một lượt Kaggle hoặc huấn luyện trên CUDA với gói đầu vào riêng tư. Nhãn test chỉ dùng cho trình chấm cục bộ. [Mã huấn luyện](../../tools/run_action_conditioned.py) · [Mã chấm](../../tools/score_action_conditioned.py)

Khi cần chạy lại test từ checkpoint LoRA đã huấn luyện, đặt `SMARTNOTICE_FROZEN_EXTRACTION` cho riêng notebook 01 hoặc 03. Notebook kiểm tra metadata của bản dữ liệu, tokenizer, BamiBERT nền và cấu hình huấn luyện trước khi nạp. Đặt `SMARTNOTICE_SKIP_APPLICABILITY=1` để chỉ chấm phần trích xuất trong các notebook 01 và 03–06.

Thư mục `executed/` chứa tám bản notebook đã chạy, giữ đầu ra tổng hợp của từng cell. Thư mục `results/` lưu chỉ số và số đếm tổng hợp. Dữ liệu từng thông báo, dự đoán, checkpoint và nhật ký đầy đủ được lưu riêng trong workspace. Các đường dẫn `reports/generated/` trong báo cáo chỉ vị trí của bằng chứng cục bộ.

Bộ notebook còn có [notebook phát triển LoRA ban đầu](legacy/01_bamibert_development.ipynb) và bốn báo cáo chi tiết về [LoRA](reports/bamibert-v3.3-validation-2026-11-23.md), [mô hình mẫu](reports/drive-v3.3-pipeline-comparison-2026-11-23.md), [luật và bộ nối](reports/rule-spans-bamibert-relations-2026-11-23.md) và [lượt Kaggle](reports/kaggle-action-conditioned-v3.3-2026-11-23.md).

## Kết quả chạy notebook đợt 23–24/11/2026

Các cột F1 tính bằng phần trăm trên 126 thông báo test thường. Tập tham chiếu có 1.412 cụm có kiểu, 1.149 quan hệ và 468 sự kiện. Cột ngày đếm liên kết thời gian khớp cả vai trò và ngày chuẩn hóa trong 188 mốc tường minh. Điểm này dùng nhãn lịch sử có máy hỗ trợ.

| Bản đã chạy | F1 cụm có kiểu | F1 quan hệ | F1 sự kiện | Ngày đúng / 188 |
|---|---:|---:|---:|---:|
| [01 LoRA trọng số 8](executed/01-bamibert-lora.ipynb) | 7,45 | 1,36 | 0,31 | 0 |
| [02 LoRA lọc chồng lấn](executed/02-bamibert-lora-overlap.ipynb) | 12,52 | 0,16 | 0,00 | 0 |
| [03 LoRA trọng số 2](executed/03-bamibert-lora-weight2.ipynb) | 12,86 | 0,24 | 0,24 | 0 |
| [04 BIO ngữ cảnh](executed/04-bio-context.ipynb) | 9,72 | 1,94 | 0,48 | 1 |
| [05 Mẫu câu](executed/05-sentence-templates.ipynb) | 18,29 | 7,55 | 1,49 | 9 |
| [06 Mẫu thông báo](executed/06-document-templates.ipynb) | 19,54 | 9,97 | 1,48 | 16 |
| [07 Luật và từ điển](executed/07-span-rules-linkers.ipynb), nối gần nhất | 11,11 | 1,46 | 0,12 | 2 |
| Cùng cụm luật, học lại đầu BamiBERT | 11,11 | 2,79 | 0,19 | 7 |
| [08 BamiBERT theo công việc](executed/08-action-conditioned-kaggle.ipynb) | **46,11** | **21,85** | **3,09** | 15 |

Notebook 01 huấn luyện lại từ BamiBERT nền, gồm bộ trích xuất và bộ phân loại hồ sơ. Kết quả test trích xuất trùng với lượt dùng checkpoint đã lưu. Bộ phân loại đạt Macro-F1 67,07% trên validation với sự kiện chú giải và F1 đồng thời sự kiện–nhãn áp dụng 0,31% khi chạy từ văn bản test. Notebook 02 giữ cố định checkpoint LoRA trọng số 8 của báo cáo gốc và chọn lại ngưỡng validation. Notebook 03 huấn luyện lại bộ trích xuất từ BamiBERT nền, dùng bộ phân loại hồ sơ chung. F1 cụm trên test của 03 là 12,86% sau huấn luyện lại và 12,82% khi chấm checkpoint cũ. [Điểm LoRA trọng số 8](results/01-test_scores.json) · [Điểm LoRA trọng số 2](results/03-test_scores.json) · [Điểm áp dụng trên validation](results/01-applicability_metrics.json)

Notebook 04–06 huấn luyện lại từ train. Notebook 07 xây lại từ điển và huấn luyện lại đầu nối trên encoder cố định. Hàng 08 chấm lại dự đoán của lượt Tesla T4 đã hoàn tất. Lượt chạy GPU riêng tư mới vẫn ở trạng thái `QUEUED` tại lần kiểm tra cuối. [Lượt Tesla T4 đã hoàn tất](https://www.kaggle.com/code/phattruongpo344/smartnotice-action-conditioned-v33-1123/version/2) · [Lượt Kaggle mới](https://www.kaggle.com/code/phattruongpo344/smartnotice-action-notebook-v33-1123/version/1)

Bốn kết quả test bổ sung so với bảng tổng hợp trước là lọc chồng lấn, LoRA trọng số 2, BIO và mẫu câu. Mẫu câu và mẫu thông báo cùng khớp 6 sự kiện. Mẫu thông báo khớp thêm 22 quan hệ và thêm 7 ngày tường minh.

Trên 11.232 cặp sự kiện–hồ sơ tham chiếu, F1 đồng thời đúng cả sự kiện và nhãn áp dụng lần lượt là 0,31% (01), 0,00% (02), 0,24% (03), 0,48% (04), 1,07% (05) và 0,87% (06). Các cấu hình 02–06 dùng cùng bộ phân loại hồ sơ từ báo cáo gốc. Notebook 01 huấn luyện lại bộ phân loại này. [Điểm mẫu câu](results/05-test_scores.json) · [Điểm mẫu thông báo](results/06-test_scores.json)
