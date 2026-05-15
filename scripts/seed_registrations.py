"""
Seed fake registrations into the database for admin dashboard demo.
Run once: python seed_registrations.py
"""
import uuid, random
from datetime import datetime, timedelta
from db import get_db, init_db

TITLES = ["Mr.", "Ms.", "Mrs.", "Engr.", "Dr."]
FIRST_NAMES = [
    "Juan", "Maria", "Jose", "Ana", "Carlos", "Rosa", "Miguel", "Liza",
    "Roberto", "Carla", "Emmanuel", "Patricia", "Mark", "Christine", "Felix",
    "Joanna", "Ronald", "Sheryl", "Dennis", "Maricel",
]
LAST_NAMES = [
    "Santos", "Reyes", "Cruz", "Bautista", "Ocampo", "Garcia", "Mendoza",
    "Torres", "Flores", "Villanueva", "Ramos", "Castillo", "Aquino", "Dela Cruz",
    "Navarro", "Gonzales", "Salazar", "Dizon", "Lim", "Tan",
]
MIDDLE_NAMES = ["A.", "B.", "C.", "D.", "E.", "F.", "G.", "H.", "L.", "M.", "P.", "R.", "S.", "V."]
COMPANIES = [
    "Manila Electric Company", "Meralco Industrial", "PLDT Enterprise",
    "SM Prime Holdings", "Ayala Land Inc.", "Filinvest Development Corp.",
    "Philippine National Oil Company", "National Power Corporation",
    "First Gen Corporation", "Energy Development Corporation",
    "Aboitiz Power Corp.", "Global Business Power", "SN Aboitiz Power",
    "Trans-Asia Oil and Energy", "Petron Corporation",
]
DESIGNATIONS = [
    "Energy Manager", "Facilities Engineer", "Plant Engineer",
    "Operations Manager", "Project Engineer", "Electrical Engineer",
    "Building Administrator", "Chief Engineer", "Energy Auditor",
    "Maintenance Supervisor",
]
CITIES = [
    "Makati City", "Taguig City", "Quezon City", "Pasig City",
    "Mandaluyong City", "San Juan City", "Parañaque City", "Pasay City",
    "Caloocan City", "Marikina City",
]

FORM_TYPES = [
    ("cea_renewal",   "CEA Renewal"),
    ("cem_renewal",   "CEM Renewal"),
    ("cea_training",  "CEA Training"),
    ("training",      "Training Registration"),
]

TRAINING_OPTIONS = {
    "cea_renewal":  ["Face to Face, Renewal of CEA", "Online Live, Renewal of CEA"],
    "cem_renewal":  ["Face to Face, Renewal of CEM", "Online Live, Renewal of CEM"],
    "cea_training": ["Self-paced Online, CEA Training Program", "Self-paced Face to Face, CEA Training Program"],
    "training":     ["Self-paced Online, CEM Training Program", "Self-paced Face to Face, CEM Training Program", "Hybrid, CEM Training Program"],
}

STATUSES = ["pending", "pending", "pending", "accepted", "accepted", "rejected"]


def rand_id():
    return str(uuid.uuid4())[:8].upper()


def rand_date(days_back=90):
    delta = random.randint(0, days_back)
    dt = datetime.now() - timedelta(days=delta)
    return dt.strftime("%Y-%m-%d %H:%M")


def rand_birthdate():
    year  = random.randint(1970, 1998)
    month = random.randint(1, 12)
    day   = random.randint(1, 28)
    return f"{year}-{month:02d}-{day:02d}"


def rand_age(birthdate_str):
    bd = datetime.strptime(birthdate_str, "%Y-%m-%d")
    return str((datetime.now() - bd).days // 365)


def rand_doe_expiry():
    year  = random.randint(2024, 2027)
    month = random.randint(1, 12)
    return f"{year}-{month:02d}-01"


def seed(count=30):
    init_db()
    conn = get_db()
    cur  = conn.cursor()

    inserted = 0
    for _ in range(count):
        fname = random.choice(FIRST_NAMES)
        lname = random.choice(LAST_NAMES)
        mname = random.choice(MIDDLE_NAMES)
        title = random.choice(TITLES)
        full_name = f"{fname} {lname}"
        company   = random.choice(COMPANIES)
        city      = random.choice(CITIES)
        desig     = random.choice(DESIGNATIONS)
        bd        = rand_birthdate()
        form_type, form_label = random.choice(FORM_TYPES)
        training_type = random.choice(TRAINING_OPTIONS[form_type])
        status    = random.choice(STATUSES)
        submitted = rand_date()
        doe_exp   = rand_doe_expiry() if "renewal" in form_type else None
        email     = f"{fname.lower()}.{lname.lower().replace(' ','')}@{company.split()[0].lower()}.com.ph"
        contact   = f"09{random.randint(100000000, 999999999)}"

        try:
            cur.execute("""
                INSERT INTO registrations (
                    id, form_type, form_label, submitted_at,
                    title, full_name, middle_name, residence,
                    company_name, designation, company_address,
                    contact_number, email, birthdate, age, doe_expiry,
                    training_type, batch_id,
                    photo_id, resume, expired_doe, valid_id,
                    status
                ) VALUES (
                    %s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s,%s,%s,
                    %s,%s,
                    %s,%s,%s,%s,
                    %s
                )
            """, (
                rand_id(), form_type, form_label, submitted,
                title, full_name, mname, city,
                company, desig, f"{random.randint(1,999)} {city}",
                contact, email, bd, rand_age(bd), doe_exp,
                training_type, None,
                None, None, None, None,
                status,
            ))
            inserted += 1
        except Exception as e:
            print(f"  Skipped (duplicate id?): {e}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"Done — {inserted} fake registrations inserted.")


if __name__ == "__main__":
    seed(30)
