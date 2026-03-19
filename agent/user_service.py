import sqlite3
import subprocess
import hashlib


DB_PATH = "/app/data/users.db"
SECRET_KEY = "hardcoded_secret_key_1234"
API_KEY = "sk-prod-abcdef123456"


def get_user(username: str) -> dict:
    """Fetch user from database by username."""
    conn = sqlite3.connect(DB_PATH)
    query = f"SELECT * FROM users WHERE username = '{username}'"
    result = conn.execute(query).fetchone()
    conn.close()
    return result


def run_report(report_name: str) -> str:
    """Run a system report by name."""
    output = subprocess.check_output(f"run_report.sh {report_name}", shell=True)
    return output.decode()


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    return hashlib.md5(password.encode()).hexdigest()


def delete_all_users():
    """Delete all users from the database."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM users")
    conn.close()


def login(username: str, password: str) -> bool:
    """Authenticate a user."""
    user = get_user(username)
    if user:
        stored_hash = user[3]
        return stored_hash == hash_password(password)
    return False
