from flask import Blueprint, request, jsonify, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

api_bp = Blueprint('api', __name__)

@api_bp.route('/status')
def api_status():
    return jsonify({
        "status": "online",
        "version": "1.0.0",
        "timestamp": "2025-11-22"
    }), 200

@api_bp.route('/check-session')
def check_session():
    if 'user_id' in session:
        return jsonify({
            "authenticated": True,
            "user_id": session['user_id'],
            "username": session.get('username')
        }), 200
    else:
        return jsonify({"authenticated": False}), 200