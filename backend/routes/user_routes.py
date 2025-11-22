from flask import Blueprint, request, jsonify, session
import cloudinary.uploader
from database import db
from utils import award_points

user_bp = Blueprint('user', __name__)

def require_auth(f):
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

@user_bp.route('/profile/<username>')
@require_auth
def get_profile(username):
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT u.*, 
                   (SELECT COUNT(*) FROM posts WHERE user_id = u.id) as posts_count,
                   (SELECT COUNT(*) FROM friends WHERE friend_1 = u.id OR friend_2 = u.id) as friends_count
            FROM users u WHERE username = ? AND status = 'approved'
        ''', (username,))
        
        user = cursor.fetchone()
        conn.close()
        
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        return jsonify({
            "user": {
                "id": user['id'],
                "username": user['username'],
                "full_name": user['full_name'],
                "age": user['age'],
                "city": user['city'],
                "college_name": user['college_name'],
                "bio": user['bio'],
                "interests": user['interests'],
                "teengram_number": user['teengram_number'],
                "profile_photo_url": user['profile_photo_url'],
                "points": user['points'],
                "posts_count": user['posts_count'],
                "friends_count": user['friends_count']
            }
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@user_bp.route('/update-profile', methods=['PUT'])
@require_auth
def update_profile():
    try:
        data = request.get_json()
        user_id = session['user_id']
        
        allowed_fields = ['full_name', 'bio', 'city', 'interests']
        update_fields = []
        values = []
        
        for field in allowed_fields:
            if field in data:
                update_fields.append(f"{field} = ?")
                values.append(data[field])
        
        if not update_fields:
            return jsonify({"error": "No valid fields to update"}), 400
        
        values.append(user_id)
        
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE users SET {', '.join(update_fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values
        )
        conn.commit()
        conn.close()
        
        return jsonify({"message": "Profile updated successfully"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@user_bp.route('/search')
@require_auth
def search_users():
    try:
        query = request.args.get('q', '').strip()
        
        if len(query) < 2:
            return jsonify({"users": []}), 200
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, username, full_name, profile_photo_url, college_name
            FROM users 
            WHERE (username LIKE ? OR full_name LIKE ?) 
            AND status = 'approved' 
            AND id != ?
            LIMIT 20
        ''', (f'%{query}%', f'%{query}%', session['user_id']))
        
        users = cursor.fetchall()
        conn.close()
        
        return jsonify({
            "users": [dict(user) for user in users]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@user_bp.route('/campus-connect')
@require_auth
def campus_connect():
    try:
        user_id = session['user_id']
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get users that haven't been skipped in last 30 days and not already friends
        cursor.execute('''
            SELECT u.id, u.username, u.full_name, u.profile_photo_url, 
                   u.college_name, u.age, u.city
            FROM users u
            WHERE u.id != ? 
            AND u.status = 'approved'
            AND u.id NOT IN (
                SELECT friend_1 FROM friends WHERE friend_2 = ?
                UNION
                SELECT friend_2 FROM friends WHERE friend_1 = ?
            )
            AND u.id NOT IN (
                SELECT skipped_user_id FROM skips 
                WHERE user_id = ? AND created_at > datetime('now', '-30 days')
            )
            ORDER BY RANDOM()
            LIMIT 10
        ''', (user_id, user_id, user_id, user_id))
        
        users = cursor.fetchall()
        conn.close()
        
        return jsonify({
            "users": [dict(user) for user in users]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@user_bp.route('/wave', methods=['POST'])
@require_auth
def send_wave():
    try:
        data = request.get_json()
        receiver_id = data.get('receiver_id')
        sender_id = session['user_id']
        
        if not receiver_id:
            return jsonify({"error": "Receiver ID required"}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Check if already waved
        cursor.execute(
            'SELECT id FROM waves WHERE sender_id = ? AND receiver_id = ?',
            (sender_id, receiver_id)
        )
        
        if cursor.fetchone():
            return jsonify({"error": "Already waved to this user"}), 400
        
        # Insert wave
        cursor.execute(
            'INSERT INTO waves (sender_id, receiver_id) VALUES (?, ?)',
            (sender_id, receiver_id)
        )
        
        # Check if receiver also waved back
        cursor.execute(
            'SELECT id FROM waves WHERE sender_id = ? AND receiver_id = ?',
            (receiver_id, sender_id)
        )
        
        mutual_wave = cursor.fetchone()
        
        if mutual_wave:
            # Create friendship
            cursor.execute(
                'INSERT INTO friends (friend_1, friend_2) VALUES (?, ?)',
                (min(sender_id, receiver_id), max(sender_id, receiver_id))
            )
            
            # Award points to both users
            award_points(sender_id, 2, 'New friend')
            award_points(receiver_id, 2, 'New friend')
            
            conn.commit()
            conn.close()
            
            return jsonify({
                "message": "Connected! You're now friends!",
                "connected": True
            }), 200
        
        conn.commit()
        conn.close()
        
               return jsonify({
            "message": "Wave sent successfully",
            "connected": False
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@user_bp.route('/skip', methods=['POST'])
@require_auth
def skip_user():
    try:
        data = request.get_json()
        skipped_user_id = data.get('user_id')
        user_id = session['user_id']
        
        if not skipped_user_id:
            return jsonify({"error": "User ID required"}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Insert skip record
        cursor.execute(
            'INSERT OR REPLACE INTO skips (user_id, skipped_user_id) VALUES (?, ?)',
            (user_id, skipped_user_id)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({"message": "User skipped"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@user_bp.route('/friends')
@require_auth
def get_friends():
    try:
        user_id = session['user_id']
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT u.id, u.username, u.full_name, u.profile_photo_url, 
                   u.college_name, f.connected_time
            FROM friends f
            JOIN users u ON (
                CASE 
                    WHEN f.friend_1 = ? THEN u.id = f.friend_2
                    ELSE u.id = f.friend_1
                END
            )
            WHERE f.friend_1 = ? OR f.friend_2 = ?
            ORDER BY f.connected_time DESC
        ''', (user_id, user_id, user_id))
        
        friends = cursor.fetchall()
        conn.close()
        
        return jsonify({
            "friends": [dict(friend) for friend in friends]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@user_bp.route('/leaderboard')
@require_auth
def get_leaderboard():
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT username, full_name, college_name, points,
                   ROW_NUMBER() OVER (ORDER BY points DESC) as rank
            FROM users 
            WHERE status = 'approved'
            ORDER BY points DESC
            LIMIT 50
        ''', )
        
        leaderboard = cursor.fetchall()
        conn.close()
        
        return jsonify({
            "leaderboard": [dict(user) for user in leaderboard]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@user_bp.route('/report', methods=['POST'])
@require_auth
def report_user():
    try:
        data = request.get_json()
        reporter_id = session['user_id']
        
        required_fields = ['type', 'reason']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"{field} is required"}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        report_data = {
            'reporter_id': reporter_id,
            'reason': data['reason'],
            'reported_user_id': data.get('user_id'),
            'reported_post_id': data.get('post_id'),
            'reported_message_id': data.get('message_id')
        }
        
        cursor.execute('''
            INSERT INTO reports (reporter_id, reported_user_id, reported_post_id, 
                               reported_message_id, reason)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            report_data['reporter_id'],
            report_data['reported_user_id'],
            report_data['reported_post_id'],
            report_data['reported_message_id'],
            report_data['reason']
        ))
        
        conn.commit()
        conn.close()
        
        return jsonify({"message": "Report submitted successfully"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500