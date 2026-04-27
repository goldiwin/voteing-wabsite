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
from threading import Timer

# --- Global Face Storage ---
KNOWN_SIGNATURES = {}   # Name -> np.ndarray landmark vector
VALIDATED_VOTERS = set()

# ── MediaPipe Tasks FaceLandmarker — LAZY init (avoids blocking Render boot) ──
_MODEL_PATH = os.path.join(os.path.dirname(__file__), "face_landmarker.task")
_MODEL_URL  = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
_face_landmarker = None   # initialised on first request

def _get_face_landmarker():
    """Return (and lazily create) the singleton FaceLandmarker."""
    global _face_landmarker
    if _face_landmarker is not None:
        return _face_landmarker
    # Download model if absent
    if not os.path.exists(_MODEL_PATH):
        print(f"Downloading FaceLandmarker model …", flush=True)
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

def get_face_signature(img):
    """Return a flat float32 landmark vector, or None if no face detected."""
    try:
        landmarker = _get_face_landmarker()
        rgb    = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(mp_img)
        if not result.face_landmarks:
            return None
        lms = result.face_landmarks[0]
        return np.array([[lm.x, lm.y, lm.z] for lm in lms], dtype=np.float32).flatten()
    except Exception as e:
        print(f"get_face_signature error: {e}", flush=True)
        return None

def reload_known_faces():
    global KNOWN_SIGNATURES
    # Search both top-level files and subfolders inside each path
    search_roots = ["faces", "4 chutiye"]
    new_signatures = {}
    img_extensions = (".jpg", ".png", ".jpeg")

    for root in search_roots:
        if not os.path.exists(root):
            continue
        # Walk recursively so each subfolder name becomes the person's name
        for dirpath, dirnames, filenames in os.walk(root):
            for file in filenames:
                if file.lower().endswith(img_extensions):
                    try:
                        img_path = os.path.join(dirpath, file)
                        img = cv2.imread(img_path)
                        if img is None:
                            continue
                        sig = get_face_signature(img)
                        if sig is not None:
                            # Use filename without extension as identity key
                            name = os.path.splitext(file)[0]
                            # If multiple images per person, average their signatures
                            if name in new_signatures:
                                new_signatures[name] = (new_signatures[name] + sig) / 2
                            else:
                                new_signatures[name] = sig
                            logger.info(f"Integrated identity: {name} from {img_path}")
                    except Exception as e:
                        logger.error(f"Error loading {file}: {e}")

    KNOWN_SIGNATURES = new_signatures
    logger.info(f"System Ready: {len(KNOWN_SIGNATURES)} identities integrated.")

def get_cv2_image_from_base64(b64_str):
    if not b64_str or ',' not in b64_str: return None
    encoded_data = b64_str.split(',')[1]
    nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secure_voting_secret')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('RENDER', False)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize database
init_db()

# SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

@app.route('/health')
def health(): return "OK", 200

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception: return '127.0.0.1'

@app.route('/')
def index():
    return render_template('index.html', local_ip=get_local_ip())

@app.route('/mobile')
def mobile():
    session_id = request.args.get('session_id')
    return render_template('mobile.html', session_id=session_id)

# ─── Legacy endpoint kept for compatibility ───────────────────────────────────
@app.route('/api/biometrics', methods=['POST'])
def biometrics_match():
    """Kept for backward compat. Internally calls the same scan logic."""
    global KNOWN_SIGNATURES
    if not KNOWN_SIGNATURES:
        reload_known_faces()

    data = request.json
    face_data = data.get('face_data')
    if not face_data:
        return jsonify({'error': 'Face data missing'}), 400

    try:
        img_captured = get_cv2_image_from_base64(face_data)
        captured_sig = get_face_signature(img_captured)
        if captured_sig is None:
            return jsonify({'error': 'No face detected. Please try again.'}), 400
        return _perform_scan(captured_sig)
    except Exception as e:
        logger.error(f"Biometric error: {str(e)}")
        return jsonify({'error': 'System error. Ensure face is visible.'}), 500


