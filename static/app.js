// ============================================================
//  SECURE VOTING SYSTEM — app.js (Real-Time Face Scan Edition)
// ============================================================

// ── State ──────────────────────────────────────────────────
let currentStream       = null;
let faceMeshReady       = false;
let faceMesh            = null;
let scanIntervalId      = null;
let scanLocked          = false;      // true once a result arrives
let scanResult          = null;       // last scan result object
let selectedCandidateId = null;
let lastBiometricData   = null;

// ── DOM shortcuts ───────────────────────────────────────────
const steps = {
    biometrics: document.getElementById('step-biometrics'),
    review:     document.getElementById('step-review'),
    vote:       document.getElementById('step-vote'),
    success:    document.getElementById('step-success')
};

function switchStep(stepId) {
    Object.values(steps).forEach(el => el.classList.remove('active'));
    steps[stepId].classList.add('active');
}

// ── WebSocket (for remote mobile mode) ─────────────────────
const socket = io();
socket.emit('join', { session_id: SESSION_ID });

const remoteStreamTarget = document.getElementById('remote-stream-target');
const qrOverlay          = document.getElementById('qr-overlay');
const videoContainer     = document.querySelector('.video-container');

socket.on('remote_video_frame', (data) => {
    qrOverlay.style.display        = 'none';
    remoteStreamTarget.style.display = 'block';
    remoteStreamTarget.src          = data.image;
    videoContainer.classList.add('laser-scanning');
});

socket.on('remote_biometric_captured', (data) => {
    videoContainer.classList.remove('laser-scanning');
    remoteStreamTarget.style.display = 'none';
    // In remote mode just show the scan overlay directly
    showScanOverlay({ status: 'SCANNING' });
});

// ============================================================
//  STEP 1 — REAL-TIME FACE SCAN
// ============================================================
const video         = document.getElementById('video-stream');
const canvas        = document.getElementById('canvas-snap');
const scanOverlay   = document.getElementById('scan-result-overlay');
const cameraSelect  = document.getElementById('camera-select');

// ── Load MediaPipe FaceMesh from CDN ───────────────────────
function initFaceMesh() {
    if (typeof FaceMesh === 'undefined') {
        console.warn('FaceMesh not loaded yet — retrying in 1s');
        setTimeout(initFaceMesh, 1000);
        return;
    }
    faceMesh = new FaceMesh({
        locateFile: (file) =>
            `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh@0.4/${file}`
    });
    faceMesh.setOptions({
        maxNumFaces:           1,
        refineLandmarks:       true,
        minDetectionConfidence: 0.5,
        minTrackingConfidence:  0.5
    });
    faceMesh.onResults(onFaceMeshResults);
    faceMeshReady = true;
    console.log('✅ FaceMesh ready');
}

// ── Handle FaceMesh frame results ─────────────────────────
function onFaceMeshResults(results) {
    if (scanLocked) return; // don't fire while waiting for server
    if (!results.multiFaceLandmarks || results.multiFaceLandmarks.length === 0) {
        updateScanStatus('no_face');
        return;
    }
    updateScanStatus('detecting');
}

// ── Continuous scan loop ──────────────────────────────────
function startScanLoop() {
    if (scanIntervalId) clearInterval(scanIntervalId);
    scanIntervalId = setInterval(async () => {
        if (scanLocked || !faceMeshReady || !faceMesh) return;
        if (!video.srcObject || video.readyState < 2) return;

        // Grab current frame
        canvas.width  = video.videoWidth  || 640;
        canvas.height = video.videoHeight || 480;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

        // Create an ImageBitmap and send to FaceMesh
        const bitmap = await createImageBitmap(canvas);
        await faceMesh.send({ image: bitmap });

        // Re-run landmark extraction manually so we can get the vector
        await extractAndSubmit(ctx);
    }, 600); // every 600ms
}

