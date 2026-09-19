# Nhận diện trực tiếp

## Chạy ứng dụng

Mở Iriun trên máy tính và iPhone, chọn camera sau trên iPhone. Từ thư mục dự án:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000`. Dùng một tiến trình server (`--workers 1`, mặc định);
không chạy nhiều server cùng mở một camera. Khởi động đầu tiên có thể mất vài giây
để warm-up mô hình. Không cần thay dữ liệu người đã đăng ký: khi khởi động, migration
chỉ bổ sung cột và giữ các bản ghi cũ.

## Sử dụng

1. Trong **Quản lý dữ liệu khuôn mặt**, bật **Đang tìm** cho người cần tìm.
   Người có sẵn mặc định được bật. Ảnh của người đã tắt vẫn giúp loại trừ so khớp
   mơ hồ nhưng không tạo log nhận diện trực tiếp cho người đó.
2. Chuẩn bị khoảng 5–10 ảnh mẫu rõ/người, có góc thẳng và hơi nghiêng. Không dùng
   ảnh kiểm thử làm ảnh đăng ký; không đăng ký ảnh nhóm vì luồng đăng ký chọn mặt lớn nhất.
3. Trong **Live Camera**, iPhone/Iriun được chọn mặc định, Auto-Zoom tắt để giữ toàn cảnh.
   Bấm **Kết nối** nếu kết nối trước đó thất bại.
4. Xem thông số độ phân giải thật, FPS camera, số lượt AI/giây và thời gian xử lý.
   Di chuột lên thông số để xem provider từng mô hình. Chỉ báo GPU phản ánh provider
   chính, không phải phép đo mức sử dụng GPU.
5. Mở **Thiết lập vùng các vùng quan sát** để thêm các hình chữ nhật theo góc quay.
   Tọa độ là % trên ảnh gốc, gốc trên trái. Ví dụ vùng chiếm một phần tư phía trên trái
   có trái=0, trên=0, phải=50, dưới=50. Đây chỉ là ví dụ tọa độ, không phải sơ đồ lớp.
   Chưa khai báo vùng thì ghi **Toàn cảnh**. Vùng chồng lấn ưu tiên theo thứ tự khai báo.
   Các vùng gắn nhãn bằng tâm mặt, không đo vị trí vật lý hoặc khoảng cách.
6. Xem nhật ký theo từng người hoặc dòng thời gian; mở **Ảnh mặt / Toàn cảnh**
   để kiểm tra bằng chứng. Điểm tương đồng không phải xác suất nhận diện đúng.

## Hành vi

- Một worker AI và một luồng camera được chia sẻ giữa các cửa sổ xem; việc đóng một
  cửa sổ không nhân bản hoặc dừng worker. Bấm **Tắt Video / Cam** để dừng camera và AI.
  Chuyển sang tab quản lý hoặc phân tích video cũng dừng camera. Tạm dừng ngừng nhận
  diện/ghi log mới, nhưng luồng thu hình vẫn chạy để khi tiếp tục có hình mới.
- Mỗi lượt quét dùng toàn cảnh 1280×1280 và một trong sáu vùng chồng lấn luân phiên.
  Mặt được căn chỉnh và trích đặc trưng từ ảnh gốc. Không giới hạn một người/một khung.
- Chỉ nhận diện các mặt qua kiểm tra kích thước, độ nét và độ cân đối landmarks.
  Đây là bộ lọc chất lượng ban đầu, không bảo đảm nhận diện ở một khoảng cách cố định.
- Theo dõi dùng khung mặt, dự đoán chuyển động ngắn và embedding khi có.
  Xác nhận khi cùng một danh tính có ít nhất 3 trong 5 quan sát mới gần nhất,
  trong tối đa 2,5 giây, và quan sát hiện tại cũng khớp danh tính đó.
- Frame đã đọc rồi hoặc buffer giống hệt không được tính lại làm bằng chứng mới.
  Mất hình mới quá 2 giây thì bỏ trạng thái nhận diện hiện tại. Không suy ra một người
  vẫn ngồi ở bàn khi mặt đã bị che hoặc mất dấu.
- Ghi log từ worker AI ngay khi xác nhận, độc lập với vẽ video. Mỗi lượt xuất hiện
  có ảnh toàn cảnh, ảnh mặt, ID người, tên, nguồn, vùng, track và thời gian.
  Ảnh/điểm/vùng ban đầu giữ nguyên; lần nhìn thấy cuối và vùng cuối được cập nhật
  có giới hạn tần suất để giảm tải SQLite. Thời điểm thấy cuối trong DB có thể chậm
  tối đa khoảng một giây so với lần xác nhận cuối.
- Không có xác nhận mới quá 15 giây rồi nhận lại thì tạo lượt mới. Điều này chỉ là
  quy ước lượt xuất hiện, không khẳng định người đó đã ra khỏi lớp.
- Khi đổi ảnh mẫu hoặc danh sách tìm kiếm, worker bỏ lịch sử xác nhận cũ và xác nhận lại.
- Bản hiện tại chạy **một nguồn camera tại một thời điểm**. Bản đồ vùng dùng cho góc quay
  đang cài đặt; đặt lại khi đổi vị trí hoặc nguồn camera. Chưa có ghép danh tính giữa
  nhiều camera, nhận biết chính xác vị trí cụ thể hoặc đo khoảng cách mét.
- Video tải lên cũng dùng danh sách bật/tắt, nhưng chốt danh sách riêng lúc bắt đầu
  mỗi lần phân tích. Xem [hướng dẫn video](VIDEO_CLASSROOM.md).

## Hiệu chỉnh tại không gian thực tế

Các giá trị `LIVE_*` trong `config.py` là điểm bắt đầu, chưa phải ngưỡng đã nghiệm thu:

| Tham số | Mặc định | Ý nghĩa |
|---|---:|---|
| `LIVE_MATCH_THRESHOLD` | 0,50 | Điểm khớp tối thiểu |
| `LIVE_MATCH_MARGIN` | 0,08 | Chênh lệch với người khác đứng thứ hai (không so với ảnh thứ hai cùng người) |
| `LIVE_MIN_FACE_PIXELS` | 40 | Cạnh ngắn của khung mặt trên ảnh gốc; chỉ là bộ lọc tối thiểu |
| `LIVE_MIN_SHARPNESS` | 35 | Ngưỡng phương sai Laplacian; phụ thuộc hình ảnh thực tế |
| `LIVE_TARGET_AI_FPS` | 10 | Mục tiêu tối đa số lượt quét/giây, không cam kết hiệu năng |
| `LIVE_TRACK_TTL` | 1,5 giây | Thời gian giữ trạng thái tạm mất dấu |
| `LIVE_REENTRY_SECONDS` | 15 giây | Khoảng cách giữa các lần xác nhận để tách lượt |

Đo tại khoảng 2, 5, 8 và gần 10 m, cả vị trí giữa hình và mép hình. Tại mỗi vị trí:

1. Cho từng người đi vào, đi tới bàn, ngồi xuống và nhìn lên.
2. Tăng lên nhóm 5, 10 người, rồi mức đông thực tế; có cả người ngoài danh sách.
3. Thử đi cắt ngang, che nhau, cúi đầu, đổi chỗ, rời khung rồi quay lại.
4. Ghi số lượt đúng, số lượt bỏ sót, số log nhận nhầm, log trùng và thời gian từ lúc
   mặt đủ rõ tới lúc ghi log. Phân loại kết quả theo khoảng cách/vùng/ánh sáng/số người.
5. Kiểm tra ảnh bằng chứng, không đánh giá dựa vào tên còn lưu trên hình.

Nếu mặt xa thiếu chi tiết, hãy chỉnh vị trí/góc quay hoặc bổ sung góc camera;
giảm ngưỡng so khớp không giải quyết được thiếu chi tiết. Không dùng kết quả trên
ảnh mẫu để suy ra độ chính xác trong khung hình. Chưa có số liệu nghiệm thu dưới 10 m.

## Kiểm thử phần mềm

```powershell
python -B -m unittest discover -s tests -v
```

Kiểm thử dùng SQLite/ảnh tạm, không ghi log giả vào dữ liệu thật. API tests cần `httpx`.
Bao phủ xác nhận nhiều người, Unknown/mặt mờ, che khuất, đổi danh tính, dự đoán chuyển động,
margin giữa danh tính, bật/tắt người tìm, log theo lượt, ảnh bằng chứng, migration,
khung hình lặp, camera mất hình và nhiều cửa sổ xem.

Đã smoke-test mô hình thật trên CUDA: quét ảnh trống 1920×1080 sau warm-up khoảng
60–62 ms/lượt tại máy kiểm tra. Đây không phải benchmark cảnh đông người.
Thiết bị `Iriun Webcam` được Windows liệt kê, nhưng lần kiểm tra camera không mở được
luồng DirectShow, nên chưa đo được ảnh thật, độ trễ end-to-end hoặc phạm vi 10 m.
