// --- PHÂN TÍCH VIDEO UPLOAD & HIỂN THỊ SNAPSHOT THEO TỪNG NGƯỜI ---

function toggleVideoPlayer(forceState = null) {
    if (forceState !== null) {
        isVideoPlayerVisible = forceState;
    } else {
        isVideoPlayerVisible = !isVideoPlayerVisible;
    }

    const playerCard = document.getElementById('videoPlayerCard');
    const mainContainer = document.getElementById('videoMainContainer');
    const btn = document.getElementById('toggleVideoBtn');
    const txt = document.getElementById('toggleVideoText');

    if (isVideoPlayerVisible) {
        if (playerCard) playerCard.style.display = 'flex';
        if (mainContainer) mainContainer.style.gridTemplateColumns = '1fr 1.35fr';
        if (txt) {
            txt.innerText = 'BẬT';
            txt.style.color = 'var(--primary)';
        }
        if (btn) {
            btn.style.borderColor = 'var(--primary)';
            btn.style.background = '#0f172a';
        }
    } else {
        if (playerCard) playerCard.style.display = 'none';
        if (mainContainer) mainContainer.style.gridTemplateColumns = '1fr';
        if (txt) {
            txt.innerText = 'TẮT (Tiết kiệm diện tích)';
            txt.style.color = 'var(--text-sub)';
        }
        if (btn) {
            btn.style.borderColor = 'var(--border-color)';
            btn.style.background = '#1e293b';
        }
    }
}

async function startVideoAnalysis(e) {
    if (e && e.preventDefault) e.preventDefault();
    const fileInput = document.getElementById('videoFileInput');
    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
        alert('Vui lòng chọn 1 file video!');
        return;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append('file', file);

    const analyzeBtn = document.getElementById('analyzeBtn');
    if (analyzeBtn) {
        analyzeBtn.disabled = true;
        analyzeBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Đang tải lên...';
    }

    const progressBox = document.getElementById('videoProgressBox');
    if (progressBox) progressBox.style.display = 'block';
    document.getElementById('videoProgressBar').style.width = '0%';
    document.getElementById('videoProgressPercent').innerText = '0%';
    document.getElementById('videoProgressText').innerHTML = '<i class="fa-solid fa-cloud-arrow-up"></i> Đang tải video lên server...';

    // Reset dữ liệu bảng người tìm thấy
    detectedPersonsMap = {};
    const container = document.getElementById('personGalleriesContainer');
    if (container) {
        container.innerHTML = `
            <div id="emptyTableMsg" style="text-align: center; color: var(--text-sub); padding: 50px 15px;">
                <i class="fa-solid fa-radar fa-spin" style="font-size: 2.6rem; margin-bottom: 12px; display: block; color: var(--primary);"></i>
                AI đang quét video... Mỗi khi phát hiện được người, <b>ảnh chụp khuôn mặt thực tế</b> tại khoảnh khắc đó sẽ xuất hiện ngay tại đây!
            </div>
        `;
    }
    const totalBadge = document.getElementById('totalPeopleBadge');
    if (totalBadge) totalBadge.innerText = '0 người';
    const detectedBadge = document.getElementById('detectedCountBadge');
    if (detectedBadge) detectedBadge.innerText = '0 ảnh phát hiện';

    try {
        const res = await fetch('/api/analyze_video', { method: 'POST', body: formData });
        const data = await res.json();

        if (data.status !== 'success') {
            alert('Lỗi: ' + data.message);
            if (analyzeBtn) {
                analyzeBtn.disabled = false;
                analyzeBtn.innerHTML = '<i class="fa-solid fa-microchip"></i> Bắt Đầu Phân Tích AI';
            }
            return;
        }

        currentJobId = data.job_id;
        lastDetectionId = 0;

        // Nạp video vào trình phát HTML5
        const player = document.getElementById('html5VideoPlayer');
        if (player) {
            player.src = data.video_url;
            player.load();
        }

        if (analyzeBtn) {
            analyzeBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Đang quét AI...';
        }
        document.getElementById('videoProgressText').innerHTML = '<i class="fa-solid fa-microchip"></i> AI đang phân tích từng khung hình...';

        showToast(`🚀 Bắt đầu phân tích video: ${data.filename}`);

        // Polling kiểm tra phát hiện mới mỗi 400ms (Realtime Push)
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(pollVideoEvents, 400);

    } catch (err) {
        alert('Lỗi kết nối: ' + err.message);
        if (analyzeBtn) {
            analyzeBtn.disabled = false;
            analyzeBtn.innerHTML = '<i class="fa-solid fa-microchip"></i> Bắt Đầu Phân Tích AI';
        }
    }
}

