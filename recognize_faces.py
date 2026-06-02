import face_recognition
import cv2
import os
import numpy as np

# Load known faces
known_encodings = []
known_names = []

# Paths to search for known face images
paths = ["me"]

# Ensure at least the faces directory exists
if not os.path.exists("me"):
    os.makedirs("me")

for path in paths:
    if os.path.exists(path):
        print(f"Loading faces from directory: {path}")
        for file in os.listdir(path):
            if file.lower().endswith((".jpg", ".png", ".jpeg", ".webp")):
                file_path = os.path.join(path, file)
                try:
                    img = face_recognition.load_image_file(file_path)
                    encodings = face_recognition.face_encodings(img)
                    if len(encodings) > 0:
                        encoding = encodings[0]
                        known_encodings.append(encoding)
                        
                        import re
                        name = os.path.splitext(file)[0]
                        name = re.sub(r'(_\d+|\(\d+\)|\s\d+)$', '', name).strip()
                        
                        known_names.append(name)
                        print(f"  Loaded face: {name} (from {file})")
                    else:
                        print(f"  No face found in {file}")
                except Exception as e:
                    print(f"  Error loading {file}: {e}")

print("System Ready! Waiting for camera...")

# Start webcam
video = cv2.VideoCapture(0)

last_recognized_name = None

while True:
    ret, frame = video.read()
    if not ret:
        break
    
    # Use a larger frame for higher accuracy (0.5 instead of 0.25)
    small_frame = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
    rgb_frame = small_frame[:, :, ::-1]

    # Detect faces with upsampling for better accuracy
    face_locations = face_recognition.face_locations(rgb_frame, number_of_times_to_upsample=1)
    face_encodings = face_recognition.face_encodings(rgb_frame, face_locations, num_jitters=2)

    for face_encoding, face_location in zip(face_encodings, face_locations):
        matches = face_recognition.compare_faces(known_encodings, face_encoding)
        name = "Unknown"
        status = "UNKNOWN FACE"
        color = (0, 0, 255) # Red for unknown / not recognized

        if len(known_encodings) > 0:
            face_distances = face_recognition.face_distance(known_encodings, face_encoding)
            best_match = np.argmin(face_distances)

            if matches[best_match]:
                name = known_names[best_match]
                
                # Check database for voting status
                import sqlite3
                conn = sqlite3.connect('voters.db')
                conn.row_factory = sqlite3.Row
                voter = conn.execute('SELECT has_voted FROM voters WHERE name = ?', (name,)).fetchone()
                conn.close()
                
                status = ""
                if voter:
                    if voter['has_voted']:
                        status = "ALREADY VOTED - REJECTED"
                        color = (0, 0, 255) # Red
                    else:
                        status = "ACCESS GRANTED"
                        color = (0, 255, 0) # Green
                else:
                    status = "NOT IN DATABASE"
                    color = (0, 255, 255) # Yellow

                if name != last_recognized_name:
                    print(f"SCAN SUCCESSFUL: Recognized {name} - Status: {status}")
                    last_recognized_name = name

        # Scale back up face location (since we resized to 0.5, we multiply by 2)
        top, right, bottom, left = [v * 2 for v in face_location]

        # Draw rectangle and text
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        cv2.putText(frame, f"{name}: {status}", (left, top - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    cv2.imshow("Face Recognition System", frame)

    if cv2.waitKey(1) & 0xFF == 27:  # Press ESC to exit
        break

video.release()
cv2.destroyAllWindows()
