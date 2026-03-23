"""Demo file with intentional vulnerabilities for video demonstration."""

import os
import pickle
import sqlite3
import subprocess

from flask import Flask, request, redirect

app = Flask(__name__)

# Hardcoded credentials
DB_PASSWORD = "admin123"
API_SECRET = "sk-live-a1b2c3d4e5f6g7h8i9j0"
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def get_db():
    return sqlite3.connect("app.db")


@app.route("/login", methods=["POST"])
def login():
    username = request.form["username"]
    password = request.form["password"]
    # SQL Injection — user input directly in query
    db = get_db()
    cursor = db.execute(
        f"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'"
    )
    user = cursor.fetchone()
    if user:
        return f"Welcome {username}"
    return "Invalid credentials", 401


@app.route("/search")
def search():
    query = request.args.get("q", "")
    # XSS — rendering user input without escaping
    return f"<html><body><h1>Results for: {query}</h1></body></html>"


@app.route("/run")
def run_command():
    cmd = request.args.get("cmd", "ls")
    # Command Injection — executing user input directly
    output = subprocess.check_output(cmd, shell=True)
    return output.decode()


@app.route("/redirect")
def unsafe_redirect():
    url = request.args.get("url", "/")
    # Open Redirect — no validation on redirect target
    return redirect(url)


@app.route("/upload", methods=["POST"])
def upload():
    data = request.get_data()
    # Insecure Deserialization — pickle.loads on untrusted input
    obj = pickle.loads(data)
    return str(obj)


@app.route("/file")
def read_file():
    filename = request.args.get("name", "")
    # Path Traversal — no sanitization of file path
    with open(f"/data/{filename}", "r") as f:
        return f.read()


@app.route("/admin")
def admin_panel():
    # Missing authentication — no auth check on sensitive endpoint
    db = get_db()
    users = db.execute("SELECT username, password FROM users").fetchall()
    return str(users)


@app.route("/debug")
def debug_info():
    # Information Disclosure — exposing environment variables
    return {
        "env": dict(os.environ),
        "db_password": DB_PASSWORD,
        "api_secret": API_SECRET,
    }


def process_user_data(data: dict) -> dict:
    # No input validation at all
    age = data["age"]
    eval(data["formula"])  # Arbitrary code execution via eval
    return {"status": "processed", "age": age}


if __name__ == "__main__":
    # Debug mode enabled in production
    app.run(host="0.0.0.0", port=5000, debug=True)
