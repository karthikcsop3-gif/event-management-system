"""
Event Management System - Main Application
Flask-based multi-user event/topic CSV management with NLP duplicate detection
"""

import os
import json
import csv
import sqlite3
import hashlib
import shutil
import threading
import re
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, render_template, request, jsonify,
                   session, redirect, url_for, send_file, g)
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import difflib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Indian Standard Time helper
def ist_now():
    return datetime.now(ZoneInfo("Asia/Kolkata"))



# ─── App Setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.urandom(32).hex()

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, "data")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
CSV_FILE   = os.path.join(DATA_DIR, "events.csv")
DB_FILE    = os.path.join(DATA_DIR, "system.db")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
LOG_FILE   = os.path.join(DATA_DIR, "activity.log")

CSV_COLUMNS = [
    "id", "Name", "Date", "Overview", "Description",
    "Eligibility", "Team Size", "Event Rounds",
    "Judging Criteria", "General Rules",
    "Important Date and Deadline", "Optional (Link)",
    "added_by", "created_at", "updated_at", "updated_by"
]

csv_lock = threading.Lock()

# ─── DB Init ──────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL
        )
    """)

    # Default admin — role fixed from "AD019" to "admin"
    pwd = hashlib.sha256("63616893".encode()).hexdigest()
    c.execute(
        "INSERT OR IGNORE INTO users (username,password,role,created_at) VALUES (?,?,?,?)",
        ("AD019", pwd, "admin", datetime.now().isoformat())
    )

    # Default demo user
    pwd2 = hashlib.sha256("user123".encode()).hexdigest()
    c.execute(
        "INSERT OR IGNORE INTO users (username,password,role,created_at) VALUES (?,?,?,?)",
        ("user1", pwd2, "user", datetime.now().isoformat())
    )

    # Multiple users with unique passwords
    users = {
        "omkar01": "omk@291",
        "darshan01": "dar@482",
        "prajwal01": "pra@735",
        "namratha01": "nam@864",
        "shobitha01": "sho@519"
    }

    for username, password in users.items():
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        c.execute(
            "INSERT OR IGNORE INTO users (username,password,role,created_at) VALUES (?,?,?,?)",
            (username, pwd_hash, "user", datetime.now().isoformat())
        )

    conn.commit()
    conn.close()

def init_csv():
    if not os.path.exists(CSV_FILE):
        df = pd.DataFrame(columns=CSV_COLUMNS)
        df.to_csv(CSV_FILE, index=False)

def init_history():
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "w") as f:
            json.dump({}, f)

# Indian Standard Time helper

def ist_now():
    return datetime.now(ZoneInfo("Asia/Kolkata"))

# ─── Helpers ──────────────────────────────────────────────────────────────────
def log_activity(action, user, detail=""):
    ts = ist_now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] USER={user} ACTION={action} DETAIL={detail}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def read_csv():
    with csv_lock:
        if not os.path.exists(CSV_FILE):
            return pd.DataFrame(columns=CSV_COLUMNS)
        df = pd.read_csv(CSV_FILE, dtype=str).fillna("")
        return df

def write_csv(df):
    with csv_lock:
        df.to_csv(CSV_FILE, index=False)

def backup_csv():
    if os.path.exists(CSV_FILE):
        ts = ist_now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(BACKUP_DIR, f"events_backup_{ts}.csv")
        shutil.copy2(CSV_FILE, dest)
        # Keep only last 20 backups
        backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".csv")])
        for old in backups[:-20]:
            os.remove(os.path.join(BACKUP_DIR, old))

def next_id(df):
    if df.empty or "id" not in df.columns or df["id"].eq("").all():
        return "1"
    ids = pd.to_numeric(df["id"], errors="coerce").dropna()
    return str(int(ids.max()) + 1) if len(ids) else "1"

def validate_entry(data):
    errors = []
    # Date format
    date_val = data.get("Date", "").strip()
    if date_val:
        try:
            datetime.strptime(date_val, "%Y-%m-%d")
        except ValueError:
            errors.append("Date must be in YYYY-MM-DD format.")
    # Team size numeric
    ts = data.get("Team Size", "").strip()
    if ts and not re.match(r"^\d+(-\d+)?$", ts):
        errors.append("Team Size must be a number or range (e.g. 2-5).")
    # Optional link
    link = data.get("Optional (Link)", "").strip()
    if link and not re.match(r"^https?://", link):
        errors.append("Link must start with http:// or https://")
    # Required
    if not data.get("Name", "").strip():
        errors.append("Name is required.")
    return errors

# ─── NLP Duplicate Detection ──────────────────────────────────────────────────
def fuzzy_ratio(a, b):
    """SequenceMatcher similarity 0-1"""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()

def check_duplicates(new_name, new_overview, df, threshold=0.75, exclude_id=None):
    """
    Returns list of potential duplicate rows with similarity scores.
    Uses TF-IDF cosine similarity on Name+Overview combined text,
    plus fuzzy matching on Name alone.
    """
    if df.empty:
        return []

    working = df.copy()
    if exclude_id:
        working = working[working["id"] != str(exclude_id)]
    if working.empty:
        return []

    new_text = f"{new_name} {new_overview}".strip()
    existing_texts = (working["Name"].fillna("") + " " + working["Overview"].fillna("")).tolist()

    duplicates = []

    # TF-IDF cosine similarity
    try:
        corpus = existing_texts + [new_text]
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        tfidf_matrix = vectorizer.fit_transform(corpus)
        scores = cosine_similarity(tfidf_matrix[-1], tfidf_matrix[:-1])[0]

        for i, score in enumerate(scores):
            row = working.iloc[i]
            fuzzy = fuzzy_ratio(new_name, row["Name"])
            combined = max(float(score), fuzzy)
            if combined >= threshold:
                duplicates.append({
                    "id": row["id"],
                    "name": row["Name"],
                    "similarity": round(combined * 100, 1),
                    "method": "TF-IDF + Fuzzy"
                })
    except Exception:
        # Fallback: pure fuzzy
        for _, row in working.iterrows():
            fuzzy = fuzzy_ratio(new_name, row["Name"])
            if fuzzy >= threshold:
                duplicates.append({
                    "id": row["id"],
                    "name": row["Name"],
                    "similarity": round(fuzzy * 100, 1),
                    "method": "Fuzzy"
                })

    # Sort by similarity desc
    duplicates.sort(key=lambda x: x["similarity"], reverse=True)
    return duplicates

# ─── Auth decorator ───────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("index.html", user=session["user"], role=session["role"])

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        data = request.get_json() or request.form
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()
        conn = get_db()
        row = conn.execute("SELECT * FROM users WHERE username=? AND password=?",
                           (username, hash_password(password))).fetchone()
        conn.close()
        if row:
            session["user"] = username
            session["role"] = row["role"]
            session["uid"]  = row["id"]
            log_activity("LOGIN", username)
            if request.is_json:
                return jsonify({"success": True, "role": row["role"]})
            return redirect(url_for("index"))
        if request.is_json:
            return jsonify({"error": "Invalid credentials"}), 401
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
def logout():
    user = session.get("user", "?")
    log_activity("LOGOUT", user)
    session.clear()
    return redirect(url_for("login"))

# ─── Events API ───────────────────────────────────────────────────────────────
@app.route("/api/events", methods=["GET"])
@login_required
def get_events():
    df = read_csv()
    # Filtering
    name_q  = request.args.get("name", "").lower()
    date_q  = request.args.get("date", "")
    elig_q  = request.args.get("eligibility", "").lower()
    tsize_q = request.args.get("team_size", "").lower()

    if name_q:
        df = df[df["Name"].str.lower().str.contains(name_q, na=False)]
    if date_q:
        df = df[df["Date"].str.startswith(date_q, na=False)]
    if elig_q:
        df = df[df["Eligibility"].str.lower().str.contains(elig_q, na=False)]
    if tsize_q:
        df = df[df["Team Size"].str.lower().str.contains(tsize_q, na=False)]

    return jsonify(df.to_dict(orient="records"))

@app.route("/api/events/<event_id>", methods=["GET"])
@login_required
def get_event(event_id):
    df = read_csv()
    row = df[df["id"] == str(event_id)]
    if row.empty:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row.iloc[0].to_dict())

@app.route("/api/events", methods=["POST"])
@login_required
def add_event():
    data = request.get_json()
    errors = validate_entry(data)
    if errors:
        return jsonify({"errors": errors}), 400

    df = read_csv()

    # Duplicate check
    dups = check_duplicates(
        data.get("Name", ""),
        data.get("Overview", ""),
        df
    )
    if dups and not data.get("force_add"):
        return jsonify({"duplicates": dups, "needs_confirm": True}), 409

    backup_csv()

    new_row = {col: data.get(col, "") for col in CSV_COLUMNS}
    new_row["id"]         = next_id(df)
    new_row["added_by"]   = session["user"]
    new_row["created_at"] = datetime.now().isoformat()
    new_row["updated_at"] = datetime.now().isoformat()
    new_row["updated_by"] = session["user"]

    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    write_csv(df)
    log_activity("ADD_EVENT", session["user"], f"id={new_row['id']} name={new_row['Name']}")
    return jsonify({"success": True, "id": new_row["id"]})

@app.route("/api/events/<event_id>", methods=["PUT"])
@login_required
def update_event(event_id):
    if session["role"] not in ("admin", "user"):
        return jsonify({"error": "Not allowed"}), 403

    data = request.get_json()
    errors = validate_entry(data)
    if errors:
        return jsonify({"errors": errors}), 400

    df = read_csv()
    idx = df.index[df["id"] == str(event_id)]
    if len(idx) == 0:
        return jsonify({"error": "Not found"}), 404
    i = idx[0]

    # Duplicate check excluding self
    dups = check_duplicates(
        data.get("Name", ""),
        data.get("Overview", ""),
        df,
        exclude_id=event_id
    )
    if dups and not data.get("force_add"):
        return jsonify({"duplicates": dups, "needs_confirm": True}), 409

    # Save history
    old = df.iloc[i].to_dict()
    history = {}
    with open(HISTORY_FILE) as f:
        history = json.load(f)
    hkey = str(event_id)
    if hkey not in history:
        history[hkey] = []
    history[hkey].append({
        "snapshot": old,
        "saved_at": datetime.now().isoformat(),
        "saved_by": session["user"]
    })
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

    backup_csv()

    for col in CSV_COLUMNS:
        if col in data and col not in ("id", "added_by", "created_at"):
            df.at[i, col] = data[col]
    df.at[i, "updated_at"] = datetime.now().isoformat()
    df.at[i, "updated_by"] = session["user"]

    write_csv(df)
    log_activity("EDIT_EVENT", session["user"], f"id={event_id}")
    return jsonify({"success": True})

@app.route("/api/events/<event_id>", methods=["DELETE"])
@login_required
@admin_required
def delete_event(event_id):
    df = read_csv()
    if df[df["id"] == str(event_id)].empty:
        return jsonify({"error": "Not found"}), 404
    backup_csv()
    df = df[df["id"] != str(event_id)]
    write_csv(df)
    log_activity("DELETE_EVENT", session["user"], f"id={event_id}")
    return jsonify({"success": True})

@app.route("/api/events/<event_id>/history", methods=["GET"])
@login_required
def get_history(event_id):
    with open(HISTORY_FILE) as f:
        history = json.load(f)
    return jsonify(history.get(str(event_id), []))

@app.route("/api/events/<event_id>/restore/<int:version>", methods=["POST"])
@login_required
@admin_required
def restore_version(event_id, version):
    with open(HISTORY_FILE) as f:
        history = json.load(f)
    versions = history.get(str(event_id), [])
    if version >= len(versions):
        return jsonify({"error": "Version not found"}), 404
    snapshot = versions[version]["snapshot"]
    df = read_csv()
    idx = df.index[df["id"] == str(event_id)]
    if len(idx) == 0:
        return jsonify({"error": "Event not found"}), 404
    backup_csv()
    for col in CSV_COLUMNS:
        if col in snapshot:
            df.at[idx[0], col] = snapshot[col]
    df.at[idx[0], "updated_at"] = datetime.now().isoformat()
    df.at[idx[0], "updated_by"] = f"{session['user']} (restore v{version})"
    write_csv(df)
    log_activity("RESTORE_VERSION", session["user"], f"id={event_id} v={version}")
    return jsonify({"success": True})

@app.route("/api/check_duplicate", methods=["POST"])
@login_required
def check_dup_api():
    data = request.get_json()
    df   = read_csv()
    dups = check_duplicates(
        data.get("name", ""),
        data.get("overview", ""),
        df,
        exclude_id=data.get("exclude_id")
    )
    return jsonify({"duplicates": dups})

# ─── Admin APIs ───────────────────────────────────────────────────────────────
@app.route("/api/admin/users", methods=["GET"])
@login_required
@admin_required
def list_users():
    conn = get_db()
    rows = conn.execute("SELECT id,username,role,created_at FROM users").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/admin/users", methods=["POST"])
@login_required
@admin_required
def create_user():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    role     = data.get("role", "user")
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    conn = get_db()
    try:
        conn.execute("INSERT INTO users (username,password,role,created_at) VALUES (?,?,?,?)",
                     (username, hash_password(password), role, datetime.now().isoformat()))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Username already exists"}), 409
    conn.close()
    log_activity("CREATE_USER", session["user"], f"new_user={username} role={role}")
    return jsonify({"success": True})

@app.route("/api/admin/users/<int:uid>", methods=["DELETE"])
@login_required
@admin_required
def delete_user(uid):
    if uid == session.get("uid"):
        return jsonify({"error": "Cannot delete yourself"}), 400
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/admin/logs", methods=["GET"])
@login_required
@admin_required
def get_logs():
    if not os.path.exists(LOG_FILE):
        return jsonify([])
    with open(LOG_FILE) as f:
        lines = f.readlines()
    return jsonify(lines[-200:])  # last 200 lines

@app.route("/api/admin/backups", methods=["GET"])
@login_required
@admin_required
def list_backups():
    files = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".csv")], reverse=True)
    return jsonify(files[:20])

# ─── Export / Download ────────────────────────────────────────────────────────
@app.route("/api/export")
@login_required
def export_csv():
    log_activity("EXPORT", session["user"])
    return send_file(CSV_FILE, as_attachment=True, download_name="events_export.csv")

# ─── Startup ──────────────────────────────────────────────────────────────────

# 1. MOVED OUTSIDE __main__: 
# Gunicorn will now successfully run these when it imports your app on Render
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
init_db()
init_csv()
init_history()

# 2. LOCAL RUN BLOCK:
if __name__ == "__main__":
    print("\n" + "="*60)
    print("  Event Management System")
    print("  http://localhost:5000")
    print("="*60 + "\n")
    
    # Dynamic port binding for Render (in case it runs via python directly)
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
