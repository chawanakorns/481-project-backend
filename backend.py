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
    return jsonify({"message": "Login successful", "user_id": user['id']}), 200  # Return user_id

def parse_image_urls(image_string):
    pattern = r'"(https?://[^"]+)"'
    matches = re.findall(pattern, image_string)
    return matches if matches else []

# Folder Management Endpoints
@app.route('/folders', methods=['POST'])
def create_folder():
    data = request.get_json()
    user_id = data['user_id']
    name = data['name']
    conn = get_food_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO folders (UserId, Name) VALUES (?, ?)", (user_id, name))
    conn.commit()
    folder_id = cursor.lastrowid
    conn.close()
    return jsonify({"message": "Folder created", "folder_id": folder_id}), 201

@app.route('/folders', methods=['GET'])
def get_folders():
    user_id = request.args.get('user_id', type=int)
    conn = get_food_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM folders WHERE UserId = ?", (user_id,))
    folders = cursor.fetchall()
    conn.close()
    return jsonify([dict(folder) for folder in folders])

@app.route('/folders/<int:folder_id>', methods=['PUT'])
def update_folder(folder_id):
    data = request.get_json()
    name = data['name']
    conn = get_food_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE folders SET Name = ? WHERE FolderId = ?", (name, folder_id))
    conn.commit()
    conn.close()
    return jsonify({"message": "Folder updated"}), 200

@app.route('/folders/<int:folder_id>', methods=['DELETE'])
def delete_folder(folder_id):
    conn = get_food_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM folders WHERE FolderId = ?", (folder_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Folder deleted"}), 200

# Bookmark Endpoints
@app.route('/bookmarks', methods=['POST'])
def add_bookmark():
    data = request.get_json()
    user_id = data['user_id']
    folder_id = data['folder_id']
    recipe_id = data['recipe_id']
    rating = data['rating']
    conn = get_food_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO bookmarks (UserId, FolderId, RecipeId, Rating) VALUES (?, ?, ?, ?)",
                   (user_id, folder_id, recipe_id, rating))
    conn.commit()
    conn.close()
    return jsonify({"message": "Bookmark added"}), 201

@app.route('/bookmarks/<int:folder_id>', methods=['GET'])
def get_bookmarks(folder_id):
    conn = get_food_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.*, r.Name, r.image_url
        FROM bookmarks b
        JOIN recipes r ON b.RecipeId = r.RecipeId
        WHERE b.FolderId = ?
    """, (folder_id,))
    bookmarks = cursor.fetchall()
    conn.close()
    return jsonify([dict(bookmark) for bookmark in bookmarks])

@app.route('/recipes', methods=['GET'])
def get_recipes():
    limit = request.args.get('limit', default=12, type=int)
    conn = get_food_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM recipes LIMIT ?", (limit,))
    recipes = cursor.fetchall()
    conn.close()

    if not recipes:
        return jsonify({"message": "No recipes found"}), 404

    recipes_list = []
    for row in recipes:
        recipe = dict(row)
        if recipe['Images'] and recipe['Images'].startswith('c('):
            image_urls = parse_image_urls(recipe['Images'])
            recipe['image_url'] = image_urls[0] if image_urls else ''
            recipe['all_image_urls'] = image_urls
        else:
            recipe['image_url'] = recipe['Images']
            recipe['all_image_urls'] = [recipe['Images']] if recipe['Images'] else []
        recipes_list.append(recipe)

    print(f"Returning {len(recipes_list)} recipes from /recipes")
    return jsonify(recipes_list)

@app.route('/recipes/<int:recipe_id>', methods=['GET'])
def get_recipe(recipe_id):
    print(f"Request received for /recipes/{recipe_id}")
    conn = get_food_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM recipes WHERE RecipeId = ?", (recipe_id,))
    recipe = cursor.fetchone()
    conn.close()

    if not recipe:
        print(f"No recipe found for ID {recipe_id}")
        return jsonify({"message": "Recipe not found"}), 404

    recipe_dict = dict(recipe)
    if recipe_dict['Images'] and recipe_dict['Images'].startswith('c('):
        image_urls = parse_image_urls(recipe_dict['Images'])
        recipe_dict['image_url'] = image_urls[0] if image_urls else ''
        recipe_dict['all_image_urls'] = image_urls
    else:
        recipe_dict['image_url'] = recipe_dict['Images']
        recipe_dict['all_image_urls'] = [recipe_dict['Images']] if recipe_dict['Images'] else []

    print(f"Returning recipe: {recipe_dict['Name']}")
    return jsonify(recipe_dict)

if __name__ == '__main__':
    app.run(debug=True, port=5000)