async function extractAndSubmit(ctx) {
    if (scanLocked) return;

    // We already called faceMesh.send() — but to get the landmark vector
    // we use a second lightweight pass via the same faceMesh instance.
    // Actually we capture result inside onFaceMeshResults; instead let's
    // do the vector extraction directly by posting the canvas frame as
    // base64 to /api/scan once landmarks are available.
    //
    // Better pattern: detect inside onFaceMeshResults with latestLandmarks.
}

// ── Better approach: store latest landmarks each frame ─────
let latestLandmarks = null;

// Override onResults to capture landmark vector
function initFaceMeshWithCapture() {
    if (typeof FaceMesh === 'undefined') {
        setTimeout(initFaceMeshWithCapture, 1000);
        return;
    }
    faceMesh = new FaceMesh({
        locateFile: (file) =>
            `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh@0.4/${file}`
    });
    faceMesh.setOptions({
        maxNumFaces:            1,
        refineLandmarks:        true,
        minDetectionConfidence: 0.5,
        minTrackingConfidence:  0.5
    });
    faceMesh.onResults((results) => {
        if (!results.multiFaceLandmarks || results.multiFaceLandmarks.length === 0) {
            latestLandmarks = null;
            updateScanStatus('no_face');
        } else {
            latestLandmarks = results.multiFaceLandmarks[0];
            updateScanStatus('detecting');
        }
    });
    faceMeshReady = true;
    console.log('✅ FaceMesh ready (with capture)');
}

// ── The real scan loop ─────────────────────────────────────
function startRealScanLoop() {
    if (scanIntervalId) clearInterval(scanIntervalId);
    scanIntervalId = setInterval(async () => {
        if (scanLocked || !faceMeshReady || !faceMesh) return;
        if (!video.srcObject || video.readyState < 2) return;

        // Draw current frame to hidden canvas
        canvas.width  = video.videoWidth  || 640;
        canvas.height = video.videoHeight || 480;
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);

        // Run MediaPipe
        try {
            await faceMesh.send({ image: video });
        } catch (e) {
            console.warn('FaceMesh send error:', e);
            return;
        }

        // If we got landmarks, send to backend
        if (!latestLandmarks || scanLocked) return;

        // Flatten 468 x 3 → 1404 floats
        const vector = [];
        for (const lm of latestLandmarks) {
            vector.push(lm.x, lm.y, lm.z);
        }

        // Lock so we don't flood
        scanLocked = true;
        updateScanStatus('scanning');

        try {
            const res  = await fetch('/api/scan', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ landmarks: vector })
            });
            const data = await res.json();
            handleScanResult(data);
        } catch (err) {
            console.error('Scan fetch error:', err);
            scanLocked = false; // retry
        }
    }, 700);
}

// ── Handle scan result from backend ──────────────────────
function handleScanResult(data) {
    scanResult = data;
    showScanOverlay(data);
}

// ── HUD status label (small text above scan area) ─────────
function updateScanStatus(state) {
    const el = document.getElementById('scan-status-label');
    if (!el) return;
    switch (state) {
        case 'no_face':   el.textContent = '👁 Align face in frame…';      el.className = 'scan-label label-waiting';   break;
        case 'detecting': el.textContent = '📡 Face detected — scanning…'; el.className = 'scan-label label-detecting'; break;
        case 'scanning':  el.textContent = '⚡ Analysing biometrics…';     el.className = 'scan-label label-scanning';  break;
    }
}

