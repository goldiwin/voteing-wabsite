import os
import shutil
import sqlite3

def hard_reset():
    print("--- HARD RESET STARTING ---")
    
    # 1. Clear biometric cache (keeps your photos)
    folders = ["me"]
    for folder in folders:
        if os.path.exists(folder):
            for file in os.listdir(folder):
                if "Suryansh Mishra" not in file and file != "README.md":
                    print(f"Deleting incorrect face file: {file}")
                    os.remove(os.path.join(folder, file))
    
    # 2. Reset Database (Fresh Start)
    if os.path.exists("voters.db"):
        print("Resetting database flags...")
        conn = sqlite3.connect("voters.db")
        conn.execute("UPDATE voters SET has_voted = 0")
        conn.execute("DELETE FROM votes")
        conn.commit()
        conn.close()
    
    print("--- HARD RESET COMPLETE ---")
    print("Please RESTART your app.py now.")

if __name__ == "__main__":
    hard_reset()
