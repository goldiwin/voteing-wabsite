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
        ('6105 2059 34 50', 'NAT-ID-88392', '125 17899', 'Suryansh Mishra', 'Shri Vinod Kumar Mishra', 'Male', 20, 'uttar pradesh , pilibhit , bisalpur , mighauna, 262201'),
        ('1234567', '9876', '9876-VID', 'Tanisk', 'Suryansh Mishra', 'Male', 322, 'Uttarakhand'),
        ('4455 6677 88 99', 'NAT-ID-11223', 'VID-003', 'Priya Sharma', 'Rajesh Sharma', 'Female', 25, 'Delhi, India'),
        ('9988 7766 55 44', 'NAT-ID-44556', 'VID-004', 'Amit Verma', 'Sanjay Verma', 'Male', 29, 'Mumbai, Maharashtra'),
        ('1122 3344 55 66', 'NAT-ID-77889', 'VID-005', 'Anjali Gupta', 'Manoj Gupta', 'Female', 22, 'Bangalore, Karnataka'),
        ('566789', '125188888', '125188888-VID', 'Kamal Preet', 'Suryansh Mishra', 'Male', 20, 'Punjab'),
        ('678989', '678987654', '678987654-VID', 'Mansi', 'Suryansh Mishra', 'Female', 89, 'Gurgaon')
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
