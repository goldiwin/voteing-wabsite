import sqlite3
conn = sqlite3.connect('voters.db')
cursor = conn.cursor()
cursor.execute("SELECT name, has_voted FROM voters WHERE name = 'Suryansh Mishra'")
print(f"DEBUG_RESULT: {cursor.fetchall()}")
conn.close()