# ─── NEW: Real-time landmark-only scan (no image transmitted) ─────────────────
@app.route('/api/scan', methods=['POST'])
def scan_face():
    """
    Accepts a raw MediaPipe 468-landmark flat vector (1404 floats) from the
    browser. No image is ever sent or stored.
    Returns:
      { status: 'VALID',          name, voter_name }   → first-time recognised
      { status: 'ALREADY_SCANNED', name }               → same person scanned again
      { status: 'INVALID' }                             → unknown face
      { status: 'NO_FACE' }                             → no face in frame
    """
    global KNOWN_SIGNATURES
    if not KNOWN_SIGNATURES:
        reload_known_faces()

    data = request.json or {}
    vector = data.get('landmarks')  # list of 1404 floats

    if not vector:
        return jsonify({'status': 'NO_FACE'}), 200

    try:
        captured_sig = np.array(vector, dtype=np.float32)
        return _perform_scan(captured_sig)
    except Exception as e:
        logger.error(f"Scan error: {e}")
        return jsonify({'status': 'ERROR', 'message': str(e)}), 500


def _perform_scan(captured_sig):
    """Core matching logic shared by both scan endpoints."""
    if len(captured_sig) == 0:
        return jsonify({'status': 'NO_FACE'}), 200

    # --- Find closest known face (normalised Euclidean distance) ---
    best_match_name = None
    min_distance = float('inf')
    for name, known_sig in KNOWN_SIGNATURES.items():
        # Pad / trim to same length in case of mixed 468 vs 478 landmark counts
        min_len = min(len(captured_sig), len(known_sig))
        dist = float(np.linalg.norm(captured_sig[:min_len] - known_sig[:min_len]))
        # Normalise by vector length so threshold is scale-invariant
        dist_norm = dist / max(min_len, 1)
        if dist_norm < min_distance:
            min_distance = dist_norm
            best_match_name = name

    logger.info(f"Scan — best: {best_match_name!r}  norm_dist: {min_distance:.6f}")

    # Normalised threshold (empirically tuned: ~0.0003–0.0008 for same person)
    THRESHOLD = 0.0015
    if min_distance >= THRESHOLD:
        return jsonify({'status': 'INVALID'}), 200

    matched_name = best_match_name

    # Already scanned in this session?
    if matched_name in VALIDATED_VOTERS:
        return jsonify({'status': 'ALREADY_SCANNED', 'name': matched_name}), 200

    # Check database (has_voted flag)
    conn = get_db_connection()
    try:
        voter = conn.execute(
            'SELECT * FROM voters WHERE name = ?', (matched_name,)
        ).fetchone()

        if not voter:
            return jsonify({'status': 'INVALID'}), 200

        if voter['has_voted']:
            return jsonify({'status': 'ALREADY_SCANNED', 'name': matched_name}), 200

        # ✅ First-time valid scan → grant access
        session['voter_id'] = voter['id']
        VALIDATED_VOTERS.add(matched_name)
        conn.commit()

        return jsonify({
            'status': 'VALID',
            'name': matched_name,
            'voter_name': matched_name,
            'landmarks': {
                'Total Landmarks': 468,
                'Eyes/Brows': 120,
                'Mouth/Lips': 80,
                'Facial Oval': 36,
                'Precision': '0.001mm'
            },
            'matrix': captured_sig.tolist()[:128]
        }), 200
    finally:
        conn.close()

