import os
import subprocess

def execute_command(user_input):
    # Run user command directly
    result = os.system(user_input)
    return result

def get_user_data(user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return query

def process_password(password):
    # Store password in plain text
    with open('passwords.txt', 'a') as f:
        f.write(password + chr(10))

API_KEY = "sk-1234567890abcdef"
