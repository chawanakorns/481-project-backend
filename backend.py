import re
import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS
import bcrypt
import os
import pickle
from Levenshtein import distance as levenshtein_distance
from collections import Counter
import nltk
from nltk import bigrams, word_tokenize

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.abspath("../481-project-database")
USERS_DB = os.path.join(BASE_DIR, 'users.db')
FOOD_DB = os.path.join(BASE_DIR, 'food.db')
PREPROCESSED_RECIPES_FILE = "../481-project-database/preprocessed_recipes.pkl"
WORD_FREQ_FILE = "../481-project-database/word_freq.pkl"
BIGRAM_FREQ_FILE = "../481-project-database/bigram_freq.pkl"

# Load preprocessed recipes
with open(PREPROCESSED_RECIPES_FILE, "rb") as f:
    PREPROCESSED_RECIPES = pickle.load(f)

# Check if precomputed frequency files exist; if not, generate and save them
if not os.path.exists(WORD_FREQ_FILE):
    print("Building recipe-specific corpus...")
    corpus_words = []
    for recipe in PREPROCESSED_RECIPES.values():
        name = recipe.get('Name', '').lower()
        keywords = ' '.join(recipe.get('Keywords', [])) if recipe.get('Keywords') else ''
        corpus_words.extend(word_tokenize(name + ' ' + keywords))
    word_freq = Counter(corpus_words)
    with open(WORD_FREQ_FILE, 'wb') as f:
        pickle.dump(word_freq, f)
else:
    print("Loading precomputed recipe word frequencies...")
    with open(WORD_FREQ_FILE, 'rb') as f:
        word_freq = pickle.load(f)

total_words = sum(word_freq.values())

def clean_image_url(url):
    if url and isinstance(url, str):
        return url.strip('"')
    return url