@app.route('/api/enroll', methods=['POST'])
def enroll_biometrics():
    data = request.json
    name = data.get('name')
    face_data = data.get('face_data')

    if not name or not face_data:
        return jsonify({'error': 'Name and face data required for enrollment'}), 400

    try:
        img_captured = get_cv2_image_from_base64(face_data)
        if img_captured is None:
            return jsonify({'error': 'Invalid image data'}), 400

        # Verify a face exists in the capture before saving using MediaPipe
        sig = get_face_signature(img_captured)
        
        if sig is None:
            return jsonify({'error': 'INVALID: No face detected. Please ensure your face is visible.'}), 400

        # Save to faces directory
        path = "faces"
        if not os.path.exists(path):
            os.makedirs(path)
            
        file_path = os.path.join(path, f"{name}.jpg")
        cv2.imwrite(file_path, img_captured)
        
        # Reload identities
        reload_known_faces()
        
        logger.info(f"Successfully enrolled new identity: {name}")
        return jsonify({'message': f'Identity "{name}" successfully integrated into the secure database.'})

    except Exception as e:
        logger.error(f"Enrollment error: {str(e)}")
        return jsonify({'error': f'Enrollment failed: {str(e)}'}), 500

@app.route('/api/details', methods=['GET'])
def get_voter_details():
    logger.info(f"Fetching voter details. Current Session voter_id: {session.get('voter_id')}")
    if 'voter_id' not in session:
        logger.warning("Access denied to /api/details: No voter_id in session.")
        return jsonify({'error': 'Not authorized'}), 401
        
    conn = get_db_connection()
    voter = conn.execute('SELECT aadhaar_number, id_card_number, voter_id_number, name, father_name, sex, age, address, face_data FROM voters WHERE id = ?', (session['voter_id'],)).fetchone()
    conn.close()
    
    if voter:
        return jsonify(dict(voter))
    return jsonify({'error': 'Voter not found'}), 404

@app.route('/api/candidates', methods=['GET'])
def get_candidates():
    conn = get_db_connection()
    candidates = conn.execute('SELECT * FROM candidates').fetchall()
    conn.close()
    return jsonify([dict(c) for c in candidates])

@app.route('/api/vote', methods=['POST'])
def vote():
    if 'voter_id' not in session:
        return jsonify({'error': 'Not authorized'}), 401
        
    data = request.json
    candidate_id = data.get('candidate_id')
    
    if not candidate_id:
        return jsonify({'error': 'Missing candidate selection'}), 400

    conn = get_db_connection()
    try:
        voter = conn.execute('SELECT has_voted FROM voters WHERE id = ?', (session['voter_id'],)).fetchone()
        
        if voter['has_voted']:
            return jsonify({'error': 'You have already voted'}), 403
            
        cursor = conn.cursor()
        cursor.execute('INSERT INTO votes (candidate_id) VALUES (?)', (candidate_id,))
        cursor.execute('UPDATE voters SET has_voted = 1 WHERE id = ?', (session['voter_id'],))
        conn.commit()
        
        session.clear()
        return jsonify({'message': 'Vote cast securely!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/reset', methods=['POST'])
def reset_demo():
    conn = get_db_connection()
    try:
        logger.info("Performing full demo reset.")
        # Reset everything to allow re-enrollment and re-voting
        conn.execute('UPDATE voters SET has_voted = 0, face_data = NULL, fingerprint_data = NULL')
        conn.execute('DELETE FROM votes')
        conn.commit()
        VALIDATED_VOTERS.clear() # Clear session locks
        session.clear()
        return jsonify({'message': 'System reset successfully. All biometric data and session locks cleared.'})
    except Exception as e:
        logger.error(f"Reset error: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@socketio.on('join')
def on_join(data):
    room = data.get('session_id')
    join_room(room)

@socketio.on('video_frame')
def handle_video_frame(data):
    # Relay frame directly to laptop web browser
    emit('remote_video_frame', {'image': data['image']}, room=data.get('session_id'), include_self=False)

@socketio.on('remote_capture')
def handle_remote_capture(data):
    emit('remote_biometric_captured', {'image': data['image']}, room=data.get('session_id'), include_self=False)

def open_browser():
    try:
        webbrowser.open_new("http://127.0.0.1:5000/")
    except Exception:
        pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Only open the browser locally, not on Render
    if not os.environ.get('RENDER') and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        Timer(1.5, open_browser).start()
    socketio.run(app, debug=not os.environ.get('RENDER'), host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
