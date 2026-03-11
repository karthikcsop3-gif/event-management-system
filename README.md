# EventBase — Centralized Event Management System

A Python/Flask multi-user system for managing events and topics in a shared CSV file,
with AI-powered duplicate detection using TF-IDF and fuzzy matching.

---

## Quick Start

### 1. Install dependencies
```bash
pip install flask pandas scikit-learn
```

### 2. Run the server
```bash
python run.py
```

### 3. Open in browser
```
http://localhost:5000
```

---

## Default Credentials

| Role  | Username | Password  |
|-------|----------|-----------|
| Admin | admin    | admin123  |
| User  | user1    | user123   |

---

## Features

### Core
- Centralized CSV file (`data/events.csv`) with all 11 required columns
- Multi-user simultaneous access (threaded Flask server)
- Real-time updates (auto-refresh every 30 seconds)

### AI / NLP Duplicate Detection
- **TF-IDF cosine similarity** on combined Name + Overview text
- **Fuzzy string matching** (SequenceMatcher) on Name alone
- Combined score triggers warning at ≥75% similarity
- Live check as you type in the form
- Option to force-add despite duplicates

### User Roles
| Feature        | User | Admin |
|----------------|------|-------|
| View events    | ✓    | ✓     |
| Add events     | ✓    | ✓     |
| Edit events    | ✓    | ✓     |
| Delete events  | ✗    | ✓     |
| Manage users   | ✗    | ✓     |
| View logs      | ✗    | ✓     |

### Data Management
- **Validation**: date format (YYYY-MM-DD), team size (number/range), link format
- **Automatic backups** on every add/edit/delete (last 20 kept in `backups/`)
- **CSV export** via the Export button
- **Edit history** with per-event version snapshots
- **Version restore** (admin only)

### Filtering & Search
- Full-text search on event name
- Filter by date prefix, eligibility, team size

### Activity Logging
- Every login, logout, add, edit, delete, restore is logged to `data/activity.log`
- Viewable in the Admin Panel → Activity Log

---

## File Structure
```
event_system/
├── app.py              # Main Flask application
├── run.py              # Startup script
├── requirements.txt
├── templates/
│   ├── login.html
│   └── index.html
├── data/               # Created on first run
│   ├── events.csv      # Main data file
│   ├── system.db       # SQLite (users)
│   ├── history.json    # Edit snapshots
│   └── activity.log    # Action log
└── backups/            # Auto-generated CSV backups
```

---

## CSV Columns
```
id | Name | Date | Overview | Description | Eligibility | Team Size |
Event Rounds | Judging Criteria | General Rules |
Important Date and Deadline | Optional (Link) |
added_by | created_at | updated_at | updated_by
```

---

## Deployment Notes

For production:
- Replace `app.secret_key = os.urandom(32).hex()` with a fixed secret in an env var
- Use a WSGI server: `gunicorn -w 4 app:app`
- Consider adding HTTPS via nginx reverse proxy
- For true multi-server deployments, replace file-based CSV with PostgreSQL/MySQL

---

## Tech Stack
- **Python 3.8+**
- **Flask 3.x** — web framework
- **Pandas** — CSV read/write
- **scikit-learn** — TF-IDF vectorizer + cosine similarity
- **difflib** (stdlib) — fuzzy string matching
- **SQLite** (stdlib) — user authentication
- **threading.Lock** — concurrent CSV access safety
"# event-management-system" 
