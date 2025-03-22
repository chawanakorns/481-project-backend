import logging
import random
import re
import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS
import bcrypt
import os
import pickle
from collections import Counter
from Levenshtein import distance as levenshtein_distance

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

# Load precomputed frequency files
print("Loading precomputed recipe word frequencies...")
with open(WORD_FREQ_FILE, 'rb') as f:
    word_freq = pickle.load(f)

print("Loading precomputed recipe bigram frequencies...")
with open(BIGRAM_FREQ_FILE, 'rb') as f:
    bigram_freq = pickle.load(f)

total_words = sum(word_freq.values())
total_bigrams = sum(bigram_freq.values())

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

# Spell Correction Functions
def generate_candidates(misspelled_word, max_distance=2):
    candidates = []
    misspelled_word = misspelled_word.lower()
    for word in word_freq.keys():
        dist = levenshtein_distance(misspelled_word, word)
        if dist <= max_distance:
            candidates.append((word, dist))
    return candidates

def generate_bigram_candidates(misspelled_bigram, max_distance=3):
    candidates = []
    misspelled_bigram = misspelled_bigram.lower()
    for bigram in bigram_freq.keys():
        dist = levenshtein_distance(misspelled_bigram, bigram)
        if dist <= max_distance:
            candidates.append((bigram, dist))
    return candidates

def calculate_p_w(word):
    # Probability of word in corpus, with a small default for unseen words
    return word_freq.get(word, 1) / total_words

def calculate_p_bigram(bigram):
    # Probability of bigram in corpus, with a small default for unseen bigrams
    return bigram_freq.get(bigram, 1) / total_bigrams

def calculate_p_x_given_w(misspelled, candidate, edit_dist):
    # Probability of misspelling given the candidate word/bigram
    if misspelled == candidate:
        return 1.0
    elif edit_dist == 1:
        return 0.8
    elif edit_dist == 2:
        return 0.2
    elif edit_dist == 3:
        return 0.05  # Added for bigram support
    return 0.0

def generate_bigrams(words):
    return [' '.join(words[i:i+2]) for i in range(len(words) - 1)]

def correct_spelling(query):
    query = query.lower().strip()
    words = query.split()

    if len(words) == 1:
        # Single-word correction
        if query in word_freq:
            return query, []  # No correction needed
        candidates = generate_candidates(query, max_distance=2)
        if not candidates:
            return query, []
        candidate_scores = []
        for cand, dist in candidates:
            p_w = calculate_p_w(cand)
            p_x_given_w = calculate_p_x_given_w(query, cand, dist)
            score = p_x_given_w * p_w
            candidate_scores.append((cand, score, dist))
        candidate_scores.sort(key=lambda x: (-x[1], x[2]))
        top_candidates = [cand[0] for cand in candidate_scores[:5]]
        corrected_query = top_candidates[0] if top_candidates else query
        suggestions = top_candidates if corrected_query != query else []
        return corrected_query, suggestions

    # Multi-word correction with bigrams
    corrected_words = words.copy()
    bigrams = generate_bigrams(words)

    # Step 1: Correct individual words
    for i, word in enumerate(words):
        if word not in word_freq:
            candidates = generate_candidates(word, max_distance=2)
            if candidates:
                candidate_scores = [
                    (cand, calculate_p_x_given_w(word, cand, dist) * calculate_p_w(cand), dist)
                    for cand, dist in candidates
                ]
                candidate_scores.sort(key=lambda x: (-x[1], x[2]))
                corrected_words[i] = candidate_scores[0][0] if candidate_scores else word

    # Step 2: Correct bigrams
    corrected_bigrams = generate_bigrams(corrected_words)
    for i, bigram in enumerate(bigrams):
        if bigram not in bigram_freq:
            bigram_candidates = generate_bigram_candidates(bigram, max_distance=3)
            if bigram_candidates:
                bigram_scores = [
                    (cand, calculate_p_x_given_w(bigram, cand, dist) * calculate_p_bigram(cand), dist)
                    for cand, dist in bigram_candidates
                ]
                bigram_scores.sort(key=lambda x: (-x[1], x[2]))
                if bigram_scores:
                    corrected_bigram = bigram_scores[0][0]
                    corrected_words[i:i+2] = corrected_bigram.split()

    corrected_query = ' '.join(corrected_words)
    # Generate suggestions (top 5 corrected queries)
    suggestions = []
    if corrected_query != query:
        suggestions.append(corrected_query)
    # Add more suggestions if needed (e.g., from top bigram candidates), limited implementation here for simplicity

    return corrected_query, suggestions

def search_recipes(query, recipes_list):
    filtered_recipes = []
    query_terms = query.lower().strip().split()
    for recipe in recipes_list:
        name = recipe.get('Name', '').lower()
        desc = recipe.get('Description', '').lower() if recipe.get('Description') else ''
        keywords_list = [
            kw.strip('"').lower() for kw in recipe.get('Keywords', [])
            if kw and not re.match(r'^\d+$', kw.strip('"'))
        ]
        ingredients_list = [
            ing.strip('"').lower() for ing in recipe.get('RecipeIngredientParts', [])
            if ing and not re.match(r'^\d+$', ing.strip('"'))
        ]
        instructions = ' '.join(recipe.get('RecipeInstructions', [])).lower()
        recipe_text = ' '.join([name, desc, ' '.join(keywords_list), ' '.join(ingredients_list), instructions])
        # Match all query terms in any field
        if all(term in recipe_text for term in query_terms):
            filtered_recipes.append(recipe)
    return filtered_recipes

