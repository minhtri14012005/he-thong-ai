# Hệ thống nhận diện người

Ứng dụng FastAPI / InsightFace nhận diện nhiều khuôn mặt từ iPhone qua Iriun,
webcam, IP camera và video tải lên.

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Mở http://127.0.0.1:8000. Chạy một server/một worker cho nguồn camera hiện tại.

Xem [hướng dẫn nhận diện trực tiếp](docs/LIVE_CLASSROOM.md) để thiết lập
danh sách tìm kiếm, các vùng các vùng quan sát, nhật ký ảnh bằng chứng và kiểm thử dưới 10 m.

Phần upload có **Quét kỹ / Quét nhanh**, chỉ tìm người đang bật tìm kiếm,
xác nhận qua nhiều khung hình và thông báo ngay trong quá trình phân tích.
Xem [hướng dẫn video và kiểm thử phạm vi dưới 15 m](docs/VIDEO_CLASSROOM.md).
