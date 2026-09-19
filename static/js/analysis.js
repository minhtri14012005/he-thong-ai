// Video events are appearances, not one notification per sampled frame.
let videoRun = 0;
let videoBusy = false;
let videoEventItems = new Map();
let videoPeople = new Map();
let videoAudio = null;

function toggleVideoPlayer(forceState = null) {
    isVideoPlayerVisible = forceState === null ? !isVideoPlayerVisible : forceState;
    document.getElementById('videoPlayerCard').style.display = isVideoPlayerVisible ? 'flex' : 'none';
    document.getElementById('videoMainContainer').style.gridTemplateColumns = isVideoPlayerVisible ? '1fr 1.35fr' : '1fr';
    document.getElementById('toggleVideoText').textContent = isVideoPlayerVisible ? 'BẬT' : 'TẮT';
}

async function prepareVideoSound() {
    if (!document.getElementById('videoAlertSound').checked) return;
    try {
        const AudioClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioClass) throw new Error('Trình duyệt không hỗ trợ âm báo');
        videoAudio ??= new AudioClass();
        await videoAudio.resume();
    } catch (error) { showToast('Không bật được âm báo: ' + error.message, true); }
}

function playVideoAlert() {
    if (!document.getElementById('videoAlertSound').checked || !videoAudio || videoAudio.state !== 'running') return;
    const oscillator = videoAudio.createOscillator();
    const gain = videoAudio.createGain();
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(0.12, videoAudio.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, videoAudio.currentTime + 0.18);
    oscillator.connect(gain); gain.connect(videoAudio.destination);
    oscillator.start(); oscillator.stop(videoAudio.currentTime + 0.2);
    oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
}

function addVideoZone() {
    const row = document.createElement('div');
    row.className = 'video-zone-row';
    row.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;margin:8px 0';
    const name = document.createElement('input');
    name.placeholder = 'Tên vùng'; name.maxLength = 60;
    name.className = 'input-control'; name.style.width = '170px'; row.appendChild(name);
    ['Trái %', 'Trên %', 'Phải %', 'Dưới %'].forEach((text, index) => {
        const label = document.createElement('label'); label.textContent = text;
        const input = document.createElement('input');
        input.type = 'number'; input.min = '0'; input.max = '100'; input.step = '0.1';
        input.value = index < 2 ? '0' : '100'; input.style.width = '75px'; input.className = 'input-control';
        label.appendChild(input); row.appendChild(label);
    });
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'btn'; button.textContent = 'Bỏ';
    button.onclick = () => row.remove(); row.appendChild(button);
    document.getElementById('videoZoneRows').appendChild(row);
}

function finishVideoRun() {
    videoBusy = false;
    clearTimeout(pollInterval); pollInterval = null;
    const button = document.getElementById('analyzeBtn');
    button.disabled = false; button.textContent = 'Bắt đầu phân tích AI';
}

async function startVideoAnalysis(event) {
    event?.preventDefault();
    if (videoBusy) return;
    const file = document.getElementById('videoFileInput').files?.[0];
    if (!file) { showToast('Vui lòng chọn video.', true); return; }
    videoBusy = true;
    const run = ++videoRun;
    currentJobId = null; lastDetectionId = 0;
    clearTimeout(pollInterval);
    videoEventItems.clear(); videoPeople.clear();
    document.getElementById('personGalleriesContainer').textContent = 'Đang chờ các lượt xuất hiện được xác nhận…';
    document.getElementById('totalPeopleBadge').textContent = '0 người';
    document.getElementById('detectedCountBadge').textContent = '0 lượt xuất hiện';
    document.getElementById('videoAlertBanner').textContent = '';
    document.getElementById('videoWatchlist').textContent = '';
    document.getElementById('videoAnalysisWarning').textContent = '';
    document.getElementById('videoProgressBox').style.display = 'block';
    document.getElementById('videoProgressBar').style.width = '0%';
    document.getElementById('videoProgressPercent').textContent = '0%';
    document.getElementById('videoProgressText').textContent = 'Đang tải video lên…';
    const button = document.getElementById('analyzeBtn');
    button.disabled = true; button.textContent = 'Đang tải lên…';
    const form = new FormData();
    form.append('file', file);
    form.append('mode', document.getElementById('videoScanMode').value);
    const zones = Array.from(document.querySelectorAll('.video-zone-row')).map(row => {
        const inputs = row.querySelectorAll('input');
        return {name: inputs[0].value, rect: Array.from(inputs).slice(1).map(i => Number(i.value)/100)};
    });
    form.append('zones_json', JSON.stringify(zones));
    await prepareVideoSound();
    try {
        const response = await fetch('/api/analyze_video', {method:'POST', body:form});
        const data = await response.json();
        if (!response.ok || data.status !== 'success') {
            throw new Error(typeof data.detail === 'string' ? data.detail : data.message || 'Yêu cầu phân tích không hợp lệ');
        }
        if (run !== videoRun) return;
        currentJobId = data.job_id;
        const player = document.getElementById('html5VideoPlayer');
        player.src = data.video_url; player.load();
        document.getElementById('videoWatchlist').textContent = `Danh sách đã chốt (${data.watchlist.length} người): ` + data.watchlist.map(p => p.name).join(', ');
        button.textContent = 'Đang phân tích…';
        showToast('Bắt đầu phân tích: ' + data.filename);
        await pollVideoEvents(currentJobId, run);
    } catch (error) {
        if (run !== videoRun) return;
        document.getElementById('videoProgressText').textContent = error.message;
        showToast(error.message, true); finishVideoRun();
    }
}