async function pollVideoEvents() {
    if (!currentJobId) return;

    try {
        const res = await fetch(`/api/video_analysis/${currentJobId}/events?last_id=${lastDetectionId}`);
        if (!res.ok) return;
        const data = await res.json();

        // Cập nhật thanh tiến trình
        const progress = data.progress || 0;
        document.getElementById('videoProgressBar').style.width = `${progress}%`;
        document.getElementById('videoProgressPercent').innerText = `${progress}%`;

        if (data.total_frames > 0) {
            document.getElementById('videoProgressText').innerHTML = 
                `<i class="fa-solid fa-spinner fa-spin"></i> Đang quét AI: Frame ${data.processed_frames}/${data.total_frames}`;
        }

        // CÓ PHÁT HIỆN MỚI TẠI FRAME NÀY -> ĐẨY VÀO DẢI ẢNH THEO TỪNG NGƯỜI
        if (data.new_detections && data.new_detections.length > 0) {
            handleNewDetections(data.new_detections);
            lastDetectionId = data.last_id;
        }

        // Kiểm tra trạng thái hoàn tất
        if (data.status === 'completed' || data.status === 'error') {
            clearInterval(pollInterval);
            pollInterval = null;

            const analyzeBtn = document.getElementById('analyzeBtn');
            if (analyzeBtn) {
                analyzeBtn.disabled = false;
                analyzeBtn.innerHTML = '<i class="fa-solid fa-microchip"></i> Bắt Đầu Phân Tích AI';
            }

            if (data.status === 'completed') {
                document.getElementById('videoProgressBar').style.width = '100%';
                document.getElementById('videoProgressPercent').innerText = '100%';
                document.getElementById('videoProgressText').innerHTML = '✅ <b>Hoàn tất phân tích video!</b>';
                showToast('🎉 Đã hoàn tất phân tích toàn bộ video!');
            } else {
                document.getElementById('videoProgressText').innerHTML = '❌ <b>Lỗi khi phân tích video.</b>';
                showToast('❌ Lỗi khi phân tích video', true);
            }
        }

    } catch (e) {
        console.error("Lỗi polling events:", e);
    }
}

