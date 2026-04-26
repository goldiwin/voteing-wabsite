// State variables
let faceCapturedData = null;
let fingerprintScanned = false;
let selectedCandidateId = null;
let currentStream = null;
let lastBiometricData = null; // Technical analysis storage
let lastBiometricData = null; // Technical analysis storage

// DOM Elements
const steps = {
    biometrics: document.getElementById('step-biometrics'),
    review: document.getElementById('step-review'),
    vote: document.getElementById('step-vote'),
    success: document.getElementById('step-success')
};

// Navigation
function switchStep(stepId) {
    Object.values(steps).forEach(el => el.classList.remove('active'));
    steps[stepId].classList.add('active');
}

// -------------------------
// STEP 1: Biometrics
// -------------------------
const video = document.getElementById('video-stream');
const canvas = document.getElementById('canvas-snap');
const facePreview = document.getElementById('face-preview');
const btnSnap = document.getElementById('btn-snap');
const cameraSelect = document.getElementById('camera-select');
const videoContainer = document.querySelector('.video-container');

// Networking / WebSockets
const socket = io();
socket.emit('join', { session_id: SESSION_ID });

const remoteStreamTarget = document.getElementById('remote-stream-target');
const qrOverlay = document.getElementById('qr-overlay');

// Automatically receive live frames over WebSockets
socket.on('remote_video_frame', (data) => {
    // If QR was showing, hide it because connection established!
    qrOverlay.style.display = 'none';
    remoteStreamTarget.style.display = 'block';
    remoteStreamTarget.src = data.image;
    videoContainer.classList.add('laser-scanning'); // Turn on cool lasers while remote scanning
});

// Receive high-res capture from the phone
socket.on('remote_biometric_captured', (data) => {
    videoContainer.classList.remove('laser-scanning');
    remoteStreamTarget.style.display = 'none';
    
    faceCapturedData = data.image; // Overwrite memory
    facePreview.src = faceCapturedData;
    facePreview.style.display = 'block';
    
    finalizeCapture();
});

// Advanced Camera Setup
async function getCameras() {
    try {
        await navigator.mediaDevices.getUserMedia({ video: true }); // Request permission first
        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices.filter(device => device.kind === 'videoinput');
        
        cameraSelect.innerHTML = '<option value="remote_qr">📶 Scan QR Code (Wireless Match)</option>';
        
        videoDevices.forEach((device, index) => {
            const option = document.createElement('option');
            option.value = device.deviceId;
            option.text = device.label || `Camera ${index + 1}`;
            cameraSelect.appendChild(option);
        });
        
        // Default to QR
        startCamera('remote_qr');
    } catch(err) {
        console.warn("Camera access denied or unavilable.", err);
        showCameraError();
    }
}

