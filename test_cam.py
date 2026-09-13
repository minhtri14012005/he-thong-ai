import cv2

# Thử mở camera 0 với DirectShow
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

if not cap.isOpened():
    print("Không mở được camera 0, thử camera 1...")
    cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)

while True:
    ret, frame = cap.read()
    if not ret:
        print("Không đọc được khung hình!")
        break
    cv2.imshow("Test Camera - Nhan ESC de thoat", frame)
    if cv2.waitKey(1) & 0xFF == 27: # Nhấn phím ESC để đóng
        break

cap.release()
cv2.destroyAllWindows()