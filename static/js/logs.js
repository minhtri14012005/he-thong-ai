let currentLogViewMode = 'grouped';
let currentLogPersonFilter = 'all';

function setLogViewMode(mode) {
    currentLogViewMode = mode;
    document.getElementById('btnViewGrouped').classList.toggle('active', mode === 'grouped');
    document.getElementById('btnViewTimeline').classList.toggle('active', mode === 'timeline');
    document.getElementById('logGroupedContainer').style.display = mode === 'grouped' ? 'block' : 'none';
    document.getElementById('logTimelineContainer').style.display = mode === 'timeline' ? 'block' : 'none';
}

function filterLogsByPerson(name) {
    currentLogPersonFilter = name;
    fetchAndRenderLogs();
}

async function clearLiveLogs() {
    if (!confirm('Xóa toàn bộ lịch sử nhật ký camera hiện tại?')) return;
    try {
        const res = await fetch('/api/logs', {method:'DELETE'});
        if (!res.ok) throw new Error('Không xóa được nhật ký');
        currentLogPersonFilter = 'all';
        await fetchAndRenderLogs();
    } catch (error) { showToast(error.message, true); }
}

function evidenceLinks(log) {
    return [['face_path','Ảnh mặt'],['snapshot_path','Toàn cảnh']].map(([key,label]) => {
        const path = log[key];
        return typeof path === 'string' && path.startsWith('/static/snapshots/')
            ? `<a href="${escapeLive(path)}" target="_blank" rel="noopener">${label}</a>` : '';
    }).filter(Boolean).join(' · ');
}

async function fetchAndRenderLogs() {
    const section = document.getElementById('camSection');
    if (!section || section.style.display === 'none') return;
    try {
        const url = currentLogPersonFilter === 'all' ? '/api/logs' : `/api/logs?person=${encodeURIComponent(currentLogPersonFilter)}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error('Không tải được nhật ký');
        const data = await res.json();
        const people = data.people_groups || [];
        const pills = document.getElementById('logFilterPills');
        pills.replaceChildren();
        [{name:'all',label:'Tất cả'}, ...people.map(p=>({name:p.name,label:`${p.name} (${p.total_count})`}))].forEach(p => {
            const btn = document.createElement('button');
            btn.type = 'button'; btn.className = 'filter-pill';
            btn.classList.toggle('active', p.name === currentLogPersonFilter);
            btn.textContent = p.label; btn.onclick = () => filterLogsByPerson(p.name);
            pills.appendChild(btn);
        });
        const selected = people.filter(p => currentLogPersonFilter === 'all' || p.name === currentLogPersonFilter);
        document.getElementById('logGroupedContainer').innerHTML = selected.map(p => {
            const present = liveStatus.connected && !liveStatus.paused && liveStatus.detections.some(d => d.state === 'confirmed' && d.name === p.name);
            return `<div class="live-person-card ${present ? 'active-presence' : ''}">
                <div class="live-person-header"><div>
                    <h4 class="live-person-name">${escapeLive(p.name)}</h4>
                    <div class="live-person-status">${present ? 'Đã xác nhận trong hình hiện tại' : 'Chưa có xác nhận mới'} · Thấy cuối: ${escapeLive(p.last_seen)}</div>
                </div><span class="count-badge">${p.total_count} lượt</span></div>
                <div class="live-history-list">${p.recent_logs.map(log => `<div class="live-history-row">
                    <span>${escapeLive(log.time)} · ${escapeLive(log.zone || 'Log cũ')} · ${escapeLive(log.source || '')}<br>${evidenceLinks(log)}</span>
                    <span title="Điểm tương đồng, không phải xác suất đúng">${escapeLive(log.confidence)}</span>
                </div>`).join('')}</div></div>`;
        }).join('') || '<p>Chưa có lượt xuất hiện được xác nhận.</p>';
        document.getElementById('logTableBody').innerHTML = (data.logs || []).map(log => `<tr>
            <td>${escapeLive(log.name)}<br><small>${escapeLive(log.zone || '')}</small></td>
            <td title="Điểm tương đồng, không phải xác suất đúng">${escapeLive(log.confidence)}</td>
            <td>${escapeLive(log.time)}<br>${evidenceLinks(log)}</td>
        </tr>`).join('') || '<tr><td colspan="3">Chưa có lượt xuất hiện được xác nhận.</td></tr>';
    } catch (error) { console.error(error); }
}

function startLiveLogPolling() {
    const poll = async () => {
        await fetchAndRenderLogs();
        setTimeout(poll, 1200);
    };
    poll();
}