// ── Big result overlay ─────────────────────────────────────
function showScanOverlay(data) {
    const overlay = document.getElementById('scan-result-overlay');
    if (!overlay) return;

    overlay.className = 'scan-overlay visible';

    if (data.status === 'VALID') {
        overlay.innerHTML = `
            <div class="scan-verdict valid">
                <div class="verdict-icon">✅</div>
                <div class="verdict-title">VALID</div>
                <div class="verdict-name">${data.name}</div>
                <div class="verdict-sub">Identity confirmed — proceeding to ballot</div>
            </div>`;
        lastBiometricData = data;
        // After 2 seconds, move to review
        setTimeout(() => {
            stopScanLoop();
            stopCamera();
            loadReviewData();
        }, 2000);

    } else if (data.status === 'ALREADY_SCANNED') {
        overlay.innerHTML = `
            <div class="scan-verdict invalid">
                <div class="verdict-icon">🔴</div>
                <div class="verdict-title">INVALID</div>
                <div class="verdict-name">${data.name}</div>
                <div class="verdict-sub">This person has already been scanned / voted</div>
            </div>`;
        // Unlock after 3 seconds so they can try again / next person
        setTimeout(() => {
            overlay.className = 'scan-overlay';
            scanLocked = false;
            updateScanStatus('no_face');
        }, 3000);

    } else if (data.status === 'INVALID') {
        overlay.innerHTML = `
            <div class="scan-verdict invalid">
                <div class="verdict-icon">❌</div>
                <div class="verdict-title">INVALID</div>
                <div class="verdict-name">Unknown Person</div>
                <div class="verdict-sub">Face not in authorised database</div>
            </div>`;
        setTimeout(() => {
            overlay.className = 'scan-overlay';
            scanLocked = false;
            updateScanStatus('no_face');
        }, 2500);

    } else if (data.status === 'NO_FACE') {
        // silently ignore, just unlock
        scanLocked = false;
    } else {
        // ERROR or SCANNING state
        scanLocked = false;
    }
}

function stopScanLoop() {
    if (scanIntervalId) clearInterval(scanIntervalId);
    scanIntervalId = null;
}

function stopCamera() {
    if (currentStream) {
        currentStream.getTracks().forEach(t => t.stop());
        currentStream = null;
    }
}

// ── Camera setup ───────────────────────────────────────────
async function getCameras() {
    try {
        await navigator.mediaDevices.getUserMedia({ video: true });
        const devices     = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices.filter(d => d.kind === 'videoinput');

        cameraSelect.innerHTML = '<option value="remote_qr">📶 Scan QR Code (Wireless)</option>';
        videoDevices.forEach((device, i) => {
            const opt   = document.createElement('option');
            opt.value   = device.deviceId;
            opt.text    = device.label || `Camera ${i + 1}`;
            cameraSelect.appendChild(opt);
        });

        // Default: use first real camera if available, else QR
        if (videoDevices.length > 0) {
            cameraSelect.value = videoDevices[0].deviceId;
            startCamera(videoDevices[0].deviceId);
        } else {
            startCamera('remote_qr');
        }
    } catch (err) {
        console.warn('Camera access denied:', err);
        showCameraError();
    }
}

async function startCamera(deviceId) {
    stopCamera();
    stopScanLoop();

    const overlay = document.getElementById('scan-result-overlay');
    if (overlay) overlay.className = 'scan-overlay';
    scanLocked = false;
    latestLandmarks = null;

    if (deviceId === 'remote_qr') {
        video.style.display              = 'none';
        remoteStreamTarget.style.display = 'none';
        const urlObj = `http://${SERVER_IP}:5000/mobile?session_id=${SESSION_ID}`;
        document.getElementById('qr-code-img').src =
            `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(urlObj)}&color=0f172a&bgcolor=10b981`;
        qrOverlay.style.display = 'flex';
        return;
    }

    qrOverlay.style.display              = 'none';
    remoteStreamTarget.style.display     = 'none';
    video.style.display                  = 'block';

    try {
        currentStream = await navigator.mediaDevices.getUserMedia({
            video: { deviceId: deviceId ? { exact: deviceId } : undefined }
        });
        video.srcObject = currentStream;
        await new Promise(res => { video.onloadedmetadata = res; });
        videoContainer.classList.remove('laser-scanning');

        // Start scan loop now that camera is live
        startRealScanLoop();
        updateScanStatus('no_face');
    } catch (err) {
        console.error('Error starting camera:', err);
        showCameraError();
    }
}