async function pollVideoEvents(jobId = currentJobId, run = videoRun) {
    if (!jobId || jobId !== currentJobId || run !== videoRun) return;
    let terminal = false;
    try {
        const response = await fetch(`/api/video_analysis/${jobId}/events?last_id=${lastDetectionId}`);
        if (response.status === 404) { terminal = true; throw new Error('Không tìm thấy lần phân tích này'); }
        if (!response.ok) throw new Error('Mất kết nối, đang thử lấy kết quả lại…');
        const data = await response.json();
        if (jobId !== currentJobId || run !== videoRun) return;
        const progress = data.progress || 0;
        document.getElementById('videoProgressBar').style.width = `${progress}%`;
        document.getElementById('videoProgressPercent').textContent = `${progress}%`;
        document.getElementById('videoProgressText').textContent = data.status === 'queued'
            ? 'Đang chuẩn bị phân tích…'
            : `Đã quét tới ${formatVideoTime(data.scanned_until_sec || 0)} · ${data.scanned_frames || 0} khung phân tích · ${Number(data.elapsed_sec || 0).toFixed(1)} giây xử lý`;
        document.getElementById('videoAnalysisWarning').textContent = data.warning_message || '';
        handleNewDetections(data.new_detections || []);
        lastDetectionId = Math.max(lastDetectionId, data.last_id || 0);
        applyAppearanceUpdates(data.appearance_updates || []);
        if (data.status === 'completed' || data.status === 'error') {
            terminal = true;
            const message = data.status === 'completed'
                ? (videoEventItems.size ? 'Đã hoàn tất phân tích video.' : 'Đã quét xong, chưa xác nhận được người trong danh sách. Điều này không chứng minh họ vắng mặt.')
                : 'Phân tích bị lỗi: ' + (data.error_message || 'Không đọc được video');
            document.getElementById('videoProgressText').textContent = message;
            showToast(message, data.status === 'error');
        }
    } catch (error) {
        if (jobId === currentJobId && run === videoRun) document.getElementById('videoProgressText').textContent = error.message;
    } finally {
        if (jobId === currentJobId && run === videoRun) {
            if (terminal) finishVideoRun();
            else pollInterval = setTimeout(() => pollVideoEvents(jobId, run), 400);
        }
    }
}

function formatVideoTime(seconds) {
    const ms = Math.max(0, Math.round(Number(seconds)*1000));
    return `${String(Math.floor(ms/60000)).padStart(2,'0')}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}.${String(ms%1000).padStart(3,'0')}`;
}

function videoSnapshotPath(path) {
    if (typeof path !== 'string') return '';
    const normalized = '/' + path.trim().replace(/\\/g, '/').replace(/^\/+/, '');
    return normalized.startsWith('/static/snapshots/') ? normalized : '';
}

function createVideoSnapshot(item, facePath) {
    const wrapper = document.createElement('div'); wrapper.className = 'moment-img-wrapper';
    const open = document.createElement('button');
    open.type = 'button'; open.className = 'moment-snapshot-button';
    open.title = 'Xem ảnh khuôn mặt';
    const image = document.createElement('img');
    image.className = 'moment-img'; image.loading = 'eager'; image.decoding = 'async';
    image.width = 192; image.height = 192;
    image.alt = `${item.person_name} tại ${item.timestamp_str}`;
    open.onclick = () => viewSnapshot(facePath, item.person_name, item.timestamp_str, item.confidence);
    open.appendChild(image);
    const error = document.createElement('div'); error.className = 'moment-image-error'; error.hidden = true;
    const message = document.createElement('span'); message.textContent = 'Không tải được ảnh mặt.';
    const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'btn'; retry.textContent = 'Tải lại ảnh';
    retry.onclick = () => {
        if (!facePath) return;
        error.hidden = true; open.hidden = false;
        image.src = facePath + (facePath.includes('?') ? '&' : '?') + 'retry=' + Date.now();
    };
    error.append(message, retry);
    image.onload = () => { error.hidden = true; open.hidden = false; };
    image.onerror = () => { open.hidden = true; error.hidden = false; };
    wrapper.append(open, error);
    if (facePath) image.src = facePath;
    else { open.hidden = true; error.hidden = false; message.textContent = 'Bản ghi chưa có ảnh mặt.'; retry.hidden = true; }
    return wrapper;
}

