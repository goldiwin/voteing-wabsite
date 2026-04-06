from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from database import get_db_connection, init_db
import logging
import os
import socket
from flask_socketio import SocketIO, emit, join_room
from deepface import DeepFace
import cv2
import numpy as np
import base64
import webbrowser
from threading import Timer

def get_cv2_image_from_base64(b64_str):
    if not b64_str or ',' not in b64_str:
        return None
    encoded_data = b64_str.split(',')[1]
    nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secure_voting_secret')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('RENDER', False)  # True on Render (HTTPS)

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure Database is Initialized
logger.info("Initializing database...")
init_db()

socketio = SocketIO(app, cors_allowed_origins="*")

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

@app.route('/')
def index():
    return render_template('index.html', local_ip=get_local_ip())

@app.route('/mobile')
def mobile():
    session_id = request.args.get('session_id')
    return render_template('mobile.html', session_id=session_id)

@app.route('/api/biometrics', methods=['POST'])
def biometrics_match():
    data = request.json
    face_data = data.get('face_data')
    fingerprint_data = data.get('fingerprint_data')

    if not face_data:
        return jsonify({'error': 'Face biometric data missing'}), 400

    conn = get_db_connection()
    try:
        logger.info("New biometric verification request received.")
        
        # 1. Search for matching identity among already enrolled voters
        enrolled_voters = conn.execute('SELECT * FROM voters WHERE face_data IS NOT NULL AND has_voted = 0').fetchall()
        for v in enrolled_voters:
            img_candidate = get_cv2_image_from_base64(v['face_data'])
            img_captured = get_cv2_image_from_base64(face_data)
            
            if img_candidate is not None and img_captured is not None:
                try:
                    result = DeepFace.verify(img1_path=img_captured, img2_path=img_candidate, enforce_detection=False, model_name='VGG-Face')
                    if result.get('verified'):
                        logger.info(f"Match found for enrolled voter: {v['name']}")
                        session['voter_id'] = v['id']
                        # Update fingerprint for this session
                        conn.execute('UPDATE voters SET fingerprint_data = ? WHERE id = ?', (fingerprint_data, v['id']))
                        conn.commit()
                        return jsonify({'message': 'Identity Verified Successfully!'})
                except Exception:
                    continue

        # 2. If no match, find the first voter who is NOT yet enrolled (i.e., NO face_data)
        voter = conn.execute('SELECT * FROM voters WHERE face_data IS NULL AND has_voted = 0 LIMIT 1').fetchone()
        
        if not voter:
            # If everyone is enrolled, maybe try to match the first person anyway for demo purposes
            # but usually we want to block if no one matches.
            return jsonify({'error': 'No matching identity found or all voters have already enrolled/voted.'}), 404
            
        logger.info(f"First-time enrollment for voter: {voter['name']}")
        conn.execute('UPDATE voters SET face_data = ?, fingerprint_data = ? WHERE id = ?', 
                     (face_data, fingerprint_data, voter['id']))
        conn.commit()
        
        session['voter_id'] = voter['id']
        session.modified = True 
        logger.info(f"Identity enrolled and verified successfully for ID: {voter['id']}. Session SID: {session.get('voter_id')}")
        
        return jsonify({'message': 'Identity Enrolled & Verified Successfully!'})
    except Exception as e:
        logger.error(f"Database/Biometric error: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

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
        session.clear()
        return jsonify({'message': 'System reset successfully. All biometric data cleared.'})
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
