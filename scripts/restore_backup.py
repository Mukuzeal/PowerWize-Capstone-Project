#!/usr/bin/env python3
import mysql.connector

print("Restoring ewizedb from backup...")

# Connect to MySQL
conn = mysql.connector.connect(host='localhost', user='root', password='')
cursor = conn.cursor()

try:
    # Read the SQL dump
    with open('ewizedb_backup.sql', 'r', encoding='utf-8') as f:
        sql_content = f.read()

    # Drop and recreate the database
    print("  Dropping existing database...")
    cursor.execute('DROP DATABASE IF EXISTS ewizedb')

    print("  Creating fresh database...")
    cursor.execute('CREATE DATABASE ewizedb')
    cursor.execute('USE ewizedb')
    conn.commit()

    # Execute statements from dump
    statements = [s.strip() for s in sql_content.split(';') if s.strip() and not s.strip().startswith('--')]

    print(f"  Executing {len(statements)} SQL statements...")
    success_count = 0
    for i, statement in enumerate(statements, 1):
        try:
            cursor.execute(statement)
            success_count += 1
            if i % 50 == 0:
                print(f"    {i}/{len(statements)}...")
        except mysql.connector.Error as e:
            if 'Query is empty' not in str(e):
                print(f"  Warning in statement {i}: {str(e)[:80]}")

    conn.commit()

    # Verify tables
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()

    print(f"\nRestore complete!")
    print(f"  Tables restored: {len(tables)}")
    for table in tables:
        print(f"    - {table[0]}")

finally:
    cursor.close()
    conn.close()