async function startCamera(deviceId) {
    if (currentStream) {
        currentStream.getTracks().forEach(track => track.stop());
    }

    if (deviceId === 'remote_qr') {
        video.style.display = 'none';
        facePreview.style.display = 'none';
        remoteStreamTarget.style.display = 'none';
        
        // Generate QR Code targeting the secure python session
        const urlObj = `http://${SERVER_IP}:5000/mobile?session_id=${SESSION_ID}`;
        document.getElementById('qr-code-img').src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(urlObj)}&color=0f172a&bgcolor=10b981`;
        qrOverlay.style.display = 'flex';
        btnSnap.disabled = true;
        btnSnap.textContent = "Scanning Wirelessly...";
        return;
    }
    
    // Normal USB Camera Mode
    btnSnap.disabled = false;
    btnSnap.textContent = "Capture Face Profile";
    qrOverlay.style.display = 'none';
    remoteStreamTarget.style.display = 'none';

    const constraints = {
        video: { deviceId: deviceId ? { exact: deviceId } : undefined }
    };
    
    try {
        currentStream = await navigator.mediaDevices.getUserMedia(constraints);
        video.srcObject = currentStream;
        video.style.display = 'block';
        facePreview.style.display = 'none';
        videoContainer.classList.remove('laser-scanning');
    } catch(err) {
        console.error("Error starting camera: ", err);
        showCameraError();
    }
}

function showCameraError() {
    video.style.display = 'none';
    facePreview.style.display = 'block';
    facePreview.src = 'https://via.placeholder.com/400x300/1e293b/3b82f6?text=Face+Not+Found+Click+To+Simulate';
}

cameraSelect.addEventListener('change', (e) => {
    startCamera(e.target.value);
});

window.addEventListener('DOMContentLoaded', getCameras);

btnSnap.addEventListener('click', () => {
    if(video.srcObject && video.style.display !== 'none') {
        // Start Laser Animation
        videoContainer.classList.add('laser-scanning');
        btnSnap.textContent = "Scanning...";
        btnSnap.disabled = true;
        
        setTimeout(() => {
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
            faceCapturedData = canvas.toDataURL('image/jpeg');
            
            if(currentStream) {
                currentStream.getTracks().forEach(track => track.stop());
            }
            videoContainer.classList.remove('laser-scanning');
            video.style.display = 'none';
            facePreview.src = faceCapturedData;
            facePreview.style.display = 'block';
            
            // Update Enrollment Previews
            document.getElementById('enroll-face-preview').src = faceCapturedData;
            document.getElementById('enroll-face-preview').style.display = 'block';
            document.getElementById('enroll-face-placeholder').style.display = 'none';
            checkEnrollmentReady();

            finalizeCapture();
        }, 1500); // 1.5s scan animation
    } else {
        faceCapturedData = 'data:image/jpeg;base64,fallback_data_mock';
        facePreview.style.border = "3px solid var(--accent)";
        finalizeCapture();
    }
});

function finalizeCapture() {
    btnSnap.innerHTML = "<i class='bx bx-check'></i> Face Captured";
    btnSnap.classList.remove('outline');
    btnSnap.disabled = true;
    checkBiometricsComplete();
}

const fpArea = document.getElementById('fp-area');
const fpStatus = document.getElementById('fp-status');

// Helper to simulate hash creation rapidly from ArrayBuffer
function bufferToBase64Url(buffer) {
    return btoa(String.fromCharCode(...new Uint8Array(buffer)))
      .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

fpArea.addEventListener('click', async () => {
    if(fingerprintScanned) return;
    
    fpArea.classList.add('scanning');
    fpStatus.textContent = "Requesting Hardware Hardware Sensor...";

    try {
        // Try to invoke REAL hardware fingerprint via WebAuthn if available / permitted
        if (window.PublicKeyCredential) {
            const challenge = new Uint8Array(32);
            window.crypto.getRandomValues(challenge);

            const credential = await navigator.credentials.create({
                publicKey: {
                    challenge: challenge,
                    rp: { name: "Secure Voting Database", id: window.location.hostname },
                    user: {
                        id: new Uint8Array(16),
                        name: "identity@voting",
                        displayName: "Hardware Biometric Link"
                    },
                    pubKeyCredParams: [{type: "public-key", alg: -7}],
                    authenticatorSelection: {
                        authenticatorAttachment: "platform", // Forces internal hardware (TouchID/Windows Hello/Phone Bios)
                        userVerification: "required"
                    },
                    timeout: 60000
                }
            });
            console.log("Hardware Biometric Secure Link Created: ", credential);
            fpStatus.textContent = "Hardware Scan Complete!";
        } else {
            throw new Error("WebAuthn not supported");
        }
    } catch (err) {
        // Fallback gracefully to animation if hardware declines/fails or is unsupported
        console.warn("Hardware Sensor declined/failed, falling back to simulated UI: ", err);
        fpStatus.textContent = "Analyzing Print Simulation...";
        await new Promise(r => setTimeout(r, 1500));
        fpStatus.textContent = "Scan Complete";
    }

    fpArea.classList.remove('scanning');
    fpArea.classList.add('success');
    fingerprintScanned = true;
    checkBiometricsComplete();
});

function checkBiometricsComplete() {
    if(faceCapturedData && fingerprintScanned) {
        const btn = document.getElementById('btn-submit-bios');
        btn.disabled = false;
        btn.classList.add('glow-pulse'); 
    }
}

document.getElementById('btn-submit-bios').addEventListener('click', async () => {
    const btn = document.getElementById('btn-submit-bios');
    btn.textContent = "Querying National Database...";
    btn.disabled = true;

    try {
        const res = await fetch('/api/biometrics', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                face_data: faceCapturedData,
                fingerprint_data: 'SIMULATED_HASH'
            })
        });
        
        let data;
        try {
            data = await res.json();
        } catch (e) {
            throw new Error("Server returned an invalid response (Check Flask console for errors).");
        }

        if(!res.ok) throw new Error(data.error || "Unknown server error");

        lastBiometricData = data; 
        loadReviewData();
    } catch(err) {
        console.error("Biometric Fetch Error:", err);
        const errorEl = document.getElementById('bio-error');
        errorEl.textContent = "Error: " + err.message;
        errorEl.style.display = 'block';
        
        btn.textContent = "Fetch Identity from Database";
        btn.disabled = false;
    }
});

// -------------------------
// STEP 2: Review Database Identity
// -------------------------
async function loadReviewData() {
    try {
        const res = await fetch('/api/details');
        const voter = await res.json();
        if(!res.ok) throw new Error(voter.error);

        document.getElementById('rev-name').textContent = voter.name;
        document.getElementById('rev-father').textContent = voter.father_name;
        document.getElementById('rev-sex').textContent = voter.sex;
        document.getElementById('rev-age').textContent = voter.age;
        document.getElementById('rev-aadhaar').textContent = voter.aadhaar_number;
        document.getElementById('rev-id').textContent = voter.id_card_number;
        document.getElementById('rev-voter-id').textContent = voter.voter_id_number;
        document.getElementById('rev-address').textContent = voter.address;
        document.getElementById('rev-face').src = voter.face_data;

        if (lastBiometricData) {
            displayTechnicalAnalysis(lastBiometricData);
        }

        switchStep('review');
    } catch(err) {
        alert("Failed to load review data: " + err.message);
    }
}

function displayTechnicalAnalysis(data) {
    const landmarkList = document.getElementById('landmark-stats');
    const matrixGrid = document.getElementById('matrix-display');
    landmarkList.innerHTML = '';
    matrixGrid.innerHTML = '';

    if (data.landmarks) {
        Object.entries(data.landmarks).forEach(([feature, count]) => {
            const item = document.createElement('div');
            item.className = 'landmark-item';
            item.innerHTML = `<span>${feature.replace(/_/g, ' ')}</span> <strong>${count} pts</strong>`;
            landmarkList.appendChild(item);
        });
    }

    if (data.matrix) {
        data.matrix.forEach((val, i) => {
            const cell = document.createElement('div');
            cell.className = 'matrix-cell';
            const intensity = Math.abs(val) * 255;
            cell.style.backgroundColor = `rgba(16, 185, 129, ${Math.min(1, intensity)})`;
            setTimeout(() => { matrixGrid.appendChild(cell); }, i * 5);
        });
    }
}
    }
}

function displayTechnicalAnalysis(data) {
    const landmarkList = document.getElementById('landmark-stats');
    const matrixGrid = document.getElementById('matrix-display');
    landmarkList.innerHTML = '';
    matrixGrid.innerHTML = '';

    if (data.landmarks) {
        Object.entries(data.landmarks).forEach(([feature, count]) => {
            const item = document.createElement('div');
            item.className = 'landmark-item';
            item.innerHTML = `<span>${feature.replace(/_/g, ' ')}</span> <strong>${count} pts</strong>`;
            landmarkList.appendChild(item);
        });
    }

    if (data.matrix) {
        data.matrix.forEach((val, i) => {
            const cell = document.createElement('div');
            cell.className = 'matrix-cell';
            const intensity = Math.abs(val) * 255;
            cell.style.backgroundColor = `rgba(16, 185, 129, ${Math.min(1, intensity)})`;
            setTimeout(() => { matrixGrid.appendChild(cell); }, i * 5);
        });
    }
}

function displayTechnicalAnalysis(data) {
    const landmarkList = document.getElementById('landmark-stats');
    const matrixGrid = document.getElementById('matrix-display');
    landmarkList.innerHTML = '';
    matrixGrid.innerHTML = '';

    if (data.landmarks) {
        Object.entries(data.landmarks).forEach(([feature, count]) => {
            const item = document.createElement('div');
            item.className = 'landmark-item';
            item.innerHTML = `<span>${feature.replace(/_/g, ' ')}</span> <strong>${count} pts</strong>`;
            landmarkList.appendChild(item);
        });
    }

    if (data.matrix) {
        data.matrix.forEach((val, i) => {
            const cell = document.createElement('div');
            cell.className = 'matrix-cell';
            const intensity = Math.abs(val) * 255;
            cell.style.backgroundColor = `rgba(16, 185, 129, ${Math.min(1, intensity)})`;
            setTimeout(() => { matrixGrid.appendChild(cell); }, i * 5);
        });
    }
}

document.getElementById('btn-confirm-review').addEventListener('click', () => {
    loadCandidates(); 
});

// -------------------------
// STEP 3: Vote
// -------------------------
async function loadCandidates() {    

    try {
        const res = await fetch('/api/candidates');
        const candidates = await res.json();
        
        const container = document.getElementById('candidates-container');
        container.innerHTML = '';
        
        candidates.forEach(c => {
            const el = document.createElement('div');
            el.className = 'candidate-card';
            el.innerHTML = `
                <div>
                    <div class="candidate-name">${c.name}</div>
                </div>
                <i class='bx bx-circle bx-sm' id="icon-${c.id}"></i>
            `;
            el.addEventListener('click', () => {
                document.querySelectorAll('.candidate-card').forEach(n => n.classList.remove('selected'));
                document.querySelectorAll('.candidate-card i').forEach(n => {
                    n.classList.remove('bx-check-circle', 'bx-sm');
                    n.classList.add('bx-circle', 'bx-sm');
                });
                
                el.classList.add('selected');
                const icon = document.getElementById(`icon-${c.id}`);
                icon.classList.remove('bx-circle');
                icon.classList.add('bx-check-circle');
                
                selectedCandidateId = c.id;
                document.getElementById('btn-cast-vote').disabled = false;
            });
            container.appendChild(el);
        });
        
        switchStep('vote');
    } catch(err) {
        alert("Failed to load candidates");
    }
}

document.getElementById('btn-cast-vote').addEventListener('click', async () => {
    if(!selectedCandidateId) return;
    
    try {
        const res = await fetch('/api/vote', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ candidate_id: selectedCandidateId })
        });
        const data = await res.json();
        if(!res.ok) throw new Error(data.error);

        switchStep('success');

        // Start 5-second automatic reset timer
        let timeLeft = 5;
        const noteEl = document.getElementById('auto-reset-note');
        noteEl.innerHTML = `<i class='bx bx-refresh bx-spin'></i> Automatic reset in <b>${timeLeft}s</b> for the next voter...`;
        
        const timer = setInterval(() => {
            timeLeft--;
            if (timeLeft <= 0) {
                clearInterval(timer);
                resetForNextVoter();
            } else {
                noteEl.innerHTML = `<i class='bx bx-refresh bx-spin'></i> Automatic reset in <b>${timeLeft}s</b> for the next voter...`;
            }
        }, 1000);

        // Store timer globally to clear if manual reset is clicked
        window.activeResetTimer = timer;

    } catch(err) {
        document.getElementById('vote-error').textContent = err.message;
    }
});

// -------------------------
// Seamless Transition Reset Logic
// -------------------------
async function resetForNextVoter() {
    console.log("Resetting for next voter lookup...");
    
    // Clear the auto-reset timer if it exists
    if (window.activeResetTimer) {
        clearInterval(window.activeResetTimer);
        window.activeResetTimer = null;
    }

    // Reset Core State
    faceCapturedData = null;
    fingerprintScanned = false;
    selectedCandidateId = null;

    // Reset Biometric UI Elements
    const btnSnap = document.getElementById('btn-snap');
    btnSnap.innerHTML = "<i class='bx bx-camera'></i> Scan Face";
    btnSnap.classList.add('outline');
    btnSnap.disabled = false;

    const facePreview = document.getElementById('face-preview');
    facePreview.style.display = 'none';
    facePreview.src = '';
    facePreview.style.border = "none";

    const video = document.getElementById('video-stream');
    video.style.display = 'block';

    const fpArea = document.getElementById('fp-area');
    fpArea.classList.remove('scanning', 'success');
    const fpStatus = document.getElementById('fp-status');
    fpStatus.textContent = "Tap area to scan fingerprint";

    const btnSubmit = document.getElementById('btn-submit-bios');
    btnSubmit.disabled = true;
    btnSubmit.textContent = "Fetch Identity from Database";
    btnSubmit.classList.remove('glow-pulse');

    const bioError = document.getElementById('bio-error');
    bioError.style.display = 'none';
    bioError.textContent = '';

    // Clear Review Data UI
    document.getElementById('rev-name').textContent = '';
    document.getElementById('rev-face').src = '';

    // Clear Candidates UI
    document.getElementById('candidates-container').innerHTML = '';
    document.getElementById('btn-cast-vote').disabled = true;

    // Reset success UI
    document.getElementById('auto-reset-note').textContent = '';

    // Transition back to step 1
    switchStep('biometrics');
    
    // Refresh Camera State / QR
    const cameraSelect = document.getElementById('camera-select');
    startCamera(cameraSelect.value);
}

// -------------------------
// Advanced 3D Card Hover Effect
// -------------------------
document.addEventListener('mousemove', (e) => {
    document.querySelectorAll('.card-3d').forEach(card => {
        const rect = card.getBoundingClientRect();
        
        // Check if mouse is hovering over the card
        if(e.clientX >= rect.left && e.clientX <= rect.right && 
           e.clientY >= rect.top && e.clientY <= rect.bottom) {
            
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            
            const centerX = rect.width / 2;
            const centerY = rect.height / 2;
            
            const rotateX = ((y - centerY) / centerY) * -10; // Max 10 deg
            const rotateY = ((x - centerX) / centerX) * 10;
            
            card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`;
            card.style.boxShadow = `0 20px 40px rgba(0,0,0,0.4)`;
        } else {
            card.style.transform = `perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)`;
            card.style.boxShadow = `none`;
        }
    });
});

