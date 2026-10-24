"""Intentionally vulnerable sample for white-box review tests. Do not deploy."""
import sqlite3

from flask import Flask, request

app = Flask(__name__)

# Hardcoded credential (fake, for detection tests only).
DB_PASSWORD = "example-not-a-real-secret"


@app.route("/user")
def get_user():
    name = request.args.get("name", "")
    conn = sqlite3.connect("app.db")
    # Vulnerable: user input concatenated into the SQL statement.
    rows = conn.execute("SELECT id, email FROM users WHERE name = '" + name + "'").fetchall()
    return {"users": rows}