// Xử lý các phát hiện mới và hiển thị trực tiếp ảnh snapshot theo từng người
function handleNewDetections(newDetections) {
    const container = document.getElementById('personGalleriesContainer');
    const emptyMsg = document.getElementById('emptyTableMsg');

    for (const item of newDetections) {
        const name = item.person_name;
        const conf = item.confidence;
        const sec = item.timestamp_sec;
        const str = item.timestamp_str;
        const snap = item.snapshot_path;
        const rowKey = encodeURIComponent(name);

        showToast(`🎯 Phát hiện [${name}] tại mốc ${str} (${(conf * 100).toFixed(1)}%)`);

        const thumbSrc = snap ? `/${snap}` : '';

        if (!detectedPersonsMap[name]) {
            // NGƯỜI MỚI -> TẠO 1 KHỐI CARD MỚI CHO NGƯỜI NÀY
            detectedPersonsMap[name] = {
                name: name,
                maxConf: conf,
                count: 1,
                appearances: [{ sec: sec, str: str, snap: snap, conf: conf }]
            };

            if (emptyMsg) emptyMsg.remove();

            const personCard = document.createElement('div');
            personCard.className = 'person-gallery-card';
            personCard.id = `person-card-${rowKey}`;

            personCard.innerHTML = `
                <div class="person-gallery-header">
                    <div class="person-gallery-title">
                        <span class="person-avatar-circle"><i class="fa-solid fa-user"></i></span>
                        <h3 class="person-gallery-name">${name}</h3>
                        <span class="count-badge" id="count-${rowKey}">1 ảnh phát hiện</span>
                    </div>
                    <span class="conf-badge" id="conf-${rowKey}">Độ tin cậy cao nhất: ${(conf * 100).toFixed(1)}%</span>
                </div>
                <div class="moment-strip" id="moments-${rowKey}">
                    ${renderMomentCardHtml(name, str, sec, thumbSrc, conf)}
                </div>
            `;

            container.appendChild(personCard);
        } else {
            // NGƯỜI ĐÃ CÓ TRONG DANH SÁCH -> CHÈN THÊM THẺ ẢNH MỚI VÀO DẢI ẢNH CỦA HỌ
            const p = detectedPersonsMap[name];
            p.count += 1;
            if (conf > p.maxConf) {
                p.maxConf = conf;
            }
            p.appearances.push({ sec: sec, str: str, snap: snap, conf: conf });

            const confBadge = document.getElementById(`conf-${rowKey}`);
            if (confBadge) confBadge.innerText = `Độ tin cậy cao nhất: ${(p.maxConf * 100).toFixed(1)}%`;

            const countBadge = document.getElementById(`count-${rowKey}`);
            if (countBadge) countBadge.innerText = `${p.count} ảnh phát hiện`;

            const strip = document.getElementById(`moments-${rowKey}`);
            if (strip) {
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = renderMomentCardHtml(name, str, sec, thumbSrc, conf);
                const newCard = tempDiv.firstElementChild;
                strip.appendChild(newCard);
            }
        }
    }

    // Cập nhật tổng số người và tổng số ảnh phát hiện
    const totalPeople = Object.keys(detectedPersonsMap).length;
    let totalDetections = 0;
    for (const k in detectedPersonsMap) {
        totalDetections += detectedPersonsMap[k].count;
    }
    const totalPeopleBadge = document.getElementById('totalPeopleBadge');
    if (totalPeopleBadge) totalPeopleBadge.innerText = `${totalPeople} người`;
    const detectedCountBadge = document.getElementById('detectedCountBadge');
    if (detectedCountBadge) detectedCountBadge.innerText = `${totalDetections} ảnh phát hiện`;
}

function renderMomentCardHtml(name, str, sec, thumbSrc, conf) {
    const imgTag = thumbSrc
        ? `<img src="${thumbSrc}" class="moment-img" alt="${name} lúc ${str}">`
        : `<div class="moment-img" style="display:flex;align-items:center;justify-content:center;color:var(--text-sub);"><i class="fa-solid fa-user"></i></div>`;

    return `
        <div class="moment-card new-pulse" onclick="seekVideo(${sec}, '${name}', '${str}')" title="Nhấp để xem video tại mốc ${str}">
            <div class="moment-img-wrapper">
                ${imgTag}
                <div class="moment-play-overlay">
                    <i class="fa-solid fa-circle-play"></i>
                </div>
            </div>
            <div class="moment-footer">
                <span class="moment-time"><i class="fa-solid fa-play" style="font-size:0.65rem;"></i> ${str}</span>
                <span class="moment-conf">${(conf * 100).toFixed(0)}%</span>
            </div>
        </div>
    `;
}

function seekVideo(sec, name, str) {
    if (!isVideoPlayerVisible) {
        toggleVideoPlayer(true);
        showToast('🎬 Đã tự động mở trình phát video để bạn theo dõi');
    }

    const player = document.getElementById('html5VideoPlayer');
    if (player) {
        player.currentTime = parseFloat(sec);
        player.play();
        showToast(`⏩ Đang phát video lúc ${str || Math.floor(sec) + 's'} (${name || ''})`);
    }
}

function viewSnapshot(src, name, str, conf) {
    if (!src) return;
    document.getElementById('photoModalTitle').innerText = `Ảnh Chân Dung: ${name || ''}`;
    document.getElementById('photoModalImg').src = src;
    document.getElementById('photoModalMeta').innerText = `Mốc thời gian: ${str || ''} | Độ tin cậy: ${conf ? (conf * 100).toFixed(1) + '%' : ''}`;
    document.getElementById('photoModal').style.display = 'flex';
}

function closePhotoModal() {
    const modal = document.getElementById('photoModal');
    if (modal) modal.style.display = 'none';
}

document.addEventListener('DOMContentLoaded', () => {
    const videoForm = document.getElementById('videoForm');
    if (videoForm) {
        videoForm.addEventListener('submit', startVideoAnalysis);
    }
});