function showCameraError() {
    video.style.display = 'none';
    const overlay = document.getElementById('scan-result-overlay');
    if (overlay) {
        overlay.className = 'scan-overlay visible';
        overlay.innerHTML = `
            <div class="scan-verdict invalid">
                <div class="verdict-icon">📷</div>
                <div class="verdict-title">Camera Error</div>
                <div class="verdict-sub">Allow camera access and reload the page</div>
            </div>`;
    }
}

cameraSelect.addEventListener('change', (e) => startCamera(e.target.value));
window.addEventListener('DOMContentLoaded', () => {
    initFaceMeshWithCapture();
    getCameras();
});

// ============================================================
//  STEP 2 — REVIEW
// ============================================================
async function loadReviewData() {
    try {
        const res   = await fetch('/api/details');
        const voter = await res.json();
        if (!res.ok) throw new Error(voter.error);

        document.getElementById('rev-name').textContent     = voter.name;
        document.getElementById('rev-father').textContent   = voter.father_name;
        document.getElementById('rev-sex').textContent      = voter.sex;
        document.getElementById('rev-age').textContent      = voter.age;
        document.getElementById('rev-aadhaar').textContent  = voter.aadhaar_number;
        document.getElementById('rev-id').textContent       = voter.id_card_number;
        document.getElementById('rev-voter-id').textContent = voter.voter_id_number;
        document.getElementById('rev-address').textContent  = voter.address;

        // Face image from DB (may be null)
        const faceEl = document.getElementById('rev-face');
        if (voter.face_data) {
            faceEl.src = voter.face_data;
            faceEl.style.display = 'block';
        } else {
            faceEl.style.display = 'none';
        }

        if (lastBiometricData) displayTechnicalAnalysis(lastBiometricData);

        switchStep('review');
    } catch (err) {
        alert('Failed to load review data: ' + err.message);
    }
}

function displayTechnicalAnalysis(data) {
    const landmarkList = document.getElementById('landmark-stats');
    const matrixGrid   = document.getElementById('matrix-display');
    if (!landmarkList || !matrixGrid) return;
    landmarkList.innerHTML = '';
    matrixGrid.innerHTML   = '';

    if (data.landmarks) {
        Object.entries(data.landmarks).forEach(([feature, count]) => {
            const item = document.createElement('div');
            item.className = 'landmark-item';
            item.innerHTML = `<span>${feature.replace(/_/g, ' ')}</span> <strong>${count}</strong>`;
            landmarkList.appendChild(item);
        });
    }

    if (data.matrix) {
        data.matrix.forEach((val, i) => {
            const cell = document.createElement('div');
            cell.className = 'matrix-cell';
            const intensity = Math.abs(val) * 255;
            cell.style.backgroundColor = `rgba(16,185,129,${Math.min(1, intensity)})`;
            setTimeout(() => matrixGrid.appendChild(cell), i * 5);
        });
    }
}

document.getElementById('btn-confirm-review').addEventListener('click', loadCandidates);

// ============================================================
//  STEP 3 — VOTE
// ============================================================
async function loadCandidates() {
    try {
        const res        = await fetch('/api/candidates');
        const candidates = await res.json();
        const container  = document.getElementById('candidates-container');
        container.innerHTML = '';

        candidates.forEach(c => {
            const el = document.createElement('div');
            el.className = 'candidate-card';
            el.innerHTML = `
                <div><div class="candidate-name">${c.name}</div></div>
                <i class='bx bx-circle bx-sm' id="icon-${c.id}"></i>`;
            el.addEventListener('click', () => {
                document.querySelectorAll('.candidate-card').forEach(n => n.classList.remove('selected'));
                document.querySelectorAll('.candidate-card i').forEach(n => {
                    n.classList.remove('bx-check-circle'); n.classList.add('bx-circle');
                });
                el.classList.add('selected');
                const icon = document.getElementById(`icon-${c.id}`);
                icon.classList.remove('bx-circle'); icon.classList.add('bx-check-circle');
                selectedCandidateId = c.id;
                document.getElementById('btn-cast-vote').disabled = false;
            });
            container.appendChild(el);
        });

        switchStep('vote');
    } catch (err) {
        alert('Failed to load candidates');
    }
}

