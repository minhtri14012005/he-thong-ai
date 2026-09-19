# Tìm người trong video

## Cách dùng

1. Khởi động lại server sau khi cập nhật mã. Migration tự thêm cột, giữ dữ liệu cũ.
2. Trong **Quản lý dữ liệu khuôn mặt**, thêm ảnh mẫu rõ và bật **Đang tìm** cho người cần tìm.
   Người không có ảnh mẫu hợp lệ không được đưa vào danh sách của lần phân tích.
3. Vào **Tải Video Lên**, chọn file và chọn **Quét kỹ** (mặc định).
4. Nếu video quay cố định, có thể khai báo vùng các vùng quan sát bằng tọa độ %
   trên ảnh gốc. Đây là vùng riêng cho video, không tự lấy vùng của camera trực tiếp.
   Với máy quay di chuyển, để trống vùng để tránh gắn nhãn vị trí sai.
5. Có thể bật **Âm báo khi xác nhận người cần tìm**, sau đó bấm **Bắt đầu phân tích AI**.
6. Danh sách người cần tìm của lần phân tích được hiển thị phía trên. Mỗi lượt xác nhận
   xuất hiện ngay trong quá trình quét: tên, điểm tương đồng, vùng và mốc video,
   kèm ảnh mặt / ảnh toàn cảnh. Bấm ảnh mặt hoặc mốc thời gian để xem đoạn tương ứng.

Thông báo hiển thị trong ứng dụng, có âm báo tùy chọn. Không gửi email hay thông báo
ra ứng dụng khác. Trình duyệt có thể hạn chế âm thanh hoặc làm chậm cập nhật khi tab
chạy nền. Để theo dõi sát, giữ tab ứng dụng đang mở.

## Hai chế độ

| Chế độ | Không gian | Thời gian trong video |
|---|---|---|
| Quét kỹ | Toàn cảnh 1280×1280 + cả 6 vùng chồng lấn 960×960 trên mỗi khung được chọn | Mục tiêu 4 khung/giây, tăng lên 8 khi có mặt mới, di chuyển hoặc đang xác nhận |
| Quét nhanh | Toàn cảnh 1280×1280 + 1 trong 6 vùng luân phiên 640×640 | Mục tiêu 3 khung/giây, tăng lên 8 khi cần |

Tần suất thực không vượt FPS gốc; việc chọn frame theo timestamp có thể làm tần suất
thấp hơn mục tiêu. Video được đọc tuần tự, không nhảy seek từng mẫu. Nếu metadata
thời gian không dùng được, hệ thống dùng FPS dự phòng và hiển thị cảnh báo.

Quét nhanh có thể bỏ sót mặt nhỏ chỉ xuất hiện trong vùng luân phiên. Dùng quét kỹ
cho cảnh nhiều vùng ảnh hoặc nhiều người. Sáu vùng bao phủ toàn ảnh, không chỉ nửa trên.
Mặt đã phát hiện được căn chỉnh/trích đặc trưng từ pixel ảnh gốc. Ảnh mặt lưu không
được phóng to để giả tạo thêm độ chi tiết.

## Xác nhận và lượt xuất hiện

- Job giữ bản chụp gallery trong bộ nhớ tại thời điểm tải lên: ảnh mẫu, ID, tên,
  trạng thái bật/tắt, ngưỡng khớp. Sửa danh sách trong lúc quét chỉ áp dụng cho lần
  phân tích mới. CSDL lưu danh sách mục tiêu, số mẫu, fingerprint gallery, mô hình,
  chế độ và ngưỡng để đối chiếu; không lưu thêm bản sao embedding trong bản ghi job.
- Những người tắt tìm vẫn tham gia so sánh để loại trường hợp dễ nhầm với mục tiêu,
  nhưng không được trả thành kết quả tìm thấy.
- Dùng bộ lọc chất lượng và bộ xác nhận như live: mặt tối thiểu 40 pixel ở cạnh ngắn,
  kiểm tra độ nét/góc mặt, điểm khớp tối thiểu 0,50 và margin 0,08 giữa các danh tính.
  Đây là ngưỡng khởi đầu, chưa hiệu chỉnh cho một không gian cụ thể.
- Cần ít nhất 3 trong 5 quan sát mới của cùng track trong 2,5 giây video, và quan sát
  hiện tại cũng phải khớp. Buffer ảnh trùng hệt không được tính thêm phiếu xác nhận.
- Hệ thống ghi ảnh và commit sự kiện ngay khi xác nhận, trước khi quét frame tiếp theo.
  Giao diện lấy sự kiện mới theo chu kỳ khoảng 400 ms sau mỗi phản hồi, không chờ quét xong.
  Đây không phải cam kết thời gian thực cứng; tải GPU, lưu ảnh, mạng và trình duyệt đều ảnh hưởng.
