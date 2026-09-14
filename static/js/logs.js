// --- QUẢN LÝ NHẬT KÝ CAMERA REALTIME ---

let currentLogViewMode = 'grouped'; // 'grouped' hoặc 'timeline'
let currentLogPersonFilter = 'all';

function setLogViewMode(mode) {
    currentLogViewMode = mode;
    const btnGrouped = document.getElementById('btnViewGrouped');
    const btnTimeline = document.getElementById('btnViewTimeline');
    const grpBox = document.getElementById('logGroupedContainer');
    const timeBox = document.getElementById('logTimelineContainer');
    if (btnGrouped && btnTimeline) {
        btnGrouped.classList.toggle('active', mode === 'grouped');
        btnTimeline.classList.toggle('active', mode === 'timeline');
    }
    if (grpBox && timeBox) {
        grpBox.style.display = (mode === 'grouped') ? 'block' : 'none';
        timeBox.style.display = (mode === 'timeline') ? 'block' : 'none';
    }
}

function filterLogsByPerson(name) {
    currentLogPersonFilter = name;
    document.querySelectorAll('#logFilterPills .filter-pill').forEach(btn => {
        if (btn.getAttribute('data-person') === name) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    fetchAndRenderLogs();
}

async function clearLiveLogs() {
    if (!confirm("Bạn có chắc chắn muốn xóa toàn bộ lịch sử nhật ký camera hiện tại?")) return;
    try {
        const res = await fetch('/api/logs', { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'success') {
            currentLogPersonFilter = 'all';
            fetchAndRenderLogs();
        }
    } catch (e) {
        alert("Lỗi khi xóa nhật ký: " + e.message);
    }
}

async function fetchAndRenderLogs() {
    const camSection = document.getElementById('camSection');
    if (!camSection || camSection.style.display === 'none') return;

    try {
        const url = currentLogPersonFilter && currentLogPersonFilter !== 'all' 
            ? `/api/logs?person=${encodeURIComponent(currentLogPersonFilter)}` 
            : '/api/logs';
        const res = await fetch(url);
        const data = await res.json();

        const people = data.people_groups || [];
        const logs = data.logs || [];

        // 1. Cập nhật thanh Filter Pills
        const pillsContainer = document.getElementById('logFilterPills');
        if (pillsContainer) {
            const totalAllCount = people.reduce((acc, p) => acc + (p.total_count || 0), 0);
            let pillsHtml = `
                <button type="button" class="filter-pill ${currentLogPersonFilter === 'all' ? 'active' : ''}" data-person="all" onclick="filterLogsByPerson('all')">
                    Tất Cả (${totalAllCount})
                </button>
            `;
            people.forEach(p => {
                const isActive = currentLogPersonFilter === p.name ? 'active' : '';
                pillsHtml += `
                    <button type="button" class="filter-pill ${isActive}" data-person="${p.name}" onclick="filterLogsByPerson('${p.name}')">
                        <i class="fa-solid fa-user"></i> ${p.name} (${p.total_count})
                    </button>
                `;
            });
            pillsContainer.innerHTML = pillsHtml;
        }

        // 2. Cập nhật Chế độ 1: Danh sách nhóm theo từng người
        const groupedContainer = document.getElementById('logGroupedContainer');
        if (groupedContainer) {
            let displayPeople = people;
            if (currentLogPersonFilter !== 'all') {
                displayPeople = people.filter(p => p.name === currentLogPersonFilter);
            }

            if (displayPeople.length === 0) {
                groupedContainer.innerHTML = `
                    <div style="text-align: center; color: var(--text-sub); padding: 40px 10px;">
                        <i class="fa-solid fa-user-clock" style="font-size: 2.2rem; opacity: 0.4; margin-bottom: 8px; display: block; color: var(--primary);"></i>
                        Chưa có phát hiện nào
                    </div>
                `;
            } else {
                const nowTime = new Date().getTime();
                groupedContainer.innerHTML = displayPeople.map(p => {
                    let isPresent = false;
                    if (p.last_detected_at) {
                        const lastDt = new Date(p.last_detected_at.replace(' ', 'T')).getTime();
                        if (!isNaN(lastDt) && (nowTime - lastDt) < 12000) {
                            isPresent = true;
                        }
                    }

                    const statusHtml = isPresent
                        ? `<span class="live-presence-dot"></span> <span style="color: var(--success); font-weight: 600;">Đang có mặt</span>`
                        : `<i class="fa-regular fa-clock"></i> Lần cuối: ${p.last_seen || ''}`;

                    const avatarHtml = p.avatar
                        ? `<img src="/${p.avatar}" class="live-person-avatar" alt="${p.name}">`
                        : `<div class="live-person-avatar">${p.name.charAt(0).toUpperCase()}</div>`;

                    const historyRowsHtml = (p.recent_logs || []).map(r => `
                        <div class="live-history-row">
                            <span><i class="fa-regular fa-circle-dot" style="font-size: 0.65rem; color: var(--primary); margin-right: 4px;"></i> ${r.time}</span>
                            <span style="font-weight: 600; color: var(--text-main);">${r.confidence}</span>
                        </div>
                    `).join('');

                    return `
                        <div class="live-person-card ${isPresent ? 'active-presence' : ''}">
                            <div class="live-person-header">
                                <div class="live-person-title-box">
                                    ${avatarHtml}
                                    <div>
                                        <h4 class="live-person-name">${p.name}</h4>
                                        <div class="live-person-status">${statusHtml}</div>
                                    </div>
                                </div>
                                <div class="live-person-badges">
                                    <span class="count-badge"><i class="fa-solid fa-eye"></i> ${p.total_count} lần</span>
                                    <span class="conf-badge">Max: ${p.max_confidence}</span>
                                </div>
                            </div>
                            <div class="live-history-list">
                                ${historyRowsHtml || '<div style="color: var(--text-sub); font-size: 0.75rem;">Chưa có mốc thời gian</div>'}
                            </div>
                        </div>
                    `;
                }).join('');
            }
        }

        // 3. Cập nhật Chế độ 2: Bảng dòng thời gian
        const tbody = document.getElementById('logTableBody');
        if (tbody) {
            if (logs && logs.length > 0) {
                tbody.innerHTML = logs.map(log => `
                    <tr>
                        <td style="color: var(--primary); font-weight: 600;">
                            <i class="fa-solid fa-user" style="font-size: 0.75rem; margin-right: 4px;"></i>${log.name}
                        </td>
                        <td style="font-weight: 600;">${log.confidence}</td>
                        <td style="color: var(--text-sub);">${log.time}</td>
                    </tr>
                `).join('');
            } else {
                tbody.innerHTML = `<tr><td colspan="3" style="text-align: center; color: var(--text-sub);">Chưa có nhật ký phát hiện</td></tr>`;
            }
        }
    } catch (e) {
        console.error("Lỗi fetch log:", e);
    }
}

function startLiveLogPolling() {
    setInterval(fetchAndRenderLogs, 1200);
}
