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
        showToast('🔍 Đã BẬT Auto-Zoom: Tự động bắt nét khoảng cách (Không gián đoạn video)');
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


function stopStream() {
    const streamImg = document.getElementById('cameraStream');
    if (streamImg) streamImg.src = "";
    fetch('/api/control_stream?action=stop', { method: 'POST' });
}

function toggleIpInput() {
    const source = document.getElementById('camSourceSelect').value;
    const ipInput = document.getElementById('iphoneIpInput');
    if (ipInput) {
        ipInput.style.display = (source === 'ip_cam') ? 'block' : 'none';
    }
}

function changeCameraSource() {
    const select = document.getElementById('camSourceSelect');
    if (!select) return;

    const source = select.value;
    const ip = document.getElementById('iphoneIpInput') ? document.getElementById('iphoneIpInput').value.trim() : '';
    if (source === 'ip_cam' && !ip) return alert('Vui lòng nhập IP hoặc URL Camera!');

    currentSource = source;
    const streamImg = document.getElementById('cameraStream');
    if (streamImg) {
        streamImg.src = `/video_feed?source=${source}&ip=${encodeURIComponent(ip)}&auto_zoom=${autoZoomEnabled}&t=${new Date().getTime()}`;
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
