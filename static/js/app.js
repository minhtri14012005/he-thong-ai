// --- BIẾN TOÀN CỤC & TRẠNG THÁI ỨNG DỤNG ---
let currentSource = 'webcam';
let isPausedState = false;
let autoZoomEnabled = false;
let isVideoPlayerVisible = true;
let currentPersonIdForModal = null;
let currentPersonNameForModal = '';

let currentJobId = null;
let pollInterval = null;
let lastDetectionId = 0;

// Dữ liệu gom nhóm: person_name -> { name, maxConf, count, appearances: [{ sec, str, snap, conf }] }
let detectedPersonsMap = {};

// Chuyển đổi giữa các Tab chính
function switchTab(type) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));

    document.getElementById('camSection').style.display = 'none';
    document.getElementById('videoSection').style.display = 'none';
    document.getElementById('manageSection').style.display = 'none';

    if (type === 'cam') {
        document.getElementById('camTabBtn').classList.add('active');
        document.getElementById('camSection').style.display = 'grid';
        if (typeof changeCameraSource === 'function') changeCameraSource();
    } else if (type === 'file') {
        document.getElementById('fileTabBtn').classList.add('active');
        document.getElementById('videoSection').style.display = 'flex';
        if (typeof stopStream === 'function') stopStream();
    } else if (type === 'manage') {
        document.getElementById('manageTabBtn').classList.add('active');
        document.getElementById('manageSection').style.display = 'block';
        if (typeof stopStream === 'function') stopStream();
        if (typeof loadPersons === 'function') loadPersons();
    }
}

// Hiển thị thông báo Toast góc trên bên phải
function showToast(message, isError = false) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast';
    if (isError) {
        toast.style.borderColor = 'var(--danger)';
        toast.style.borderLeftColor = 'var(--danger)';
    }
    toast.innerHTML = `
        <i class="${isError ? 'fa-solid fa-triangle-exclamation' : 'fa-solid fa-bell'}" style="color: ${isError ? 'var(--danger)' : 'var(--primary)'}; font-size: 1.1rem;"></i>
        <div style="flex: 1;">${message}</div>
    `;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.transition = 'opacity 0.4s, transform 0.4s';
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 400);
    }, 4000);
}

// Khởi tạo các sự kiện khi tải trang
document.addEventListener('DOMContentLoaded', () => {
    if (typeof loadPersons === 'function') loadPersons();
    if (typeof changeCameraSource === 'function') changeCameraSource();
    if (typeof startLiveLogPolling === 'function') startLiveLogPolling();
});