// Demo Reset Mechanism
document.getElementById('btn-reset-demo').addEventListener('click', async () => {
    if(!confirm("ARE YOU SURE? This will clear ALL biometric enrollments and votes for the entire database to reset the demo.")) return;
    try {
        const res = await fetch('/api/reset', { method: 'POST' });
        const data = await res.json();
        alert(data.message);
        location.reload();
    } catch(err) {
        alert("Reset failed: " + err);
    }
});

// -------------------------
// Hardware Manager 
// -------------------------
const hwModal = document.getElementById('hw-modal');

document.getElementById('btn-open-hw').addEventListener('click', () => {
    hwModal.classList.add('open');
});

document.getElementById('close-hw').addEventListener('click', () => {
    hwModal.classList.remove('open');
});

document.getElementById('btn-hw-usb').addEventListener('click', async () => {
    try {
        const device = await navigator.usb.requestDevice({ filters: [] }); // Prompts user heavily for ALL USB items
        alert("Successfully paired protocol handler for USB Device: " + (device.productName || "Unknown biometric mechanism"));
        hwModal.classList.remove('open');
    } catch(err) {
        console.warn("USB Request failed or declined", err);
        alert("USB integration was closed or an error occurred.");
    }
});

document.getElementById('btn-hw-sim').addEventListener('click', () => {
    alert("Scanning for Bluetooth devices... (Requires Bluetooth Web API support on this device environment and HTTPS context)");
});

