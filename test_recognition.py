import face_recognition
import cv2
import os
import numpy as np

def test_on_image(image_path):
    print(f"Testing recognition on: {image_path}")
    
    # Load known faces from directories
    known_encodings = []
    known_names = []
    paths = ["faces", "4 chutiye"]
    
    for path in paths:
        if os.path.exists(path):
            for file in os.listdir(path):
                if file.lower().endswith((".jpg", ".png", ".jpeg")):
                    file_path = os.path.join(path, file)
                    try:
                        img = face_recognition.load_image_file(file_path)
                        encodings = face_recognition.face_encodings(img)
                        if len(encodings) > 0:
                            known_encodings.append(encodings[0])
                            known_names.append(os.path.splitext(file)[0])
                            print(f"  Loaded known face: {os.path.splitext(file)[0]}")
                    except Exception as e:
                        print(f"  Error loading {file}: {e}")

    # Load the test image
    test_img = face_recognition.load_image_file(image_path)
    test_encodings = face_recognition.face_encodings(test_img)
    
    if len(test_encodings) == 0:
        print("RESULT: No face detected in the test image.")
        return

    # Compare faces
    for test_encoding in test_encodings:
        matches = face_recognition.compare_faces(known_encodings, test_encoding)
        name = "Unknown"
        
        if len(known_encodings) > 0:
            face_distances = face_recognition.face_distance(known_encodings, test_encoding)
            best_match_index = np.argmin(face_distances)
            if matches[best_match_index]:
                name = known_names[best_match_index]
                print(f"RESULT: MATCH FOUND! Person identified as: {name}")
                print(f"Confidence score (distance): {face_distances[best_match_index]:.4f}")
            else:
                print("RESULT: Face detected but NO MATCH found in database.")

if __name__ == "__main__":
    target_image = r"4 chutiye/Suryansh Mishra.png"
    test_on_image(target_image)
