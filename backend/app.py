from flask import Flask, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
import os
from datetime import datetime, timedelta
import bcrypt
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

from database import db
from utils import generate_teengram_number, generate_device_fingerprint, award_points, check_ban_status

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')
app.config['SESSION_TYPE'] = 'filesystem'

# Initialize extensions
socketio = SocketIO(app, cors_allowed_origins="*")
limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)
CORS(app)

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

# Import routes
from routes.auth_routes import auth_bp
from routes.user_routes import user_bp
from routes.chat_routes import chat_bp
from routes.post_routes import post_bp
from routes.admin_routes import admin_bp
from routes.api_routes import api_bp

# Register blueprints
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(user_bp, url_prefix='/user')
app.register_blueprint(chat_bp, url_prefix='/chat')
app.register_blueprint(post_bp, url_prefix='/posts')
app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(api_bp, url_prefix='/api')

# Socket events
from sockets.chat_sockets import *

@app.route('/')
def index():
    return jsonify({"message": "Teengram API is running!"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)