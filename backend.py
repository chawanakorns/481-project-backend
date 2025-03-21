import sqlite3
from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
import bcrypt  # Import the bcrypt module
import os

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

USERS_DB = os.path.join(BASE_DIR, 'database', 'users.db')  # Path to your users.db file
FOOD_DB = os.path.join(BASE_DIR, 'database', 'food.db')  # Path to your food.db file


# Create a function to get a database connection for users database
def get_user_db_connection():
    conn = sqlite3.connect(USERS_DB)
    conn.row_factory = sqlite3.Row
    return conn


# Create a function to get a database connection for recipes database
def get_food_db_connection():
    conn = sqlite3.connect(FOOD_DB)
    conn.row_factory = sqlite3.Row
    return conn


# User Model
class User:
    @staticmethod
    def create_user(username, password):
        conn = get_user_db_connection()
        cursor = conn.cursor()

        # Hash the password with bcrypt
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        # Insert into users table
        cursor.execute("INSERT INTO users (username, hashed_password) VALUES (?, ?)", (username, hashed_password))
        conn.commit()
        conn.close()

    @staticmethod
    def get_user_by_username(username):
        conn = get_user_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()
        return user


# User registration route
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data['username']
    password = data['password']

    # Check if the user already exists
    user = User.get_user_by_username(username)
    if user:
        return jsonify({"message": "Username already taken"}), 400

    # Create the user
    User.create_user(username, password)
    return jsonify({"message": "User registered successfully"}), 201


# User login route
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data['username']
    password = data['password']

    # Fetch user by username
    user = User.get_user_by_username(username)
    if not user or not bcrypt.checkpw(password.encode('utf-8'), user['hashed_password']):
        return jsonify({"message": "Invalid credentials"}), 401

    return jsonify({"message": "Login successful"}), 200


# Route to get recipes from food.db
@app.route('/recipes', methods=['GET'])
def get_recipes():
    conn = get_food_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM recipes LIMIT 10")
    recipes = cursor.fetchall()
    conn.close()

    if not recipes:
        return jsonify({"message": "No recipes found"}), 404

    recipes_list = [dict(row) for row in recipes]
    return jsonify(recipes_list)


if __name__ == '__main__':
    app.run(debug=True, port=5000)
