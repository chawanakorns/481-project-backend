import re

from flask import Blueprint, request, jsonify
import random
import logging
from utils.utils import get_food_db_connection, clean_image_url, PREPROCESSED_RECIPES

recommendations_bp = Blueprint('recommendations', __name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@recommendations_bp.route('/recommendations', methods=['GET'])
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