document.getElementById('btn-hw-fido').addEventListener('click', () => {
    alert("Success! To cross-link your phone via FIDO2 natively, simply use the actual Fingerprint Scanner button on the main panel. The system will dispatch a secure hardware polling event to activate platform authenticators!");
    hwModal.classList.remove('open');
});

// -------------------------
// Enrollment Manager
// -------------------------
const enrollModal = document.getElementById('enroll-modal');
const enrollNameInput = document.getElementById('enroll-name');
const btnConfirmEnroll = document.getElementById('btn-confirm-enroll');

document.getElementById('btn-open-enroll').addEventListener('click', () => {
    enrollModal.classList.add('open');
});

document.getElementById('close-enroll').addEventListener('click', () => {
    enrollModal.classList.remove('open');
});

enrollNameInput.addEventListener('input', checkEnrollmentReady);

function checkEnrollmentReady() {
    if (enrollNameInput.value.trim().length > 2 && faceCapturedData) {
        btnConfirmEnroll.disabled = false;
        btnConfirmEnroll.classList.add('glow-pulse');
    } else {
        btnConfirmEnroll.disabled = true;
        btnConfirmEnroll.classList.remove('glow-pulse');
    }
}

btnConfirmEnroll.addEventListener('click', async () => {
    const name = enrollNameInput.value.trim();
    const errorEl = document.getElementById('enroll-error');
    errorEl.textContent = '';
    
    btnConfirmEnroll.disabled = true;
    btnConfirmEnroll.textContent = "Integrating Biometric Profile...";

    try {
        const res = await fetch('/api/enroll', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name: name,
                face_data: faceCapturedData
            })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Enrollment failed");

        alert(data.message);
        enrollModal.classList.remove('open');
        
        // Auto-trigger identification to show it works
        document.getElementById('btn-submit-bios').click();
    } catch (err) {
        errorEl.textContent = "Enrollment Error: " + err.message;
        btnConfirmEnroll.disabled = false;
        btnConfirmEnroll.textContent = "Securely Link Identity";
    }
});
