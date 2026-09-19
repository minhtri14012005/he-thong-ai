// --- ĐIỀU KHIỂN LUỒNG LIVE STREAM & AUTO-ZOOM ---

async function toggleAutoZoom() {
    autoZoomEnabled = !autoZoomEnabled;
    const btn = document.getElementById('autoZoomBtn');
    const txt = document.getElementById('autoZoomText');
    if (autoZoomEnabled) {
        if (btn) {
            btn.style.borderColor = 'var(--primary)';
            btn.style.background = '#0284c7';
            btn.style.color = '#fff';
        }
        if (txt) {
            txt.innerText = 'TỰ ĐỘNG (BẬT)';
            txt.style.color = '#fff';
        }
        showToast('Đã bật phóng to hiển thị. AI vẫn quét toàn ảnh gốc.');
    } else {
        if (btn) {
            btn.style.borderColor = 'var(--border-color)';
            btn.style.background = '#1e293b';
            btn.style.color = 'var(--text-main)';
        }
        if (txt) {
            txt.innerText = 'TẮT (Toàn Cảnh)';
            txt.style.color = 'var(--text-sub)';
        }
        showToast('Đã TẮT Auto-Zoom: Cố định góc rộng toàn cảnh');
    }

    // Gửi lệnh mềm tới backend trong nền (Zero-lag, giữ nguyên luồng 30 FPS, không reload camera)
    try {
        await fetch(`/api/set_auto_zoom?enabled=${autoZoomEnabled}`, { method: 'POST' });
    } catch (err) {
        console.error('Lỗi khi cập nhật Auto-Zoom:', err);
    }
}


async function stopStream() {
    const streamImg = document.getElementById('cameraStream');
    if (streamImg) streamImg.removeAttribute('src');
    await fetch('/api/control_stream?action=stop', { method: 'POST' });
}

function toggleIpInput() {
    const source = document.getElementById('camSourceSelect').value;
    const ipInput = document.getElementById('iphoneIpInput');
    if (ipInput) {
        ipInput.style.display = (source === 'ip_cam') ? 'block' : 'none';
    }
}

let isSwitchingCamera = false;

async function changeCameraSource() {
    const select = document.getElementById('camSourceSelect');
    if (!select || isSwitchingCamera) return;

    const source = select.value;
    const ip = document.getElementById('iphoneIpInput') ? document.getElementById('iphoneIpInput').value.trim() : '';
    if (source === 'ip_cam' && !ip) return alert('Vui lòng nhập IP hoặc URL Camera!');

    isSwitchingCamera = true;
    select.disabled = true;

    const streamImg = document.getElementById('cameraStream');
    const sourceLabel = source === 'iphone' ? 'iPhone (Iriun Cam)' : (source === 'webcam' ? 'Webcam Laptop' : 'IP Camera');
    showToast(`🔄 Đang chuyển sang ${sourceLabel}...`);

    try {
        // 1. Gọi backend để giải phóng an toàn camera cũ trước khi mở camera mới
        if (streamImg) streamImg.removeAttribute('src');
        const response = await fetch(`/api/switch_camera?source=${source}&ip=${encodeURIComponent(ip)}`, { method: 'POST' });
        const result = await response.json();
        if (!response.ok || result.status !== 'success') throw new Error(result.detail || 'Không mở được camera');

        // 2. Cập nhật luồng stream mới với timestamp chống cache
        if (streamImg) {
            streamImg.src = `/video_feed?source=${source}&ip=${encodeURIComponent(ip)}&auto_zoom=${autoZoomEnabled}&t=${Date.now()}`;
        }
        currentSource = source;
        isPausedState = false;
        document.getElementById('pauseBtn').textContent = 'Tạm Dừng';
        showToast(`✅ Đã kết nối: ${sourceLabel}`);
    } catch (err) {
        console.error('Lỗi khi chuyển camera:', err);
        showToast('Lỗi kết nối: ' + err.message, true);
    } finally {
        isSwitchingCamera = false;
        select.disabled = false;
    }
}


async function togglePause() {
    const action = isPausedState ? "resume" : "pause";
    await fetch(`/api/control_stream?action=${action}`, { method: 'POST' });
    isPausedState = !isPausedState;
    const pauseBtn = document.getElementById('pauseBtn');
    if (pauseBtn) {
        pauseBtn.innerHTML = isPausedState ? `<i class="fa-solid fa-play"></i> Tiếp Tục` : `<i class="fa-solid fa-pause"></i> Tạm Dừng`;
    }
}