@app.route('/recipes', methods=['GET'])
def get_recipes():
    limit = request.args.get('limit', default=20, type=int)
    page = request.args.get('page', default=1, type=int)
    search_query = request.args.get('search', default='', type=str).strip()
    recipes_list = list(PREPROCESSED_RECIPES.values())

    start = (page - 1) * limit
    end = start + limit

    if search_query:
        original_query = search_query
        corrected_query, suggestions = correct_spelling(search_query)
        filtered_recipes = search_recipes(corrected_query, recipes_list)

        total_results = len(filtered_recipes)
        paginated_recipes = filtered_recipes[start:end]
        total_pages = (total_results + limit - 1) // limit

        response = {
            'recipes': [
                {**recipe, 'image_url': clean_image_url(recipe.get('image_url', ''))}
                for recipe in paginated_recipes
            ],
            'original_query': original_query,
            'corrected_query': corrected_query if corrected_query != original_query else None,
            'suggestions': suggestions,
            'total_results': total_results,
            'total_pages': total_pages,
            'current_page': page
        }
    else:
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

# Folder and Bookmark Endpoints (unchanged)
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/recommendations', methods=['GET'])
def get_recommendations():
    user_id = request.args.get('user_id', type=int)
    folder_id = request.args.get('folder_id', type=int)
    limit = request.args.get('limit', default=10, type=int)

    if not user_id:
        return jsonify({"message": "User ID is required"}), 400

    conn = get_food_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT RecipeId FROM bookmarks WHERE UserId = ?", (user_id,))
        bookmarked_recipe_ids = set(row['RecipeId'] for row in cursor.fetchall())
        logger.info(f"User {user_id} has {len(bookmarked_recipe_ids)} bookmarked recipes")

        folder_keywords = set()
        avg_rating = 0
        if folder_id:
            cursor.execute("""
                SELECT b.RecipeId, b.Rating
                FROM bookmarks b
                WHERE b.FolderId = ? AND b.UserId = ?
            """, (folder_id, user_id))
            bookmarks = cursor.fetchall()
            if not bookmarks:
                logger.warning(f"Folder {folder_id} for user {user_id} is empty or not found")
                return jsonify({"message": "Folder is empty or not found"}), 404
        else:
            cursor.execute("SELECT RecipeId, Rating FROM bookmarks WHERE UserId = ?", (user_id,))
            bookmarks = cursor.fetchall()
            if not bookmarks:
                logger.info(f"User {user_id} has no bookmarks; returning random recipes")

        if bookmarks:
            ratings = [b['Rating'] for b in bookmarks]
            avg_rating = sum(ratings) / len(ratings) if ratings else 0
            for bookmark in bookmarks:
                recipe = PREPROCESSED_RECIPES.get(bookmark['RecipeId'], {})
                keywords = [
                    kw.strip('"').lower() for kw in recipe.get('Keywords', [])
                    if kw and not re.match(r'^\d+$', kw.strip('"'))
                ]
                folder_keywords.update(keywords)
            logger.info(
                f"{'Folder ' + str(folder_id) if folder_id else 'All bookmarks'}: {len(folder_keywords)} keywords, avg rating {avg_rating}")

        all_recipes = [
            {**r, 'image_url': clean_image_url(r.get('image_url', ''))}
            for r in PREPROCESSED_RECIPES.values()
            if r['RecipeId'] not in bookmarked_recipe_ids
        ]
        logger.info(f"Found {len(all_recipes)} unbookmarked recipes")

        num_to_recommend = min(limit, len(all_recipes))
        if num_to_recommend == 0:
            return jsonify({
                'recommendations': [],
                'total_recommendations': 0,
                'message': 'All available recipes are bookmarked.'
            })

        if folder_keywords:
            scored_recipes = [
                (recipe, calculate_recipe_score(recipe, folder_keywords, avg_rating))
                for recipe in all_recipes
            ]
            scored_recipes.sort(key=lambda x: x[1], reverse=True)
            recommended_recipes = [recipe for recipe, _ in scored_recipes[:num_to_recommend]]
            random.shuffle(recommended_recipes)
            logger.info(f"Generated {len(recommended_recipes)} ranked and shuffled suggestions")
        else:
            recommended_recipes = random.sample(all_recipes, num_to_recommend)
            logger.info(f"Generated {len(recommended_recipes)} random suggestions")

        response = {
            'recommendations': recommended_recipes,
            'total_recommendations': len(recommended_recipes),
            'message': 'Suggestions generated based on folder contents.' if folder_id else 'Suggestions based on all bookmarks.' if bookmarks else ''
        }
        return jsonify(response)

    except Exception as e:
        logger.error(f"Error in /recommendations: {str(e)}")
        return jsonify({"message": f"Server error: {str(e)}"}), 500
    finally:
        conn.close()

def calculate_recipe_score(recipe, folder_keywords, avg_folder_rating):
    recipe_keywords = set(
        kw.strip('"').lower() for kw in recipe.get('Keywords', [])
        if kw and not re.match(r'^\d+$', kw.strip('"'))
    )
    overlap = len(recipe_keywords.intersection(folder_keywords))
    rating = recipe.get('AggregatedRating', 0) or 0
    rating_diff = min(5, abs(avg_folder_rating - rating))
    score = (overlap * 2) + (5 - rating_diff)
    return score

if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=False)