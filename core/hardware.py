import config


def scan_available_cameras() -> list:
    """
    Quét danh sách các thiết bị camera vật lý và camera ảo DirectShow trên Windows.
    """
    devices = []
    try:
        import comtypes
        comtypes.CoInitialize()
        from pygrabber.dshow_graph import FilterGraph
        devices = FilterGraph().get_input_devices()
    except Exception as e:
        print(f"Lỗi quét camera DirectShow: {e}")
    finally:
        try:
            import comtypes
            comtypes.CoUninitialize()
        except Exception:
            pass

    return [{"index": i, "name": name} for i, name in enumerate(devices)]


def get_camera_device_index(source: str) -> int:
    """
    Tự động tìm chỉ số (index) camera DirectShow trên Windows.
    - 'iphone': tìm thiết bị có tên chứa 'iriun', fallback config.DEFAULT_IRIUN_INDEX (0)
    - 'webcam': tìm webcam laptop (bỏ qua iriun, obs, virtual), fallback config.DEFAULT_WEBCAM_INDEX (1)
    """
    cameras = scan_available_cameras()
    devices = [c["name"] for c in cameras]

    if source == "iphone":
        for idx, name in enumerate(devices):
            if "iriun" in name.lower():
                return idx
        return getattr(config, "DEFAULT_IRIUN_INDEX", 0)
    else:
        for idx, name in enumerate(devices):
            name_lower = name.lower()
            if not any(v in name_lower for v in ["iriun", "obs", "virtual"]):
                return idx
        return getattr(config, "DEFAULT_WEBCAM_INDEX", 1)
