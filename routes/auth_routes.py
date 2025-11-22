from flask import Blueprint, request, jsonify, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import bcrypt
import cloudinary.uploader
from database import db
from utils import generate_teengram_number, generate_device_fingerprint, check_ban_status

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/signup', methods=['POST'])
def signup():
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['username', 'full_name', 'password', 'age', 'city', 'gender', 'college_name']
                for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({"error": f"{field} is required"}), 400
        
        # Validate age
        if not (13 <= int(data['age']) <= 25):
            return jsonify({"error": "Age must be between 13-25"}), 400
        
        # Validate username
        username = data['username'].lower().strip()
        if len(username) < 3 or not username.isalnum():
            return jsonify({"error": "Username must be alphanumeric and at least 3 characters"}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Check if username exists
        cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
        if cursor.fetchone():
            return jsonify({"error": "Username already exists"}), 400
        
        # Check device limit
        device_fingerprint = generate_device_fingerprint(
            request.headers.get('User-Agent', ''),
            request.remote_addr
        )
        
        cursor.execute('SELECT COUNT(*) FROM device_ids WHERE device_fingerprint = ?', (device_fingerprint,))
        device_count = cursor.fetchone()[0]
        
        if device_count >= 2:
            return jsonify({"error": "Device limit exceeded. Maximum 2 accounts per device."}), 400
        
        # Hash password
        password_hash = bcrypt.hashpw(data['password'].encode('utf-8'), bcrypt.gensalt())
        
        # Generate Teengram number
        teengram_number = generate_teengram_number(username)
        
        # Insert user
        cursor.execute('''
            INSERT INTO users (username, full_name, password_hash, age, city, gender, 
                             college_name, bio, teengram_number, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        ''', (
            username, data['full_name'], password_hash.decode('utf-8'),
            data['age'], data['city'], data['gender'], data['college_name'],
            data.get('bio', ''), teengram_number
        ))
        
        user_id = cursor.lastrowid
        
        # Store device fingerprint
        cursor.execute(
            'INSERT INTO device_ids (device_fingerprint, user_id) VALUES (?, ?)',
            (device_fingerprint, user_id)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "message": "Account created successfully! Waiting for admin approval.",
            "user_id": user_id,
            "teengram_number": teengram_number
        }), 201
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username', '').lower().strip()
        password = data.get('password', '')
        
        if not username or not password:
            return jsonify({"error": "Username and password required"}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get user
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({"error": "Invalid credentials"}), 401
        
        # Check password
        if not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            return jsonify({"error": "Invalid credentials"}), 401
        
        # Check user status
        if user['status'] == 'pending':
            return jsonify({"error": "Your account is pending admin approval"}), 403
        
        if user['status'] == 'rejected':
            return jsonify({"error": "Your account has been rejected"}), 403
        
        # Check ban status
        ban_status = check_ban_status(user['id'])
        if ban_status['is_banned']:
            if ban_status['is_permanent']:
                return jsonify({"error": "Your account has been permanently banned"}), 403
            else:
                return jsonify({
                    "error": f"You are banned until {ban_status['ban_end']}",
                    "ban_end": ban_status['ban_end']
                }), 403
        
        # Update last login
        cursor.execute(
            'UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?',
            (user['id'],)
        )
        
        # Award daily login points
        cursor.execute('''
            SELECT COUNT(*) FROM points 
            WHERE user_id = ? AND reason = 'Daily login' 
            AND DATE(created_at) = DATE('now')
        ''', (user['id'],))
        
        if cursor.fetchone()[0] == 0:
            from utils import award_points
            award_points(user['id'], 1, 'Daily login')
        
        conn.commit()
        conn.close()
        
        # Create session
        session['user_id'] = user['id']
        session['username'] = user['username']
        
        return jsonify({
            "message": "Login successful",
            "user": {
                "id": user['id'],
                "username": user['username'],
                "full_name": user['full_name'],
                "teengram_number": user['teengram_number'],
                "profile_photo_url": user['profile_photo_url'],
                "points": user['points']
            }
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200

@auth_bp.route('/upload-college-id', methods=['POST'])
def upload_college_id():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        user_id = request.form.get('user_id')
        
        if not user_id:
            return jsonify({"error": "User ID required"}), 400
        
        # Upload to Cloudinary
        result = cloudinary.uploader.upload(
            file,
            folder="teengram/college_ids",
            resource_type="auto"
        )
        
        # Update user record
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET college_id_url = ? WHERE id = ?',
            (result['secure_url'], user_id)
        )
        conn.commit()
        conn.close()
        
        return jsonify({
            "message": "College ID uploaded successfully",
            "url": result['secure_url']
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@auth_bp.route('/upload-profile-photo', methods=['POST'])
def upload_profile_photo():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        user_id = request.form.get('user_id')
        
        if not user_id:
            return jsonify({"error": "User ID required"}), 400
        
        # Upload to Cloudinary
        result = cloudinary.uploader.upload(
            file,
            folder="teengram/profile_photos",
            transformation=[
                {'width': 400, 'height': 400, 'crop': 'fill'},
                {'quality': 'auto'}
            ]
        )
        
        # Update user record
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET profile_photo_url = ? WHERE id = ?',
            (result['secure_url'], user_id)
        )
        conn.commit()
        conn.close()
        
        return jsonify({
            "message": "Profile photo uploaded successfully",
            "url": result['secure_url']
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500