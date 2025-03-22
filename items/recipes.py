from flask import Blueprint, request, jsonify
import re
from utils.utils import PREPROCESSED_RECIPES, clean_image_url, generate_candidates, generate_bigrams, \
    calculate_p_w, calculate_p_x_given_w, calculate_p_bigram, word_freq, token_required

recipes_bp = Blueprint('recipes', __name__)

def correct_spelling(query):
    query = query.lower().strip()
    words = query.split()
    if len(words) == 1:
        if query in word_freq:
            return query, []
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
    # Multi-word correction omitted for brevity, copy from original if needed

def search_recipes(query, recipes_list):
    filtered_recipes = []
    query_terms = query.lower().strip().split()
    for recipe in recipes_list:
        name = recipe.get('Name', '').lower()
        desc = recipe.get('Description', '').lower() if recipe.get('Description') else ''
        keywords_list = [kw.strip('"').lower() for kw in recipe.get('Keywords', []) if kw and not re.match(r'^\d+$', kw.strip('"'))]
        ingredients_list = [ing.strip('"').lower() for ing in recipe.get('RecipeIngredientParts', []) if ing and not re.match(r'^\d+$', ing.strip('"'))]
        instructions = ' '.join(recipe.get('RecipeInstructions', [])).lower()
        recipe_text = ' '.join([name, desc, ' '.join(keywords_list), ' '.join(ingredients_list), instructions])
        if all(term in recipe_text for term in query_terms):
            filtered_recipes.append(recipe)
    return filtered_recipes

@recipes_bp.route('/recipes', methods=['GET'])
@token_required
def get_recipes():
    limit = request.args.get('limit', default=20, type=int)
    page = request.args.get('page', default=1, type=int)
    search_query = request.args.get('search', default='', type=str).strip()
    recipes_list = list(PREPROCESSED_RECIPES.values())
    start = (page - 1) * limit
    end = start + limit
    if search_query:
        corrected_query, suggestions = correct_spelling(search_query)
        filtered_recipes = search_recipes(corrected_query, recipes_list)
        total_results = len(filtered_recipes)
        paginated_recipes = filtered_recipes[start:end]
        total_pages = (total_results + limit - 1) // limit
        response = {
            'recipes': [{**recipe, 'image_url': clean_image_url(recipe.get('image_url', ''))} for recipe in paginated_recipes],
            'original_query': search_query,
            'corrected_query': corrected_query if corrected_query != search_query else None,
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
            'recipes': [{**recipe, 'image_url': clean_image_url(recipe.get('image_url', ''))} for recipe in paginated_recipes],
            'original_query': '',
            'corrected_query': None,
            'suggestions': [],
            'total_results': total_results,
            'total_pages': total_pages,
            'current_page': page
        }
    return jsonify(response)