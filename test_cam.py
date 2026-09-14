import cv2

try:
    import comtypes
    comtypes.CoInitialize()
    from pygrabber.dshow_graph import FilterGraph
    devices = FilterGraph().get_input_devices()
    print("=== DANH SÁCH CAMERA PHÁT HIỆN ĐƯỢC ===")
    for idx, name in enumerate(devices):
        print(f"  [{idx}] {name}")
    print("=======================================")
except Exception:
    pass

print("\nMặc định mở Camera Index 1 (Webcam Laptop)...")
print("Phím tắt: [ESC] hoặc [Q] để thoát | [S] để chuyển giữa Camera 0 (Iriun) và Camera 1 (Laptop)\n")

current_idx = 1
cap = cv2.VideoCapture(current_idx, cv2.CAP_DSHOW)

while True:
    ret, frame = cap.read()
    if not ret:
        print(f"Không đọc được khung hình từ Camera {current_idx}!")
        break
    cv2.imshow(f"Test Camera (Index {current_idx}) - ESC/Q: Thoat, S: Doi Cam", frame)
    key = cv2.waitKey(1) & 0xFF
    if key in [27, ord('q'), ord('Q')]:
        break
    elif key in [ord('s'), ord('S')]:
        cap.release()
        current_idx = 0 if current_idx == 1 else 1
        print(f"-> Đang chuyển sang Camera Index {current_idx}...")
        cap = cv2.VideoCapture(current_idx, cv2.CAP_DSHOW)

cap.release()
cv2.destroyAllWindows()