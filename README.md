# EnergyWize – DOE-CEA Renewal Registration System

A Flask-based registration form for DOE-CEA certificate renewal.

## Project Structure

```
energywize/
├── app.py                   ← Flask backend
├── requirements.txt
├── static/
│   └── uploads/             ← Uploaded files saved here
└── templates/
    ├── index.html           ← Registration form
    ├── success.html         ← Confirmation page
    └── admin.html           ← Admin view of all registrations
```

## Setup & Run

```bash
# 1. Create and activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate        # Mac/Linux
venv\Scripts\activate           # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python app.py
```

Then open your browser to: **http://localhost:5000**

## Pages

| URL | Description |
|-----|-------------|
| `/` | Registration form |
| `/register` | POST endpoint (form submission) |
| `/admin` | View all submitted registrations |

## Notes

- Uploaded files are saved in `static/uploads/` with UUID-based filenames.
- Registrations are stored in memory — restart clears them.
  For production, replace the `registrations` list with a real database (SQLite, PostgreSQL, etc.).
- To use a database, install `flask-sqlalchemy` and define a `Registration` model.
