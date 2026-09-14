import unicodedata


def remove_accents(input_str: str) -> str:
    """Loại bỏ dấu tiếng Việt cho nhãn vẽ OpenCV cv2.putText tránh lỗi font hiển thị dấu ??"""
    if not input_str:
        return ""
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).replace('đ', 'd').replace('Đ', 'D')
