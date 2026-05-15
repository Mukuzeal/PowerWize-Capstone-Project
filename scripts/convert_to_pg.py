"""
Convert MySQL dump to PostgreSQL-compatible SQL for Supabase import.
Run: python scripts/convert_to_pg.py
"""
import re, os

INPUT  = os.path.join(os.path.dirname(__file__), "data_export.sql")
OUTPUT = os.path.join(os.path.dirname(__file__), "supabase_import.sql")

# Tables that have SERIAL (auto-increment) primary keys — need sequence reset
SERIAL_TABLES = [
    "batches", "users", "payments", "solar_requests",
    "lms_modules", "lms_module_files", "lms_quizzes",
    "lms_quiz_questions", "lms_quiz_choices", "lms_practical_exams",
    "lms_quiz_attempts", "lms_quiz_answers", "lms_exam_submissions",
    "lms_exam_questions", "lms_exam_answers", "lms_progress",
    "lms_certificates", "feedback", "audit_logs",
]

with open(INPUT, "r", encoding="utf-8-sig") as f:
    sql = f.read()

lines = sql.splitlines()
out = []

for line in lines:
    # Skip MySQL-specific lines
    if re.match(r"^/\*!", line):             continue
    if re.match(r"^LOCK TABLES", line):      continue
    if re.match(r"^UNLOCK TABLES", line):    continue
    if re.match(r"^SET @OLD_", line):        continue
    if re.match(r"^SET @SAVED_", line):      continue
    if re.match(r"^SET TIME_ZONE", line):    continue
    if re.match(r"^/\*\!40103", line):       continue

    # Replace backtick identifiers with no quotes
    line = line.replace("`", "")

    # Replace MySQL backslash-escaped quotes with standard SQL double single-quotes
    line = line.replace("\\'", "''")

    out.append(line)

result = "\n".join(out)

# Fix INSERT table names (backticks already removed above)
# Disable FK checks equivalent for PostgreSQL
header = """-- PostgreSQL import for Supabase
-- Generated from MySQL EwizeDB dump
SET session_replication_role = 'replica';  -- disable FK checks during import

"""

# Build sequence reset statements at the end
seq_resets = "\n-- Reset sequences after import\nSET session_replication_role = 'origin';\n\n"
for tbl in SERIAL_TABLES:
    seq_resets += f"SELECT setval('{tbl}_id_seq', COALESCE((SELECT MAX(id) FROM {tbl}), 0) + 1, false);\n"

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(header + result + seq_resets)

print(f"Done! Output: {OUTPUT}")
print("Upload this file to Supabase SQL Editor and run it.")
