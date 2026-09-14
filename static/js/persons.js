// --- QUẢN LÝ DỮ LIỆU NGƯỜI DÙNG & MẪU ẢNH KHUÔN MẶT ---

async function loadPersons() {
    const grid = document.getElementById('personCardGrid');
    if (!grid) return;

    try {
        const res = await fetch('/api/persons');
        const data = await res.json();

        if (!data.persons || data.persons.length === 0) {
            grid.innerHTML = `<p style="color: var(--text-sub); text-align: center; padding: 20px;">Chưa có dữ liệu khuôn mặt nào trong hệ thống.</p>`;
            return;
        }

        grid.innerHTML = data.persons.map(p => `
            <div class="person-card">
                <div class="person-info">
                    <h3><i class="fa-solid fa-user-tag" style="color: var(--primary);"></i> ${p.name}</h3>
                    <p>Số mẫu ảnh: <b style="color: var(--primary);">${p.sample_count}</b></p>
                </div>

                <input type="file" id="addMoreInput_${p.id}" accept="image/*" multiple style="display: none;" onchange="uploadMoreImages(${p.id}, '${p.name}')">

                <div class="person-actions">
                    <button class="btn btn-success" onclick="document.getElementById('addMoreInput_${p.id}').click()">
                        <i class="fa-solid fa-plus"></i> Thêm ảnh
                    </button>
                    <button class="btn btn-warning" onclick="openManageModal(${p.id}, '${p.name}')">
                        <i class="fa-solid fa-images"></i> Quản lý ảnh mẫu
                    </button>
                    <button class="btn btn-primary" onclick="renamePerson(${p.id}, '${p.name}')">
                        <i class="fa-solid fa-pen"></i> Đổi tên
                    </button>
                    <button class="btn btn-danger" onclick="deletePerson(${p.id})">
                        <i class="fa-solid fa-trash"></i> Xóa
                    </button>
                </div>
            </div>
        `).join('');
    } catch (err) {
        grid.innerHTML = `<p style="color: var(--danger); text-align: center;">Lỗi tải dữ liệu: ${err.message}</p>`;
    }
}

async function openManageModal(personId, personName) {
    currentPersonIdForModal = personId;
    if (personName) {
        currentPersonNameForModal = personName;
    }
    const modalTitle = document.getElementById('modalTitle');
    if (modalTitle) modalTitle.innerText = `Danh sách ảnh mẫu của: ${currentPersonNameForModal}`;
    const sampleModal = document.getElementById('sampleModal');
    if (sampleModal) sampleModal.style.display = 'flex';

    const listContainer = document.getElementById('sampleList');
    if (!listContainer) return;
    listContainer.innerHTML = `<p style="color: var(--text-sub); text-align: center;">Đang tải dữ liệu...</p>`;

    try {
        const res = await fetch(`/api/person_embeddings?person_id=${personId}`);
        if (!res.ok) throw new Error(`Mã lỗi: ${res.status}`);

        const data = await res.json();
        const samples = data.embeddings || [];

        if (samples.length === 0) {
            listContainer.innerHTML = `<p style="color: var(--text-sub); text-align: center;">Không có mẫu ảnh nào.</p>`;
        } else {
            listContainer.innerHTML = samples.map((item, index) => {
                const imgSrc = item.image_path ? `${item.image_path}` : '';
                const imgHtml = imgSrc
                    ? `<img src="${imgSrc}" class="sample-thumb" alt="Mẫu ${index + 1}">`
                    : `<div class="sample-thumb" style="display:flex;align-items:center;justify-content:center;color:var(--text-sub);"><i class="fa-solid fa-image"></i></div>`;

                return `
                    <div class="sample-item">
                        <div style="display: flex; align-items: center; gap: 12px;">
                            ${imgHtml}
                            <span style="font-size: 0.9rem; font-weight: 500;">Mẫu ảnh #${index + 1}</span>
                        </div>
                        <button class="btn btn-danger" onclick="deleteSingleSample(${item.id})">
                            <i class="fa-solid fa-trash"></i> Xóa
                        </button>
                    </div>
                `;
            }).join('');
        }
    } catch (err) {
        listContainer.innerHTML = `<p style="color: var(--danger); text-align: center;">${err.message}</p>`;
    }
}

async function deleteSingleSample(embeddingId) {
    if (confirm("Bạn có chắc muốn xóa mẫu ảnh này?")) {
        const res = await fetch(`/api/embeddings/${embeddingId}`, { method: 'DELETE' });
        if (res.ok) {
            openManageModal(currentPersonIdForModal, null);
            loadPersons();
        } else {
            alert("Xóa thất bại!");
        }
    }
}

function closeModal() {
    const sampleModal = document.getElementById('sampleModal');
    if (sampleModal) sampleModal.style.display = 'none';
}

async function uploadMoreImages(personId, personName) {
    const input = document.getElementById(`addMoreInput_${personId}`);
    if (!input || !input.files || input.files.length === 0) return;

    const formData = new FormData();
    formData.append('name', personName);
    for (let i = 0; i < input.files.length; i++) {
        formData.append('files', input.files[i]);
    }

    const res = await fetch('/api/register', { method: 'POST', body: formData });
    const data = await res.json();
    alert(data.message);
    loadPersons();
}

async function renamePerson(id, oldName) {
    const newName = prompt("Nhập tên mới:", oldName);
    if (newName && newName !== oldName) {
        const formData = new FormData();
        formData.append('person_id', id);
        formData.append('new_name', newName);
        await fetch('/api/persons/rename', { method: 'PUT', body: formData });
        loadPersons();
    }
}

async function deletePerson(id) {
    if (confirm("Xóa hoàn toàn người này khỏi hệ thống?")) {
        await fetch(`/api/persons/${id}`, { method: 'DELETE' });
        loadPersons();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const registerForm = document.getElementById('registerForm');
    if (registerForm) {
        registerForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = document.getElementById('personName').value;
            const files = document.getElementById('faceImageInput').files;

            const formData = new FormData();
            formData.append('name', name);
            for (let i = 0; i < files.length; i++) {
                formData.append('files', files[i]);
            }

            const res = await fetch('/api/register', { method: 'POST', body: formData });
            const data = await res.json();
            alert(data.message);
            if (data.status === 'success') {
                registerForm.reset();
                loadPersons();
            }
        });
    }
});
