# Secure Voting Web Application Plan

Create a secure voting simulation web application using Flask (Python) and SQLite for the backend, with a modern, beautiful frontend using vanilla HTML/CSS/JS.

## Proposed System Architecture
- **Backend:** Flask (Python)
- **Database:** SQLite (local `voters.db`)
- **Frontend:** HTML, Vanilla CSS (with modern aesthetics), vanilla JavaScript
- **Biometric Simulation:**
  - **Face Scan:** Access local webcam stream (via browser API) to capture an image snapshot.
  - **Fingerprint Scan:** Interactive UI element simulating a secure scan process visually.

## User Flow
1. **Registration/Login Step:** User enters Name, Father's Name, Sex, Address, Aadhaar Card No, and ID Card No.
2. **Biometrics Step:** 
   - A webcam feed launches and asks the user to scan their face (captures a snapshot).
   - An interactive area asks the user to scan their fingerprint.
3. **Information Review Step:** Displays a secure dashboard containing all elements: the user's details, the captured face snapshot, and a simulated fingerprint record.
4. **Voting Booth Step:** If verification passes and the user hasn't voted, they are presented with a list of candidates.
5. **Confirmation Step:** The vote is cast anonymously, marking the user as `has_voted`, and returning a success receipt.

## Proposed Changes

### Database Layer
#### [NEW] `database.py` (file:///c:/Users/Suryansh%20mishra/OneDrive/Documents/secure%20voting/database.py)
Set up the SQLite database initialization and helper functions.
- `Voters` Table: `id`, `aadhaar_number`, `id_card_number`, `name`, `father_name`, `sex`, `address`, `has_voted`
- `Votes` Table: `id`, `candidate_id`
- `Candidates` Table: `id`, `name`, `party`

### Backend Layer
#### [NEW] `app.py` (file:///c:/Users/Suryansh%20mishra/OneDrive/Documents/secure%20voting/app.py)
Provide Flask endpoints:
- `GET /`: Serve the main UI.
- `POST /register`: Accept voter details and create/verify voter record.
- `POST /upload_biometrics`: Accept face snapshot data.
- `GET /candidates`: Return list of candidates.
- `POST /vote`: Record the vote and update voter status, preventing double voting.

### Frontend Layer
#### [NEW] `templates/index.html` (file:///c:/Users/Suryansh%20mishra/OneDrive/Documents/secure%20voting/templates/index.html)
A single-page application (SPA) structure dividing the process into steps: Forms, Biometric Scanning (using `<video>` and `<canvas>` for webcam), Data Review, and Voting Interface.

#### [NEW] `static/style.css` (file:///c:/Users/Suryansh%20mishra/OneDrive/Documents/secure%20voting/static/style.css)
A premium, dark-mode styling with glassmorphism, glowing gradients, high-tech accents, and smooth transition animations to make the voting process feel highly advanced and secure.

#### [NEW] `static/app.js` (file:///c:/Users/Suryansh%20mishra/OneDrive/Documents/secure%20voting/static/app.js)
Handles multi-step form transitions, WebRTC (camera) API setup for the face scan, fingerprint scan CSS/JS animation, and fetching data from the Flask server.

## User Review Required

> [!IMPORTANT]
> **Webcam Requirements for Face Scan**
> The planned feature for "Scanning his face" uses the browser's native webcam API. Have you got a locally attached or laptop webcam for this to work? If not, we can simulate the "face scan" with a simple file upload or an animation instead.

> [!TIP]
> **Candidates Setup**
> By default, I will populate the database with a few generic candidates (e.g., Candidate A, Candidate B). If you have specific candidate names or parties you want to feature, please mention them!

## Verification Plan

### Manual Verification
1. Install Flask via pip.
2. Initialize database via `python database.py`.
3. Start the Flask application by running `python app.py`.
4. Open the site in the browser at `http://127.0.0.1:5000`.
5. Enter sample user details.
6. Verify webcam turns on and captures face picture.
7. Verify fingerprint animation plays.
8. Verify "Review Document" page visually renders all entered and scanned info accurately.
9. Verify submitting the vote records successfully to the DB and blocks any immediate re-voting attempts.
