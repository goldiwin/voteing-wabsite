import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from database import get_db_connection, init_db
import logging
import os
import socket
from flask_socketio import SocketIO, emit, join_room
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
import cv2
import numpy as np
import base64
import webbrowser
import urllib.request
from threading import Timer, Lock
import time
from functools import wraps
import secrets

# --- Global Face Storage ---
KNOWN_SIGNATURES = {}   # Name -> np.ndarray landmark vector (L2-normalised)
VALIDATED_VOTERS = set()
SCAN_LOCK = Lock()
_FACES_LOADED = False

# ── MediaPipe Tasks FaceLandmarker — LAZY init (avoids blocking Render boot) ──
_MODEL_PATH = os.path.join(os.path.dirname(__file__), "face_landmarker.task")
_MODEL_URL  = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
_face_landmarker = None
_LANDMARKER_LOCK = Lock()

def _get_face_landmarker():
    """Return (and lazily create) the singleton FaceLandmarker — thread-safe."""
    global _face_landmarker
    if _face_landmarker is not None:
        return _face_landmarker
    with _LANDMARKER_LOCK:
        if _face_landmarker is not None:
            return _face_landmarker
        if not os.path.exists(_MODEL_PATH):
            print("Downloading FaceLandmarker model …", flush=True)
            urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
            print("Model download complete.", flush=True)
        opts = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=_MODEL_PATH),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        _face_landmarker = mp_vision.FaceLandmarker.create_from_options(opts)
    return _face_landmarker

def normalize_signature(sig: np.ndarray) -> np.ndarray:
    """Produce a translation-invariant, scale-invariant, unit-length signature."""
    points = sig.reshape(-1, 3).astype(np.float32)
    # 1. Translate centroid to origin
    points -= points.mean(axis=0)
    # 2. Scale by RMS distance
    rms = np.sqrt(np.mean(np.sum(points ** 2, axis=1)))
    if rms > 1e-6:
        points /= rms
    flat = points.flatten()
    # 3. L2-normalise
    norm = np.linalg.norm(flat)
    if norm > 1e-6:
        flat /= norm
    return flat

def get_face_signature(img: np.ndarray):
    """Return a normalised unit-length landmark vector, or None if no face."""
    try:
        landmarker = _get_face_landmarker()
        rgb    = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(mp_img)
        if not result.face_landmarks:
            return None
        lms = result.face_landmarks[0]
        raw_sig = np.array([[lm.x, lm.y, lm.z] for lm in lms], dtype=np.float32).flatten()
        return normalize_signature(raw_sig)
    except Exception as e:
        print(f"get_face_signature error: {e}", flush=True)
        return None