- Một người hiện liên tục tạo một lượt. Các lần xác nhận mới cập nhật mốc thấy cuối
  và vùng cuối, không tạo thêm âm báo. Mất xác nhận quá 5 giây video rồi nhận lại sẽ
  tạo lượt mới. Đây không chứng minh người đó đã rời khỏi phòng.
- Bằng chứng ban đầu giữ nguyên. Mốc xác nhận khác với mốc đầu tiên nhìn thấy track;
  cả hai được lưu. Theo dõi mất dấu/Unknown không kéo dài lần nhìn thấy cuối.
- Nếu file lỗi, mô hình lỗi hoặc lưu bằng chứng thất bại, job báo lỗi và giữ kết quả
  đã xác nhận trước đó. Không báo 100% hoàn tất cho file không đọc được hoặc bị thiếu
  đáng kể số frame so với metadata. Có thể có cảnh báo metadata nếu file khai báo sai.
- Khi server khởi động lại, lần quét chưa hoàn tất được đánh dấu lỗi và giữ các sự kiện
  đã lưu; cần tải video lên để quét lại. Chạy một tiến trình server như hướng dẫn README.

## Phạm vi dưới 15 m

Hệ thống không đo khoảng cách mét từ video và không suy ra vị trí bàn cụ thể từ tên vùng.
Không có cam kết nhận diện mọi người ở 15 m: phải có khuôn mặt đủ rõ trong dữ liệu gốc.
Người quay lưng hoặc bị che kín mặt chỉ có thể được tìm khi có quan sát phù hợp khác.

Để nghiệm thu, dùng video độc lập với ảnh đăng ký, có đánh dấu danh tính và mốc xuất hiện:

| Nhóm kiểm tra | Tình huống |
|---|---|
| Khoảng cách | Khoảng 3, 5, 8, 10, 12 và gần 15 m; giữa ảnh và hai bên |
| Tư thế | Đứng, ngồi nhìn lên, ngồi cúi đầu rồi nhìn lên |
| Di chuyển | Đi vào lớp, đi tới bàn, đi ngang/cắt nhau, đổi chỗ |
| Che khuất | Người đi ngang mặt, che một phần, mất dấu rồi xuất hiện lại |
| Độ đông | Từng người, nhóm 5/10 người và số người thực tế trong khung hình |
| Đối chứng | Người ngoài danh sách và người đã tắt tìm kiếm |

Ghi theo lượt xuất hiện: số đúng, số bỏ sót, số nhận nhầm, số cảnh báo lặp, mốc bắt đầu
thấy rõ mặt, mốc xác nhận trong video, độ trễ hiển thị và thời gian xử lý toàn file.
Kết quả không có cảnh báo không chứng minh người cần tìm vắng mặt.

## Kiểm thử kỹ thuật

```powershell
python -B -m unittest discover -s tests -v
```

Các test dùng SQLite và ảnh tạm, không ghi log thử vào dữ liệu thật. Bao phủ snapshot
danh sách, người đã tắt, quét đủ vùng, lấy mẫu thích ứng, xác nhận nhiều người, sự kiện
trước khi job hoàn tất, chống lặp ảnh/lặp lượt, xuất hiện lại, lỗi video/mô hình/ảnh,
metadata thiếu, API upload và tương thích với luồng live.

`tests/test_video_ui.mjs` kiểm thử logic bằng DOM mô phỏng: cảnh báo không trùng,
ảnh bằng chứng, mốc thấy cuối, polling tuần tự, lỗi và phản hồi cũ. Đây không phải
kiểm tra trực quan trên trình duyệt.

Đã chạy smoke test decoder và mô hình thật trên CUDA bằng video tổng hợp không có
khuôn mặt; không dùng kết quả đó làm số liệu độ chính xác ở lớp hoặc ở 15 m.

Đã kiểm tra thêm một video có sẵn trong dự án: 720×1280, 30 FPS, 356 frame,
dài khoảng 11,87 giây. Trên bản sao dữ liệu bật mục tiêu để kiểm thử:

| Chế độ | Khung được phân tích | Thời gian xử lý | Lượt nhận diện do hệ thống tạo |
|---|---:|---:|---:|
| Quét nhanh | 58 | 11,97 giây | 1 |
| Quét kỹ | 63 | 19,09 giây | 1 |

Cả hai đọc đủ 356 frame và không báo lỗi metadata. Dữ liệu thử được lưu ở thư mục
tạm; không thay đổi trạng thái bật/tắt hoặc nhật ký thật. Chưa có nhãn đối chiếu
danh tính/khoảng cách của video này nên không suy ra tỷ lệ chính xác từ số lượt trên.
