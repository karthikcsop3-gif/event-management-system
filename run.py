#!/usr/bin/env python3

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
for d in ["data","backups","static"]:
    os.makedirs(os.path.join(BASE,d), exist_ok=True)

# Add project to path and run
sys.path.insert(0, BASE)
from app import app, init_db, init_csv, init_history, DATA_DIR, BACKUP_DIR

# These stay OUTSIDE the main block so Gunicorn runs them to set up your DB/CSV
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
init_db()
init_csv()
init_history()

# Protect the local execution so Gunicorn ignores it on Render
if __name__ == "__main__":
    print("\n" + "="*60)
    print("Event Management System")
    print("  http://localhost:5000")
    print()
    print("="*60 + "\n")
    
    # Dynamic port binding just in case
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)