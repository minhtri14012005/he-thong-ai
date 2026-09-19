let liveStatus = { detections: [], connected: false };
let zonesLoaded = false;

function escapeLive(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function addLiveZone(zone = {name: '', rect: [0, 0, 1, 1]}) {
    const row = document.createElement('div');
    row.className = 'live-zone-row';
    row.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;margin:8px 0';
    const name = document.createElement('input');
    name.placeholder = 'Tên vùng quan sát';
    name.value = zone.name;
    name.className = 'input-control';
    name.style.width = '210px';
    name.maxLength = 60;
    row.appendChild(name);
    ['Trái %', 'Trên %', 'Phải %', 'Dưới %'].forEach((label, i) => {
        const field = document.createElement('label');
        field.textContent = label;
        const input = document.createElement('input');
        input.type = 'number'; input.min = '0'; input.max = '100'; input.step = '0.1';
        input.value = Math.round(zone.rect[i] * 1000) / 10;
        input.className = 'input-control'; input.style.width = '75px';
        field.appendChild(input); row.appendChild(field);
    });
    const remove = document.createElement('button');
    remove.type = 'button'; remove.className = 'btn'; remove.textContent = 'Bỏ vùng';
    remove.onclick = () => row.remove(); row.appendChild(remove);
    document.getElementById('liveZoneRows').appendChild(row);
}

async function saveLiveZones() {
    const zones = Array.from(document.querySelectorAll('.live-zone-row')).map(row => {
        const inputs = row.querySelectorAll('input');
        return {name: inputs[0].value, rect: Array.from(inputs).slice(1).map(i => Number(i.value)/100)};
    });
    try {
        const res = await fetch('/api/live/zones', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(zones)});
        const data = await res.json();
        if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Vùng không hợp lệ');
        showToast('Đã lưu vùng theo góc quay hiện tại.');
    } catch (error) { showToast(error.message, true); }
}

async function refreshLiveStatus() {
    try {
        const res = await fetch('/api/live/status');
        if (!res.ok) throw new Error('Không lấy được trạng thái camera');
        liveStatus = await res.json();
        if (!zonesLoaded) {
            (liveStatus.zones || []).forEach(addLiveZone);
            zonesLoaded = true;
        }
        const state = liveStatus.paused ? 'Tạm dừng' : liveStatus.connected ? 'Có tín hiệu' : 'Chưa có tín hiệu mới';
        const providers = liveStatus.providers || {};
        const device = Object.entries(providers).map(([name, values]) => `${name}: ${values[0]}`).join(', ');
        const gpu = Object.values(providers).some(values => values[0] === 'CUDAExecutionProvider');
        const metrics = document.getElementById('liveMetrics');
        metrics.textContent = `${state} · ${liveStatus.resolution?.join(' × ') || 'Chưa rõ độ phân giải'} · Camera ${liveStatus.capture_fps} FPS · AI ${liveStatus.ai_fps} lượt/s · ${liveStatus.ai_ms} ms/lượt · ${device ? (gpu ? 'GPU' : 'CPU') : 'Đang khởi tạo AI'}${liveStatus.error ? ' · Lỗi: ' + liveStatus.error : ''}`;
        metrics.title = device;
        const labels = {confirmed:'Đã xác nhận', pending:'Đang xác nhận', lost:'Tạm mất dấu', unknown:'Chưa xác định'};
        document.getElementById('livePeople').textContent = liveStatus.detections.map(d =>
            `${d.state === 'confirmed' || d.state === 'lost' ? d.name + ': ' : ''}${labels[d.state]} · ${d.zone} · mặt ${d.face_pixels}px${d.quality_reason ? ' (' + d.quality_reason + ')' : ''}`
        ).join(' | ') || 'Chưa có khuôn mặt được cập nhật.';
    } catch (error) {
        liveStatus = {detections: [], connected: false};
        document.getElementById('liveMetrics').textContent = error.message;
        document.getElementById('livePeople').textContent = '';
    } finally { setTimeout(refreshLiveStatus, 1000); }
}

document.addEventListener('DOMContentLoaded', refreshLiveStatus);
