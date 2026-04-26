import sqlite3
import os

def init_db():
    conn = sqlite3.connect('voters.db')
    cursor = conn.cursor()

    # Create Voters Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS voters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        aadhaar_number TEXT UNIQUE NOT NULL,
        id_card_number TEXT UNIQUE NOT NULL,
        voter_id_number TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        father_name TEXT,
        sex TEXT,
        age INTEGER,
        address TEXT,
        face_data TEXT, 
        fingerprint_data TEXT,
        has_voted INTEGER DEFAULT 0
    )
    ''')

    # Create Candidates Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL
    )
    ''')

    # Create Votes Table 
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER,
        FOREIGN KEY (candidate_id) REFERENCES candidates (id)
    )
    ''')

    # Seed Mock Biometric Identities 
    voters = [
        ('6105 2059 34 50', 'NAT-ID-001', 'VID-001', 'Suryansh Mishra', 'Shri Vinod Kumar Mishra', 'Male', 20, 'Uttar Pradesh, Pilibhit'),
        ('1234 5678 90 12', 'NAT-ID-002', 'VID-002', 'Kanwal Preet Kaur', 'Suryansh Mishra', 'Female', 22, 'Punjab'),
        ('4455 6677 88 99', 'NAT-ID-003', 'VID-003', 'Tanisk', 'Suryansh Mishra', 'Male', 21, 'Uttarakhand'),
        ('9988 7766 55 44', 'NAT-ID-004', 'VID-004', 'Mansi', 'Suryansh Mishra', 'Female', 23, 'Gurgaon')
    ]
    cursor.executemany('''
        INSERT OR IGNORE INTO voters (aadhaar_number, id_card_number, voter_id_number, name, father_name, sex, age, address)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', voters)

    # Seed Candidates
    candidates = [
        ('Alice Smith',),
        ('Bob Jones',),
        ('Charlie Brown',)
    ]
    cursor.executemany('INSERT OR IGNORE INTO candidates (name) VALUES (?)', candidates)

    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def get_db_connection():
    conn = sqlite3.connect('voters.db')
    conn.row_factory = sqlite3.Row
    return conn

if __name__ == '__main__':
    init_db()