document.getElementById('btn-cast-vote').addEventListener('click', async () => {
    if (!selectedCandidateId) return;
    try {
        const res  = await fetch('/api/vote', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ candidate_id: selectedCandidateId })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);

        switchStep('success');

        let timeLeft  = 5;
        const noteEl  = document.getElementById('auto-reset-note');
        noteEl.innerHTML = `<i class='bx bx-refresh bx-spin'></i> Auto-reset in <b>${timeLeft}s</b>…`;
        const timer = setInterval(() => {
            timeLeft--;
            if (timeLeft <= 0) { clearInterval(timer); resetForNextVoter(); }
            else noteEl.innerHTML = `<i class='bx bx-refresh bx-spin'></i> Auto-reset in <b>${timeLeft}s</b>…`;
        }, 1000);
        window.activeResetTimer = timer;
    } catch (err) {
        document.getElementById('vote-error').textContent = err.message;
    }
});

// ============================================================
//  RESET FOR NEXT VOTER
// ============================================================
async function resetForNextVoter() {
    if (window.activeResetTimer) { clearInterval(window.activeResetTimer); window.activeResetTimer = null; }

    // State
    selectedCandidateId = null;
    lastBiometricData   = null;
    scanResult          = null;
    scanLocked          = false;
    latestLandmarks     = null;

    // Clear overlay
    const overlay = document.getElementById('scan-result-overlay');
    if (overlay) overlay.className = 'scan-overlay';

    // Reset candidates
    document.getElementById('candidates-container').innerHTML = '';
    document.getElementById('btn-cast-vote').disabled = true;
    document.getElementById('auto-reset-note').textContent = '';

    // Reset review
    document.getElementById('rev-name').textContent = '';
    const revFace = document.getElementById('rev-face');
    revFace.src = ''; revFace.style.display = 'none';

    // Go back to step 1
    switchStep('biometrics');
    // Restart camera
    startCamera(cameraSelect.value);
}

// ============================================================
//  DEMO RESET (full DB wipe)
// ============================================================
document.getElementById('btn-reset-demo').addEventListener('click', async () => {
    if (!confirm('Reset ALL votes and biometric session locks?')) return;
    try {
        const res  = await fetch('/api/reset', { method: 'POST' });
        const data = await res.json();
        alert(data.message);
        location.reload();
    } catch (err) {
        alert('Reset failed: ' + err);
    }
});

// ============================================================
//  3D CARD HOVER
// ============================================================
document.addEventListener('mousemove', (e) => {
    document.querySelectorAll('.card-3d').forEach(card => {
        const rect = card.getBoundingClientRect();
        if (e.clientX >= rect.left && e.clientX <= rect.right &&
            e.clientY >= rect.top  && e.clientY <= rect.bottom) {
            const x = e.clientX - rect.left, y = e.clientY - rect.top;
            const cx = rect.width / 2,       cy = rect.height / 2;
            card.style.transform  = `perspective(1000px) rotateX(${((y-cy)/cy)*-10}deg) rotateY(${((x-cx)/cx)*10}deg) scale3d(1.02,1.02,1.02)`;
            card.style.boxShadow  = '0 20px 40px rgba(0,0,0,0.4)';
        } else {
            card.style.transform  = 'perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1,1,1)';
            card.style.boxShadow  = 'none';
        }
    });
});

// ============================================================
//  HARDWARE MANAGER MODAL
// ============================================================
const hwModal = document.getElementById('hw-modal');
document.getElementById('btn-open-hw').addEventListener('click', () => hwModal.classList.add('open'));
document.getElementById('close-hw').addEventListener('click',   () => hwModal.classList.remove('open'));