def get_user_db_connection():
    conn = sqlite3.connect(USERS_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def get_food_db_connection():
    conn = sqlite3.connect(FOOD_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


class User:
    @staticmethod
    def create_user(username, password):
        conn = get_user_db_connection()
        cursor = conn.cursor()
        try:
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            cursor.execute("INSERT INTO users (username, hashed_password) VALUES (?, ?)", (username, hashed_password))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_user_by_username(username):
        conn = get_user_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            return user
        finally:
            conn.close()


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
    return jsonify({"message": "Login successful", "user_id": user['id']}), 200


def parse_image_urls(image_string):
    pattern = r'"(https?://[^"]+)"'
    matches = re.findall(pattern, image_string)
    return matches if matches else []


def clean_image_url(url):
    if url and isinstance(url, str):
        return url.strip('"')
    return url


# Folder Management Endpoints
@app.route('/folders', methods=['POST'])
def create_folder():
    data = request.get_json()
    user_id = data.get('user_id')
    name = data.get('name')
    if not user_id or not name or not name.strip():
        return jsonify({"message": "User ID and folder name are required"}), 400
    conn = get_food_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO folders (UserId, Name) VALUES (?, ?)", (user_id, name.strip()))
        folder_id = cursor.lastrowid
        conn.commit()
        return jsonify({"message": "Folder created", "folder_id": folder_id}), 201
    except sqlite3.OperationalError as e:
        return jsonify({"message": f"Database error: {str(e)}"}), 500
    finally:
        conn.close()


@app.route('/folders', methods=['GET'])
def get_folders():
    user_id = request.args.get('user_id', type=int)
    conn = get_food_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM folders WHERE UserId = ?", (user_id,))
        folders = cursor.fetchall()
        return jsonify([dict(folder) for folder in folders])
    finally:
        conn.close()


@app.route('/folders/<int:folder_id>', methods=['PUT'])
def update_folder(folder_id):
    data = request.get_json()
    name = data.get('name')
    if not name or not name.strip():
        return jsonify({"message": "Folder name is required"}), 400
    conn = get_food_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE folders SET Name = ? WHERE FolderId = ?", (name.strip(), folder_id))
        if cursor.rowcount == 0:
            return jsonify({"message": "Folder not found"}), 404
        conn.commit()
        return jsonify({"message": "Folder updated"}), 200
    finally:
        conn.close()


@app.route('/folders/<int:folder_id>', methods=['DELETE'])
def delete_folder(folder_id):
    conn = get_food_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM bookmarks WHERE FolderId = ?", (folder_id,))
        cursor.execute("DELETE FROM folders WHERE FolderId = ?", (folder_id,))
        if cursor.rowcount == 0:
            return jsonify({"message": "Folder not found"}), 404
        conn.commit()
        return jsonify({"message": "Folder and its bookmarks deleted"}), 200
    finally:
        conn.close()


# Bookmark Endpoints
@app.route('/bookmarks', methods=['POST'])
def add_bookmark():
    data = request.get_json()
    user_id = data.get('user_id')
    folder_id = data.get('folder_id')
    recipe_id = data.get('recipe_id')
    rating = data.get('rating')
    if not all([user_id, folder_id, recipe_id, rating]) or not (1 <= rating <= 5):
        return jsonify({"message": "All fields are required, and rating must be 1-5"}), 400
    conn = get_food_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM folders WHERE FolderId = ? AND UserId = ?", (folder_id, user_id))
        if not cursor.fetchone():
            return jsonify({"message": "Folder not found or not owned by user"}), 404
        cursor.execute("INSERT INTO bookmarks (UserId, FolderId, RecipeId, Rating) VALUES (?, ?, ?, ?)",
                       (user_id, folder_id, recipe_id, rating))
        conn.commit()
        return jsonify({"message": "Bookmark added"}), 201
    finally:
        conn.close()


@app.route('/bookmarks/<int:folder_id>', methods=['GET'])
def get_bookmarks(folder_id):
    conn = get_food_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT b.*, r.Name, r.Images
            FROM bookmarks b
            JOIN recipes r ON b.RecipeId = r.RecipeId
            WHERE b.FolderId = ?
        """, (folder_id,))
        bookmarks = cursor.fetchall()
        bookmarks_list = []
        for bookmark in bookmarks:
            bookmark_dict = dict(bookmark)
            recipe = PREPROCESSED_RECIPES.get(bookmark_dict['RecipeId'], {})
            bookmark_dict['image_url'] = clean_image_url(recipe.get('image_url', ''))
            bookmarks_list.append(bookmark_dict)
        return jsonify(bookmarks_list)
    finally:
        conn.close()


@app.route('/bookmarks/all', methods=['GET'])
def get_all_bookmarks():
    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return jsonify({"message": "User ID is required"}), 400
    conn = get_food_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT f.FolderId, f.Name, AVG(b.Rating) as AvgRating
            FROM folders f
            LEFT JOIN bookmarks b ON f.FolderId = b.FolderId
            WHERE f.UserId = ?
            GROUP BY f.FolderId, f.Name
            ORDER BY AvgRating DESC
        """, (user_id,))
        folders = cursor.fetchall()

        cursor.execute("""
            SELECT b.*, r.Name, r.Images
            FROM bookmarks b
            JOIN recipes r ON b.RecipeId = r.RecipeId
            WHERE b.UserId = ?
        """, (user_id,))
        bookmarks = cursor.fetchall()

        bookmarks_by_folder = {}
        for bookmark in bookmarks:
            bookmark_dict = dict(bookmark)
            recipe = PREPROCESSED_RECIPES.get(bookmark_dict['RecipeId'], {})
            bookmark_dict['image_url'] = clean_image_url(recipe.get('image_url', ''))
            folder_id = bookmark_dict['FolderId']
            if folder_id not in bookmarks_by_folder:
                bookmarks_by_folder[folder_id] = []
            bookmarks_by_folder[folder_id].append(bookmark_dict)

        result = {
            'folders': [dict(folder) for folder in folders],
            'bookmarks': bookmarks_by_folder
        }
        return jsonify(result)
    finally:
        conn.close()


@app.route('/bookmarks/<int:bookmark_id>', methods=['PUT'])
def update_bookmark(bookmark_id):
    data = request.get_json()
    folder_id = data.get('folder_id')
    if not folder_id:
        return jsonify({"message": "Folder ID is required"}), 400
    conn = get_food_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE bookmarks SET FolderId = ? WHERE BookmarkId = ?", (folder_id, bookmark_id))
        if cursor.rowcount == 0:
            return jsonify({"message": "Bookmark not found"}), 404
        conn.commit()
        return jsonify({"message": "Bookmark moved"}), 200
    finally:
        conn.close()


@app.route('/bookmarks/<int:bookmark_id>/rating', methods=['PUT'])
def update_bookmark_rating(bookmark_id):
    data = request.get_json()
    rating = data.get('rating')
    if rating is None or not (1 <= rating <= 5):
        return jsonify({"message": "Rating must be between 1 and 5"}), 400
    conn = get_food_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE bookmarks SET Rating = ? WHERE BookmarkId = ?", (rating, bookmark_id))
        if cursor.rowcount == 0:
            return jsonify({"message": "Bookmark not found"}), 404
        conn.commit()
        return jsonify({"message": "Rating updated"}), 200
    finally:
        conn.close()


@app.route('/bookmarks/<int:bookmark_id>', methods=['DELETE'])
def delete_bookmark(bookmark_id):
    conn = get_food_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM bookmarks WHERE BookmarkId = ?", (bookmark_id,))
        if cursor.rowcount == 0:
            return jsonify({"message": "Bookmark not found"}), 404
        conn.commit()
        return jsonify({"message": "Bookmark deleted"}), 200
    finally:
        conn.close()


# Spell Correction Functions
def generate_candidates(misspelled_word, max_distance=2):
    candidates = []
    misspelled_word = misspelled_word.lower()
    for word in word_freq.keys():
        dist = levenshtein_distance(misspelled_word, word)
        if dist <= max_distance:
            candidates.append((word, dist))
    return candidates


def calculate_p_w(word):
    return word_freq.get(word, 1) / total_words


def calculate_p_x_given_w(misspelled, candidate, edit_dist):
    if edit_dist == 1:
        return 0.8
    elif edit_dist == 2:
        return 0.2
    return 1.0 if misspelled == candidate else 0.0


def search_recipes(query, recipes_list):
    filtered_recipes = []
    for recipe in recipes_list:
        name = recipe.get('Name', '').lower()
        desc = recipe.get('Description', '').lower()
        keywords = ' '.join(recipe.get('Keywords', [])) if recipe.get('Keywords') else ''
        if query in name or query in desc or query in keywords:
            filtered_recipes.append(recipe)
    return filtered_recipes


@app.route('/recipes', methods=['GET'])
def get_recipes():
    limit = request.args.get('limit', default=20, type=int)  # Default to 20 items per page
    page = request.args.get('page', default=1, type=int)  # Default to page 1
    search_query = request.args.get('search', default='', type=str).strip().lower()
    recipes_list = list(PREPROCESSED_RECIPES.values())

    start = (page - 1) * limit
    end = start + limit

    if search_query:
        # Always search with the original query first
        filtered_recipes = search_recipes(search_query, recipes_list)
        corrected_query = search_query
        suggestions = []

        # Generate candidates for correction
        candidates = generate_candidates(search_query, max_distance=2)

        if candidates:
            candidate_scores = []
            for cand, dist in candidates:
                p_w = calculate_p_w(cand)
                p_x_given_w = calculate_p_x_given_w(search_query, cand, dist)
                score = p_x_given_w * p_w
                candidate_scores.append((cand, score, dist))

            candidate_scores.sort(key=lambda x: x[1], reverse=True)
            top_candidates = [cand[0] for cand in candidate_scores[:5]]
            potential_corrected_query = top_candidates[0] if candidate_scores else search_query

            corrected_results = search_recipes(potential_corrected_query, recipes_list)
            if corrected_results:
                filtered_recipes = corrected_results
                corrected_query = potential_corrected_query
                suggestions = top_candidates if corrected_query != search_query else []

        # Apply pagination to filtered results
        total_results = len(filtered_recipes)
        paginated_recipes = filtered_recipes[start:end]
        total_pages = (total_results + limit - 1) // limit  # Ceiling division

        response = {
            'recipes': [
                {**recipe, 'image_url': clean_image_url(recipe.get('image_url', ''))}
                for recipe in paginated_recipes
            ],
            'original_query': search_query,
            'corrected_query': corrected_query,
            'suggestions': suggestions,
            'total_results': total_results,
            'total_pages': total_pages,
            'current_page': page
        }
    else:
        # No search query, paginate all recipes
        total_results = len(recipes_list)
        paginated_recipes = recipes_list[start:end]
        total_pages = (total_results + limit - 1) // limit

        response = {
            'recipes': [
                {**recipe, 'image_url': clean_image_url(recipe.get('image_url', ''))}
                for recipe in paginated_recipes
            ],
            'original_query': '',
            'corrected_query': None,
            'suggestions': [],
            'total_results': total_results,
            'total_pages': total_pages,
            'current_page': page
        }

    print(f"Returning {len(response['recipes'])} recipes from /recipes, page {page} of {response['total_pages']}")
    return jsonify(response)


@app.route('/recipes/<int:recipe_id>', methods=['GET'])
def get_recipe(recipe_id):
    print(f"Request received for /recipes/{recipe_id}")
    recipe = PREPROCESSED_RECIPES.get(recipe_id)
    if not recipe:
        print(f"No recipe found for ID {recipe_id}")
        return jsonify({"message": "Recipe not found"}), 404
    recipe = {**recipe, 'image_url': clean_image_url(recipe.get('image_url', ''))}
    print(f"Returning recipe: {recipe['Name']}")
    return jsonify(recipe)


if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=False)