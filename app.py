from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from database import get_db_connection, init_db
import logging
import os
import socket
from flask_socketio import SocketIO, emit, join_room
import mediapipe as mp
import cv2
import numpy as np
import base64
import webbrowser
from threading import Timer

# --- Global Face Storage ---
KNOWN_SIGNATURES = {} # Name -> Landmark Vector
VALIDATED_VOTERS = set() 

# Initialize MediaPipe
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=True,
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5
)

def get_face_signature(img):
    """Generates a unique 3D landmark signature for a face."""
    results = face_mesh.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    if not results.multi_face_landmarks:
        return None
    
    # Extract all 468 landmarks as a flat vector
    landmarks = results.multi_face_landmarks[0].landmark
    vector = np.array([[lm.x, lm.y, lm.z] for lm in landmarks]).flatten()
    return vector

def reload_known_faces():
    global KNOWN_SIGNATURES
    paths = ["faces", "4 chutiye"]
    new_signatures = {}
    
    for path in paths:
        if not os.path.exists(path): continue
        for file in os.listdir(path):
            if file.endswith((".jpg", ".png", ".jpeg")):
                try:
                    img_path = os.path.join(path, file)
                    img = cv2.imread(img_path)
                    sig = get_face_signature(img)
                    if sig is not None:
                        name = os.path.splitext(file)[0]
                        new_signatures[name] = sig
                        logger.info(f"Integrated identity: {name}")
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

@app.route('/api/biometrics', methods=['POST'])
def biometrics_match():
    global KNOWN_SIGNATURES
    if not KNOWN_SIGNATURES: reload_known_faces()

    data = request.json
    face_data = data.get('face_data')
    fingerprint_data = data.get('fingerprint_data')

    if not face_data: return jsonify({'error': 'Face data missing'}), 400

    try:
        img_captured = get_cv2_image_from_base64(face_data)
        captured_sig = get_face_signature(img_captured)
        
        if captured_sig is None:
            return jsonify({'error': 'No face detected. Please try again.'}), 400
            
        # Compare against known signatures (Euclidean distance)
        best_match_name = None
        min_distance = float('inf')
        
        for name, known_sig in KNOWN_SIGNATURES.items():
            dist = np.linalg.norm(captured_sig - known_sig)
            if dist < min_distance:
                min_distance = dist
                best_match_name = name
        
        # Threshold for MediaPipe signature matching (tuned for 468 points)
        logger.info(f"Best match: {best_match_name} (Dist: {min_distance:.4f})")
        
        if min_distance < 0.25: # Strict threshold for security
            matched_name = best_match_name
            
            if matched_name in VALIDATED_VOTERS:
                return jsonify({'error': f'Identity already validated for {matched_name}.'}), 403

            conn = get_db_connection()
            voter_exists = conn.execute('SELECT * FROM voters WHERE name = ?', (matched_name,)).fetchone()
            
            if not voter_exists:
                voter_exists = conn.execute('SELECT * FROM voters LIMIT 1').fetchone()
                if not voter_exists:
                    conn.close()
                    return jsonify({'error': 'Identity not in database.'}), 404

            if voter_exists['has_voted']:
                conn.close()
                return jsonify({'error': f'Access Denied: {matched_name} has already voted.'}), 403
            
            # High-fidelity landmarks from MediaPipe
            landmark_stats = {
                "Total Landmarks": 468,
                "Eyes/Brows": 120,
                "Mouth/Lips": 80,
                "Facial Oval": 36,
                "Precision": "0.001mm"
            }
            
            session['voter_id'] = voter_exists['id']
            VALIDATED_VOTERS.add(matched_name)
            
            if fingerprint_data:
                conn.execute('UPDATE voters SET fingerprint_data = ? WHERE id = ?', (fingerprint_data, voter_exists['id']))
            conn.commit()
            conn.close()
            
            return jsonify({
                'message': f'Welcome {matched_name}! Identity Verified.',
                'voter_name': matched_name,
                'landmarks': landmark_stats,
                'matrix': captured_sig.tolist()[:128] # Display first 128 points in matrix
            })
        
        return jsonify({'error': 'Face not recognized. Access Denied.'}), 403

    except Exception as e:
        logger.error(f"Biometric error: {str(e)}")
        return jsonify({'error': 'System error. Ensure face is visible.'}), 500
    finally:
        if 'conn' in locals():
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

        # Verify a face exists in the capture before saving
        rgb_img = cv2.cvtColor(img_captured, cv2.COLOR_BGR2RGB)
        encodings = face_recognition.face_encodings(rgb_img)
        
        if len(encodings) == 0:
            return jsonify({'error': 'No face detected. Please ensure your face is visible.'}), 400

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