document.getElementById('btn-hw-usb').addEventListener('click', async () => {
    try {
        const device = await navigator.usb.requestDevice({ filters: [] });
        alert('Paired USB Device: ' + (device.productName || 'Unknown biometric device'));
        hwModal.classList.remove('open');
    } catch (err) {
        alert('USB integration closed or an error occurred.');
    }
});
document.getElementById('btn-hw-sim').addEventListener('click', () => {
    alert('Scanning for Bluetooth devices… (Requires Web Bluetooth API + HTTPS)');
});
document.getElementById('btn-hw-fido').addEventListener('click', () => {
    alert('Use the main fingerprint panel to invoke hardware FIDO2 authenticators.');
    hwModal.classList.remove('open');
});

// ============================================================
//  FINGERPRINT PANEL (kept for UI completeness)
// ============================================================
const fpArea   = document.getElementById('fp-area');
const fpStatus = document.getElementById('fp-status');
let fingerprintScanned = false;

fpArea.addEventListener('click', async () => {
    if (fingerprintScanned) return;
    fpArea.classList.add('scanning');
    fpStatus.textContent = 'Requesting Hardware Sensor…';
    try {
        if (window.PublicKeyCredential) {
            const challenge = new Uint8Array(32);
            window.crypto.getRandomValues(challenge);
            await navigator.credentials.create({
                publicKey: {
                    challenge,
                    rp:   { name: 'Secure Voting Database', id: window.location.hostname },
                    user: { id: new Uint8Array(16), name: 'identity@voting', displayName: 'Hardware Biometric Link' },
                    pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
                    authenticatorSelection: { authenticatorAttachment: 'platform', userVerification: 'required' },
                    timeout: 60000
                }
            });
            fpStatus.textContent = 'Hardware Scan Complete!';
        } else throw new Error('WebAuthn not supported');
    } catch {
        fpStatus.textContent = 'Analysing Print Simulation…';
        await new Promise(r => setTimeout(r, 1500));
        fpStatus.textContent = 'Scan Complete';
    }
    fpArea.classList.remove('scanning');
    fpArea.classList.add('success');
    fingerprintScanned = true;
});

// ============================================================
//  ENROLLMENT MODAL (unchanged functionality)
// ============================================================
const enrollModal       = document.getElementById('enroll-modal');
const enrollNameInput   = document.getElementById('enroll-name');
const btnConfirmEnroll  = document.getElementById('btn-confirm-enroll');

document.getElementById('btn-open-enroll').addEventListener('click', () => enrollModal.classList.add('open'));
document.getElementById('close-enroll').addEventListener('click',   () => enrollModal.classList.remove('open'));

enrollNameInput.addEventListener('input', checkEnrollmentReady);

function checkEnrollmentReady() {
    const ready = enrollNameInput.value.trim().length > 2;
    btnConfirmEnroll.disabled = !ready;
    if (ready) btnConfirmEnroll.classList.add('glow-pulse');
    else        btnConfirmEnroll.classList.remove('glow-pulse');
}

btnConfirmEnroll.addEventListener('click', async () => {
    const name    = enrollNameInput.value.trim();
    const errorEl = document.getElementById('enroll-error');
    errorEl.textContent = '';
    btnConfirmEnroll.disabled  = true;
    btnConfirmEnroll.textContent = 'Integrating Biometric Profile…';

    // Capture a frame from the live camera for enrollment
    let faceData = null;
    if (video.srcObject && video.readyState >= 2) {
        canvas.width  = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0);
        faceData = canvas.toDataURL('image/jpeg');
    }

    if (!faceData) {
        errorEl.textContent = 'Point camera at face first.';
        btnConfirmEnroll.disabled = false;
        btnConfirmEnroll.textContent = 'Securely Link Identity';
        return;
    }

    try {
        const res  = await fetch('/api/enroll', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ name, face_data: faceData })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Enrollment failed');
        alert(data.message);
        enrollModal.classList.remove('open');
    } catch (err) {
        errorEl.textContent = 'Enrollment Error: ' + err.message;
        btnConfirmEnroll.disabled    = false;
        btnConfirmEnroll.textContent = 'Securely Link Identity';
    }
});
