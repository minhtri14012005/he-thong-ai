# Kế Hoạch: Nâng Cấp Nhận Diện Khoảng Cách Xa Cho Video Upload (High-Res & Patch Zoom Scan)

## 1. Mô tả mục tiêu

Trong môi trường lớp học Việt Nam, khi quay video toàn cảnh phòng học (chiều dài 7m - 10m):
- Người ngồi ở bàn cuối lớp có kích thước khuôn mặt rất nhỏ trong khung hình toàn cảnh.
- Cấu hình mặc định `det_size = (640, 640)` co nhỏ toàn bộ khung hình, khiến khuôn mặt ở xa bị thu nhỏ xuống dưới 10-15px, dẫn đến việc AI có thể **bỏ sót không phát hiện được mặt** để zoom vào so khớp.

**Giải pháp:** Nâng cấp AI Engine cho phần phân tích Video Upload với **Cơ chế Quét Tầm Xa Thông Minh (High-Res & Multi-Scale Scanning)**:
1. **Quét Độ Phân Giải Cao (High-Resolution Detection):** Tăng kích thước dò tìm khuôn mặt lên `(1280, 1280)` hoặc kích thước tự thích ứng theo độ phân giải gốc của video (1080p).
2. **Cơ chế Zoom Phân Vùng Lớp Học (Classroom Patch Zoom Scan):** Với các khung hình kích thước lớn (Full HD / 2K), bên cạnh việc quét tổng thể, AI sẽ tự động phân vùng (ví dụ nửa trên/nửa giữa nơi các dãy bàn học sinh xa camera thường nằm) để "zoom sâu" vào từng cụm bàn học, đảm bảo dù bạn ngồi ở góc xa nhất hoặc bàn cuối lớp, khuôn mặt vẫn hiển thị đủ lớn và sắc nét để AI nhận diện chuẩn xác.

---

## 2. Cân bằng giữa Tốc độ và Độ nhạy tầm xa

- Quét ở độ phân giải cao `(1280, 1280)` sẽ đòi hỏi CPU tính toán nhiều hơn so với `(640, 640)`.
- Tuy nhiên, vì chúng ta đang chạy theo cơ chế lấy mẫu (sample 2 frame/giây) và chạy trong background thread, video 20s - 30s vẫn chỉ mất khoảng 4 - 8 giây để quét xong, hoàn toàn không làm giật hay chậm máy.

---

## 3. Các bước triển khai kỹ thuật

### Bước 1: Cấu hình hệ thống (`config.py`)
- Bổ sung cấu hình độ phân giải quét riêng cho Video Upload:
  ```python
  VIDEO_DET_SIZE = (1280, 1280)
  ENABLE_PATCH_ZOOM_SCAN = True
  ```

### Bước 2: Nâng cấp AI Engine (`ai_engine.py`)
- Thêm phương thức phát hiện tầm xa: `process_frame_high_res(frame)`
  1. **Quét toàn cảnh độ phân giải cao (Global High-Res Pass):** Dò tìm các khuôn mặt trong toàn bộ lớp học.
  2. **Quét phân vùng tầm xa (Patch Zoom Scan):** Chia frame thành các vùng nửa trên / nửa giữa (nơi các dãy bàn học sinh xa camera thường nằm) và quét với tỷ lệ 1:1, giúp bắt trọn những khuôn mặt dù chỉ chiếm kích thước rất nhỏ.
  3. **Gộp và khử trùng lặp (NMS - Non-Maximum Suppression):** Tổng hợp tất cả các khuôn mặt tìm thấy từ cả 2 pass, loại bỏ các box trùng nhau.
  4. **Trích xuất đặc trưng nhận diện:** Sau khi bắt trọn khuôn mặt ở xa, AI tự động crop và chuẩn hóa về kích thước chuẩn chất lượng cao để trích xuất vector 512D nhận diện người đó trong CSDL.

### Bước 3: Tích hợp vào Luồng Phân Tích Video (`ai_engine.py`)
- Cập nhật hàm `analyze_video_background()`:
  - Sử dụng phương thức quét tầm xa `process_frame_high_res()` thay vì quét cơ bản `(640, 640)`.
  - Tự động lưu thumbnail crop khuôn mặt sắc nét cho người ở xa để hiển thị lên bảng kết quả (Snapshot Moment Cards).

---

## 4. Kế hoạch kiểm thử (Verification)
1. **Kiểm thử phát hiện khuôn mặt nhỏ ở xa:**
   - Sử dụng video quay từ góc rộng lớp học có người ngồi ở khoảng cách 5m - 8m (bàn cuối).
   - Kiểm tra AI phát hiện được khuôn mặt ở bàn xa và so khớp thành công với CSDL.
2. **Kiểm thử hiển thị:**
   - Kiểm tra ảnh thumbnail chụp khuôn mặt tại khoảnh khắc đó hiển thị sắc nét trong dải ảnh (filmstrip gallery).
