# items/recommendations.py
import re
import random
import logging
import numpy as np
from flask import Blueprint, request, jsonify
from utils.utils import get_food_db_connection, clean_image_url, PREPROCESSED_RECIPES, ranking_model

recommendations_bp = Blueprint('recommendations', __name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def extract_features(user_id, folder_id, recipe, user_keywords, avg_user_rating, dominant_category):
    # Extract keywords from the recipe
    recipe_keywords = set(
        kw.strip('"').lower() for kw in recipe.get('Keywords', [])
        if kw and not re.match(r'^\d+$', kw.strip('"'))
    )

    # Feature 1: Keyword overlap
    keyword_overlap = len(recipe_keywords.intersection(user_keywords))

    # Feature 2: Rating similarity
    recipe_rating = recipe.get('AggregatedRating', 0) or 0
    rating_diff = abs(avg_user_rating - recipe_rating)

    # Feature 3: Category match (increased weight for dominant category)
    category_match = 2 if recipe.get(
        'RecipeCategory') == dominant_category else 0  # Higher weight for matching category

    # Feature 4: Recipe popularity (ReviewCount)
    review_count = recipe.get('ReviewCount', 0) or 0

    # Feature 5: Cooking time (TotalTime in minutes)
    total_time = recipe.get('TotalTime', 0) or 0
    if isinstance(total_time, str):
        total_time = 0

    return [keyword_overlap, rating_diff, category_match, review_count, total_time]


def calculate_fallback_score(recipe, user_keywords, avg_user_rating, dominant_category):
    # Fallback scoring function with emphasis on category matching
    recipe_keywords = set(
        kw.strip('"').lower() for kw in recipe.get('Keywords', [])
        if kw and not re.match(r'^\d+$', kw.strip('"'))
    )
    keyword_overlap = len(recipe_keywords.intersection(user_keywords))
    recipe_rating = recipe.get('AggregatedRating', 0) or 0
    rating_diff = min(5, abs(avg_user_rating - recipe_rating))
    category_match = 5 if recipe.get(
        'RecipeCategory') == dominant_category else 0  # Higher weight for matching category
    review_count = recipe.get('ReviewCount', 0) or 0
    score = (keyword_overlap * 2) + (5 - rating_diff) + category_match + (review_count * 0.1)
    return score


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
        # Get bookmarked recipe IDs for the user
        cursor.execute("SELECT RecipeId FROM bookmarks WHERE UserId = ?", (user_id,))
        bookmarked_recipe_ids = set(row['RecipeId'] for row in cursor.fetchall())
        logger.info(f"User {user_id} has {len(bookmarked_recipe_ids)} bookmarked recipes")

        # Get all folders for the user (for UC-007 summary)
        cursor.execute("SELECT FolderId FROM folders WHERE UserId = ?", (user_id,))
        all_folder_ids = [row['FolderId'] for row in cursor.fetchall()]

        # Initialize user keywords and average rating
        user_keywords = set()
        avg_rating = 0
        all_bookmarks = []

        # UC-007: Summary from all folders
        folder_summaries = []
        for fid in all_folder_ids:
            cursor.execute("""
                SELECT b.RecipeId, b.Rating
                FROM bookmarks b
                WHERE b.FolderId = ? AND b.UserId = ?
            """, (fid, user_id))
            bookmarks = cursor.fetchall()
            if bookmarks:
                folder_ratings = [b['Rating'] for b in bookmarks]
                folder_avg_rating = sum(folder_ratings) / len(folder_ratings)
                folder_keywords = set()
                for bookmark in bookmarks:
                    recipe = PREPROCESSED_RECIPES.get(bookmark['RecipeId'], {})
                    keywords = [
                        kw.strip('"').lower() for kw in recipe.get('Keywords', [])
                        if kw and not re.match(r'^\d+$', kw.strip('"'))
                    ]
                    folder_keywords.update(keywords)
                folder_summaries.append({
                    'folder_id': fid,
                    'avg_rating': folder_avg_rating,
                    'num_bookmarks': len(bookmarks),
                    'keywords': list(folder_keywords)[:5]  # Top 5 keywords
                })
                all_bookmarks.extend(bookmarks)
            else:
                folder_summaries.append({
                    'folder_id': fid,
                    'avg_rating': 0,
                    'num_bookmarks': 0,
                    'keywords': []
                })

        # Get user keywords, average rating, and dominant category from specified folder or all bookmarks
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
            bookmarks = all_bookmarks if all_bookmarks else cursor.fetchall()
            if not bookmarks:
                logger.info(f"User {user_id} has no bookmarks; returning random recipes")

        # Determine the dominant category of bookmarked items
        dominant_category = None
        if bookmarks:
            ratings = [b['Rating'] for b in bookmarks]
            avg_rating = sum(ratings) / len(ratings) if ratings else 0
            bookmarked_recipe_ids_list = [b['RecipeId'] for b in bookmarks]
            categories = []
            for recipe_id in bookmarked_recipe_ids_list:
                recipe = PREPROCESSED_RECIPES.get(recipe_id, {})
                category = recipe.get('RecipeCategory')
                if category:
                    categories.append(category)
                keywords = [
                    kw.strip('"').lower() for kw in recipe.get('Keywords', [])
                    if kw and not re.match(r'^\d+$', kw.strip('"'))
                ]
                user_keywords.update(keywords)
            # Find the most common category among bookmarked items
            dominant_category = max(set(categories), key=categories.count, default=None) if categories else None
            logger.info(
                f"{'Folder ' + str(folder_id) if folder_id else 'All bookmarks'}: {len(user_keywords)} keywords, avg rating {avg_rating}, dominant category {dominant_category}")

        # Get all unbookmarked recipes
        all_recipes = [
            {**r, 'image_url': clean_image_url(r.get('image_url', ''))}
            for r in PREPROCESSED_RECIPES.values()
            if r['RecipeId'] not in bookmarked_recipe_ids
        ]
        logger.info(f"Found {len(all_recipes)} unbookmarked recipes")

        # UC-007: Completely random dishes (5 recipes, biased towards dominant category)
        num_random = min(5, len(all_recipes))
        if dominant_category:
            # Split random selection: 70% from dominant category, 30% completely random
            dominant_category_recipes = [
                r for r in all_recipes if r.get('RecipeCategory') == dominant_category
            ]
            other_recipes = [
                r for r in all_recipes if r.get('RecipeCategory') != dominant_category
            ]
            num_dominant = int(num_random * 0.7)  # 70% from dominant category
            num_other = num_random - num_dominant  # 30% from other categories
            completely_random = []
            if dominant_category_recipes and num_dominant > 0:
                completely_random.extend(random.sample(
                    dominant_category_recipes,
                    min(num_dominant, len(dominant_category_recipes))
                ))
            if other_recipes and num_other > 0:
                completely_random.extend(random.sample(
                    other_recipes,
                    min(num_other, len(other_recipes))
                ))
            # If we don't have enough recipes, fill the rest randomly
            if len(completely_random) < num_random:
                remaining_recipes = [r for r in all_recipes if r not in completely_random]
                completely_random.extend(random.sample(
                    remaining_recipes,
                    min(num_random - len(completely_random), len(remaining_recipes))
                ))
        else:
            completely_random = random.sample(all_recipes, num_random) if num_random > 0 else []

        # UC-007: Random selection from the dominant category (5 recipes)
        num_category = min(5, len(all_recipes))
        category_recipes = [
            r for r in all_recipes
            if dominant_category and r.get('RecipeCategory') == dominant_category
        ]
        random_from_category = random.sample(category_recipes, num_category) if len(
            category_recipes) >= num_category else category_recipes

        # UC-008: Ranked recommendations
        num_ranked = max(0, limit - len(completely_random) - len(random_from_category))
        ranked_recommendations = []
        if num_ranked > 0 and all_recipes:
            if ranking_model is not None:
                # Use LightGBM model if available
                try:
                    features = []
                    recipe_list = []
                    for recipe in all_recipes:
                        feat = extract_features(user_id, folder_id, recipe, user_keywords, avg_rating,
                                                dominant_category)
                        features.append(feat)
                        recipe_list.append(recipe)

                    # Predict scores using LightGBM
                    features = np.array(features)
                    scores = ranking_model.predict(features)

                    # Sort recipes by score
                    scored_recipes = list(zip(recipe_list, scores))
                    scored_recipes.sort(key=lambda x: x[1], reverse=True)
                    ranked_recommendations = [recipe for recipe, _ in scored_recipes[:num_ranked]]
                    logger.info(f"Generated {len(ranked_recommendations)} ranked recommendations using LightGBM")
                except Exception as e:
                    logger.error(f"Error using LightGBM model: {str(e)}. Falling back to simple scoring.")
                    # Fallback to simple scoring if LightGBM fails
                    scored_recipes = [
                        (recipe, calculate_fallback_score(recipe, user_keywords, avg_rating, dominant_category))
                        for recipe in all_recipes
                    ]
                    scored_recipes.sort(key=lambda x: x[1], reverse=True)
                    ranked_recommendations = [recipe for recipe, _ in scored_recipes[:num_ranked]]
                    logger.info(
                        f"Generated {len(ranked_recommendations)} ranked recommendations using fallback scoring")
            else:
                # Fallback to simple scoring if model is not loaded
                logger.warning("Ranking model not loaded. Falling back to simple scoring.")
                scored_recipes = [
                    (recipe, calculate_fallback_score(recipe, user_keywords, avg_rating, dominant_category))
                    for recipe in all_recipes
                ]
                scored_recipes.sort(key=lambda x: x[1], reverse=True)
                ranked_recommendations = [recipe for recipe, _ in scored_recipes[:num_ranked]]
                logger.info(f"Generated {len(ranked_recommendations)} ranked recommendations using fallback scoring")

        # Combine all recommendations
        recommended_recipes = ranked_recommendations + random_from_category + completely_random
        random.shuffle(recommended_recipes)  # Shuffle to mix the different types

        response = {
            'recommendations': recommended_recipes[:limit],
            'total_recommendations': len(recommended_recipes),
            'folder_summaries': folder_summaries,  # UC-007: Summary from all folders
            'message': 'Suggestions generated based on folder contents.' if folder_id else 'Suggestions based on all bookmarks.' if bookmarks else 'Random suggestions due to lack of bookmarks.'
        }
        return jsonify(response)

    except Exception as e:
        logger.error(f"Error in /recommendations: {str(e)}")
        return jsonify({"message": f"Server error: {str(e)}"}), 500
    finally:
        conn.close()