function handleNewDetections(detections) {
    let newCount = 0;
    const container = document.getElementById('personGalleriesContainer');
    for (const item of detections) {
        if (videoEventItems.has(item.id)) continue;
        if (!videoEventItems.size) container.replaceChildren();
        videoEventItems.set(item.id, {...item}); newCount++;
        const key = item.person_id == null ? item.person_name : String(item.person_id);
        let person = videoPeople.get(key);
        if (!person) {
            const card = document.createElement('div'); card.className = 'person-gallery-card';
            const header = document.createElement('div'); header.className = 'person-gallery-header';
            const title = document.createElement('h3'); title.className = 'person-gallery-name'; title.textContent = item.person_name;
            const count = document.createElement('span'); count.className = 'count-badge';
            const strip = document.createElement('div'); strip.className = 'moment-strip';
            header.append(title, count); card.append(header, strip); container.appendChild(card);
            person = {count:0, badge:count, strip}; videoPeople.set(key, person);
        }
        person.count++; person.badge.textContent = `${person.count} lượt`;
        const card = document.createElement('div'); card.className = 'moment-card new-pulse';
        const facePath = videoSnapshotPath(item.snapshot_path || item.face_path);
        card.appendChild(createVideoSnapshot(item, facePath));
        const details = document.createElement('div'); details.className = 'moment-details';
        const time = document.createElement('button'); time.type = 'button'; time.className = 'btn';
        time.textContent = item.timestamp_str;
        time.onclick = () => seekVideo(item.timestamp_sec, item.person_name, item.timestamp_str);
        const score = document.createElement('div'); score.textContent = `Điểm khớp: ${Number(item.confidence).toFixed(3)}`;
        const zone = document.createElement('div'); zone.textContent = item.zone || 'Toàn cảnh';
        const last = document.createElement('div'); last.id = `video-last-${item.id}`; last.style.fontSize = '0.75rem';
        details.append(time, score, zone, last);
        for (const [path,label] of [[facePath,'Ảnh mặt'],[videoSnapshotPath(item.scene_path),'Toàn cảnh']]) {
            if (!path) continue;
            const link = document.createElement('a'); link.href = path; link.target = '_blank'; link.rel = 'noopener';
            link.textContent = label; link.style.marginRight = '8px'; details.appendChild(link);
        }
        card.appendChild(details); person.strip.appendChild(card);
        applyAppearanceUpdates([{id:item.id,last_seen_sec:item.last_seen_sec ?? item.timestamp_sec,last_zone:item.last_zone || item.zone}]);
        const message = `Đã xác nhận ${item.person_name} tại ${item.timestamp_str} · ${item.zone || 'Toàn cảnh'}`;
        showToast(message); document.getElementById('videoAlertBanner').textContent = message;
    }
    if (newCount) playVideoAlert();
    document.getElementById('totalPeopleBadge').textContent = `${videoPeople.size} người`;
    document.getElementById('detectedCountBadge').textContent = `${videoEventItems.size} lượt xuất hiện`;
}

function applyAppearanceUpdates(updates) {
    for (const update of updates) {
        const item = videoEventItems.get(update.id);
        if (!item) continue;
        Object.assign(item, update);
        const label = document.getElementById(`video-last-${update.id}`);
        if (label) label.textContent = `Thấy cuối: ${formatVideoTime(item.last_seen_sec ?? item.timestamp_sec)} · ${item.last_zone || item.zone || 'Toàn cảnh'}`;
    }
}

function seekVideo(seconds, name, text) {
    if (!isVideoPlayerVisible) toggleVideoPlayer(true);
    const player = document.getElementById('html5VideoPlayer');
    player.currentTime = Number(seconds);
    const playback = player.play();
    if (playback?.catch) playback.catch(() => showToast('Bấm phát trên trình phát để xem đoạn video.'));
}

function viewSnapshot(src, name, text, confidence) {
    const path = videoSnapshotPath(src);
    if (!path) return;
    document.getElementById('photoModalTitle').textContent = `Ảnh mặt: ${name || ''}`;
    document.getElementById('photoModalImg').src = path;
    document.getElementById('photoModalMeta').textContent = `${text || ''} · Điểm tương đồng: ${Number(confidence || 0).toFixed(3)}`;
    document.getElementById('photoModal').style.display = 'flex';
}

function closePhotoModal() { document.getElementById('photoModal').style.display = 'none'; }
