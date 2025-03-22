# backend.py
from flask import Flask, redirect
from flask_cors import CORS
from auth.auth import auth_bp
from items.recipes import recipes_bp
from items.folders_bookmarks import folders_bookmarks_bp
from items.recommendations import recommendations_bp

app = Flask(__name__)
CORS(app)

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(recipes_bp)
app.register_blueprint(folders_bookmarks_bp)
app.register_blueprint(recommendations_bp)

@app.route('/')
def index():
    return redirect('/login')

if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=False)