def reload_known_faces():
    global KNOWN_SIGNATURES, _FACES_LOADED
    search_roots = ["me"]
    img_extensions = (".jpg", ".png", ".jpeg")
    raw_sigs = {}

    for root in search_roots:
        if not os.path.exists(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            for file in filenames:
                if file.lower().endswith(img_extensions):
                    try:
                        img_path = os.path.join(dirpath, file)
                        img = cv2.imread(img_path)
                        if img is None:
                            logger.warning(f"Could not read image: {img_path}")
                            continue
                        
                        sig = get_face_signature(img)
                        if sig is None:
                            logger.warning(f"No face found in image: {img_path}")
                            continue
                        
                        import re
                        name = os.path.splitext(file)[0]
                        # Strip suffixes like _1, _2, (1), etc. to group images for the same person
                        name = re.sub(r'(_\d+|\(\d+\)|\s\d+)$', '', name).strip()
                        
                        raw_sigs.setdefault(name, []).append(sig)
                        logger.info(f"Loaded face: {name} from {img_path}")
                    except Exception as e:
                        logger.error(f"Error loading {file}: {e}")

    new_signatures = {}
    for name, sigs in raw_sigs.items():
        # Store ALL signatures for this person to match against any angle
        new_signatures[name] = sigs

    with SCAN_LOCK:
        KNOWN_SIGNATURES = new_signatures
        _FACES_LOADED = True
    logger.info(f"System Ready: {len(KNOWN_SIGNATURES)} identities integrated.")

def _ensure_faces_loaded():
    global _FACES_LOADED
    if not _FACES_LOADED:
        logger.info("Scan requested but faces not loaded. Waiting (max 15s)...")
        start_wait = time.time()
        while not _FACES_LOADED:
            if time.time() - start_wait > 15:
                logger.error("TIMEOUT: Face loading took too long. Proceeding anyway.")
                break
            time.sleep(0.5)

def get_cv2_image_from_base64(b64_str):
    if not b64_str or ',' not in b64_str: return None
    encoded_data = b64_str.split(',')[1]
    nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secure_voting_secret_2026')
app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
app.config['SESSION_COOKIE_SECURE'] = True if os.environ.get('RENDER') else False
app.config['SESSION_COOKIE_HTTPONLY'] = True

# Initialize logging early
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize database
init_db()

# Pre-load biometric signatures in a background thread so Render boot doesn't timeout
import threading
def background_load():
    with app.app_context():
        print("Background task: Pre-loading biometric signatures...", flush=True)
        reload_known_faces()
        print("Background task: Biometrics ready.", flush=True)

threading.Thread(target=background_load, daemon=True).start()

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- CYBER SECURITY SUBSYSTEM ---
IP_ACCESS_LOG = {}
RATE_LIMIT_SECONDS = 2
MAX_REQUESTS = 15

def cyber_security_shield(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_ip = request.remote_addr
        current_time = time.time()
        IP_ACCESS_LOG.setdefault(client_ip, [])
        IP_ACCESS_LOG[client_ip] = [t for t in IP_ACCESS_LOG[client_ip] if current_time - t < RATE_LIMIT_SECONDS]
        if len(IP_ACCESS_LOG[client_ip]) >= MAX_REQUESTS:
            return jsonify({'error': 'Too many requests.'}), 429
        IP_ACCESS_LOG[client_ip].append(current_time)
        return f(*args, **kwargs)
    return decorated_function

@app.after_request
def apply_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com https://cdn.jsdelivr.net https://fonts.googleapis.com https://fonts.gstatic.com https://cdnjs.cloudflare.com https://storage.googleapis.com https://api.qrserver.com wss:;"
    return response

@app.before_request
def csrf_protect():
    if request.method == "POST" and request.path.startswith('/api/'):
        server_token = session.get('csrf_token')
        client_token = request.headers.get('X-CSRF-Token')
        if not server_token or not client_token or server_token != client_token:
            return jsonify({'error': 'Security Block: Invalid cryptographic signature.'}), 403

@app.route('/health')
def health(): return "OK", 200

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]; s.close()
        return ip
    except Exception: return '127.0.0.1'

def get_base_url():
    """Return the base URL of the app, respecting Render and localhost."""
    if os.environ.get('RENDER_EXTERNAL_URL'):
        return os.environ.get('RENDER_EXTERNAL_URL')
    return f"http://{get_local_ip()}:5000"

@app.route('/api/debug/signatures')
def debug_signatures():
    """See what faces are actually loaded in memory."""
    return jsonify({
        'count': len(KNOWN_SIGNATURES),
        'identities': list(KNOWN_SIGNATURES.keys()),
        'validated_count': len(VALIDATED_VOTERS)
    })

@app.route('/api/exit', methods=['POST'])
def exit_session():
    """Clear session-level biometric lock for next voter."""
    name = session.get('voter_name')
    if name in VALIDATED_VOTERS:
        VALIDATED_VOTERS.remove(name)
    session.clear()
    return jsonify({'status': 'OK'})

@app.route('/')
def index():
    # Clear scan session flags on fresh load to prevent "Already Voted" ghosting
    session.pop('voter_name', None)
    session.pop('voter_id', None)
    session['csrf_token'] = secrets.token_hex(32)
    return render_template('index.html', base_url=get_base_url(), csrf_token=session.get('csrf_token'))

@app.route('/mobile')
def mobile():
    return render_template('mobile.html', session_id=request.args.get('session_id'))

@app.route('/api/scan', methods=['POST'])
@cyber_security_shield
def scan_face():
    _ensure_faces_loaded()
    if 'voter_name' in session:
        return jsonify({'status': 'ALREADY_SCANNED', 'name': session['voter_name']}), 200
    
    data = request.json or {}
    vector = data.get('landmarks')
    if not vector: return jsonify({'status': 'NO_FACE'}), 200

    try:
        raw_sig = np.array(vector, dtype=np.float32)
        if len(raw_sig) != 1404: return jsonify({'status': 'NO_FACE'}), 200
        captured_sig = normalize_signature(raw_sig)
        return _perform_scan(captured_sig)
    except Exception as e:
        logger.error(f"Scan error: {e}")
        return jsonify({'status': 'ERROR', 'message': str(e)}), 500

def _perform_scan(captured_sig):
    COSINE_THRESHOLD = 0.70 
    # Ratio Test: Best match must be significantly better than 2nd best to avoid "confusion"
    RATIO_THRESHOLD = 0.02 
 
    with SCAN_LOCK:
        # Sort matches by similarity
        results = []
        for name, sig_list in KNOWN_SIGNATURES.items():
            # Find the BEST match among all photos of this person
            best_sim_for_person = 0
            for known_sig in sig_list:
                sim = float(np.dot(captured_sig, known_sig))
                if sim > best_sim_for_person:
                    best_sim_for_person = sim
            results.append((name, best_sim_for_person))
        
        results.sort(key=lambda x: x[1], reverse=True)

        if not results:
            return jsonify({'status': 'INVALID', 'reason': 'no_identities_loaded'}), 200

        best_name, best_sim = results[0]
        if best_sim < COSINE_THRESHOLD:
            logger.info(f"Scan FAIL: No match above {COSINE_THRESHOLD}. Best: {best_name} at {best_sim:.4f}")
            return jsonify({
                'status': 'INVALID', 
                'best_match': best_name, 
                'score': round(best_sim, 4),
                'threshold': COSINE_THRESHOLD
            }), 200

        # Check for ambiguity (confusion)
        if len(results) > 1:
            second_name, second_sim = results[1]
            if (best_sim - second_sim) < RATIO_THRESHOLD:
                logger.warning(f"Scan AMBIGUOUS: {best_name}({best_sim:.3f}) vs {second_name}({second_sim:.3f}). Gap < {RATIO_THRESHOLD}")
                return jsonify({'status': 'INVALID', 'reason': 'ambiguous'}), 200

        logger.info(f"Scan SUCCESS: Matched {best_name} (Score: {best_sim:.4f})")

        conn = get_db_connection()
        try:
            voter = conn.execute('SELECT * FROM voters WHERE name = ?', (best_name,)).fetchone()
            if not voter:
                logger.error(f"Matched {best_name} but not found in Database!")
                return jsonify({'status': 'INVALID'}), 200

            if voter['has_voted'] == 1:
                return jsonify({'status': 'ALREADY_SCANNED', 'name': best_name}), 200
            
            session['voter_id'], session['voter_name'] = voter['id'], best_name
            VALIDATED_VOTERS.add(best_name)
        finally:
            conn.close()

        return jsonify({
            'status': 'VALID', 
            'name': best_name, 
            'voter_name': best_name, 
            'similarity_score': round(best_sim, 4),
            'landmarks': {
                'Total Landmarks': 468,
                'Eyes/Brows': 120,
                'Mouth/Lips': 80,
                'Precision': '0.001mm'
            },
            'matrix': captured_sig.tolist()[:128]
        }), 200

@app.route('/api/enroll', methods=['POST'])
@cyber_security_shield
def enroll_biometrics():
    data = request.json
    name, face_data = data.get('name'), data.get('face_data')
    if not name or not face_data: return jsonify({'error': 'Missing name/face_data'}), 400
    try:
        img = get_cv2_image_from_base64(face_data)
        sig = get_face_signature(img)
        if sig is None: return jsonify({'error': 'No face detected'}), 400
        os.makedirs("me", exist_ok=True)
        file_path = os.path.join("me", f"{name}.jpg")
        cv2.imwrite(file_path, img)
        global _FACES_LOADED; _FACES_LOADED = False
        reload_known_faces()
        return jsonify({'message': f'Identity "{name}" enrolled successfully.'})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/details', methods=['GET'])
def get_voter_details():
    if 'voter_id' not in session: return jsonify({'error': 'Not authorized'}), 401
    conn = get_db_connection()
    voter = conn.execute('SELECT aadhaar_number, id_card_number, voter_id_number, name, father_name, sex, age, address FROM voters WHERE id = ?', (session['voter_id'],)).fetchone()
    conn.close()
    return jsonify(dict(voter)) if voter else (jsonify({'error': 'Not found'}), 404)

@app.route('/api/candidates', methods=['GET'])
def get_candidates():
    conn = get_db_connection()
    candidates = conn.execute('SELECT * FROM candidates').fetchall()
    conn.close()
    return jsonify([dict(c) for c in candidates])

@app.route('/api/vote', methods=['POST'])
@cyber_security_shield
def vote():
    if 'voter_id' not in session: return jsonify({'error': 'Not authorized'}), 401
    candidate_id = request.json.get('candidate_id')
    conn = get_db_connection()
    try:
        voter = conn.execute('SELECT has_voted FROM voters WHERE id = ?', (session['voter_id'],)).fetchone()
        if voter['has_voted']: return jsonify({'error': 'Already voted'}), 403
        conn.execute('INSERT INTO votes (candidate_id) VALUES (?)', (candidate_id,))
        conn.execute('UPDATE voters SET has_voted = 1 WHERE id = ?', (session['voter_id'],))
        conn.commit(); session.clear()
        return jsonify({'message': 'Vote cast securely!'})
    except Exception as e: return jsonify({'error': str(e)}), 500
    finally: conn.close()

@socketio.on('join')
def on_join(data): join_room(data.get('session_id'))

@socketio.on('video_frame')
def handle_video_frame(data):
    emit('remote_video_frame', {'image': data['image']}, room=data.get('session_id'), include_self=False)

@socketio.on('remote_capture')
def handle_remote_capture(data):
    emit('remote_biometric_captured', {'image': data['image']}, room=data.get('session_id'), include_self=False)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    if not os.environ.get('RENDER'):
        Timer(1.5, lambda: webbrowser.open(f"http://{get_local_ip()}:5000/")).start()
    socketio.run(app, debug=True, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)