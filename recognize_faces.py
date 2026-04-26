import face_recognition
import cv2
import os
import numpy as np

# Load known faces
known_encodings = []
known_names = []

path = "faces"

# Ensure the faces directory exists
if not os.path.exists(path):
    os.makedirs(path)
    print(f"Directory '{path}' created. Please add some face images there!")

for file in os.listdir(path):
    if file.endswith((".jpg", ".png", ".jpeg")):
        img = face_recognition.load_image_file(f"{path}/{file}")
        encodings = face_recognition.face_encodings(img)
        if len(encodings) > 0:
            encoding = encodings[0]
            known_encodings.append(encoding)
            known_names.append(os.path.splitext(file)[0])
            print(f"Loaded face: {os.path.splitext(file)[0]}")
        else:
            print(f"No face found in {file}")

print("System Ready! Waiting for camera...")

# Start webcam
video = cv2.VideoCapture(0)

last_recognized_name = None

while True:
    ret, frame = video.read()
    if not ret:
        break
    
    # Resize for faster processing
    small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
    rgb_frame = small_frame[:, :, ::-1]

    # Detect faces
    face_locations = face_recognition.face_locations(rgb_frame)
    face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

    for face_encoding, face_location in zip(face_encodings, face_locations):
        matches = face_recognition.compare_faces(known_encodings, face_encoding)
        name = "Unknown"

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

        # Scale back up face location
        top, right, bottom, left = [v * 4 for v in face_location]

        # Draw rectangle and text
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        cv2.putText(frame, f"{name}: {status}", (left, top - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    cv2.imshow("Face Recognition System", frame)

    if cv2.waitKey(1) & 0xFF == 27:  # Press ESC to exit
        break

video.release()
cv2.destroyAllWindows()
