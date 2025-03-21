import sqlite3
from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
import bcrypt
import os
import re

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
USERS_DB = os.path.join(BASE_DIR, 'database', 'users.db')
FOOD_DB = os.path.join(BASE_DIR, 'database', 'food.db')


def get_user_db_connection():
    conn = sqlite3.connect(USERS_DB)
    conn.row_factory = sqlite3.Row
    return conn


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
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
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


@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data['username']
    password = data['password']
    user = User.get_user_by_username(username)
    if user:
        return jsonify({"message": "Username already taken"}), 400
    User.create_user(username, password)
    return jsonify({"message": "User registered successfully"}), 201


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data['username']
    password = data['password']
    user = User.get_user_by_username(username)
    if not user or not bcrypt.checkpw(password.encode('utf-8'), user['hashed_password']):
        return jsonify({"message": "Invalid credentials"}), 401
    return jsonify({"message": "Login successful"}), 200


def parse_image_urls(image_string):
    # This regex will match URLs inside quotes
    pattern = r'"(https?://[^"]+)"'
    matches = re.findall(pattern, image_string)
    return matches if matches else []


@app.route('/recipes', methods=['GET'])
def get_recipes():
    conn = get_food_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM recipes LIMIT 10")
    recipes = cursor.fetchall()
    conn.close()

    if not recipes:
        return jsonify({"message": "No recipes found"}), 404

    recipes_list = []
    for row in recipes:
        recipe = dict(row)
        # Parse image URLs if they're in the format you showed
        if recipe['Images'] and recipe['Images'].startswith('c('):
            image_urls = parse_image_urls(recipe['Images'])
            # Use the first image URL if available, otherwise use an empty string
            recipe['image_url'] = image_urls[0] if image_urls else ''
            # Also include all image URLs in case you want to display multiple images
            recipe['all_image_urls'] = image_urls
        else:
            # If it's just a single URL
            recipe['image_url'] = recipe['Images']
            recipe['all_image_urls'] = [recipe['Images']] if recipe['Images'] else []

        recipes_list.append(recipe)

    return jsonify(recipes_list)


if __name__ == '__main__':
    app.run(debug=True, port=5000)