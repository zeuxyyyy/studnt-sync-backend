from flask import Blueprint, request, jsonify, session
import cloudinary.uploader
from database import db

chat_bp = Blueprint('chat', __name__)

def require_auth(f):
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

@chat_bp.route('/conversations')
@require_auth
def get_conversations():
    try:
        user_id = session['user_id']
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT
                CASE 
                    WHEN m.sender_id = ? THEN m.receiver_id
                    ELSE m.sender_id
                END as other_user_id,
                u.username, u.full_name, u.profile_photo_url,
                (SELECT text FROM messages m2 
                 WHERE (m2.sender_id = ? AND m2.receiver_id = other_user_id)
                    OR (m2.receiver_id = ? AND m2.sender_id = other_user_id)
                 ORDER BY m2.created_at DESC LIMIT 1) as last_message,
                (SELECT created_at FROM messages m2 
                 WHERE (m2.sender_id = ? AND m2.receiver_id = other_user_id)
                    OR (m2.receiver_id = ? AND m2.sender_id = other_user_id)
                 ORDER BY m2.created_at DESC LIMIT 1) as last_message_time,
                (SELECT COUNT(*) FROM messages m2 
                 WHERE m2.sender_id = other_user_id AND m2.receiver_id = ? 
                 AND m2.is_seen = 0) as unread_count
            FROM messages m
            JOIN users u ON u.id = CASE 
                WHEN m.sender_id = ? THEN m.receiver_id
                ELSE m.sender_id
            END
            WHERE m.sender_id = ? OR m.receiver_id = ?
            ORDER BY last_message_time DESC
        ''', (user_id, user_id, user_id, user_id, user_id, user_id, user_id, user_id, user_id))
        
        conversations = cursor.fetchall()
        conn.close()
        
        return jsonify({
            "conversations": [dict(conv) for conv in conversations]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@chat_bp.route('/messages/<int:other_user_id>')
@require_auth
def get_messages(other_user_id):
    try:
        user_id = session['user_id']
        page = int(request.args.get('page', 1))
        limit = 50
        offset = (page - 1) * limit
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Mark messages as seen
        cursor.execute(
            'UPDATE messages SET is_seen = 1 WHERE sender_id = ? AND receiver_id = ?',
            (other_user_id, user_id)
        )
        
        # Get messages
        cursor.execute('''
            SELECT m.*, u.username, u.profile_photo_url
            FROM messages m
            JOIN users u ON u.id = m.sender_id
            WHERE (m.sender_id = ? AND m.receiver_id = ?)
               OR (m.sender_id = ? AND m.receiver_id = ?)
            ORDER BY m.created_at DESC
            LIMIT ? OFFSET ?
        ''', (user_id, other_user_id, other_user_id, user_id, limit, offset))
        
        messages = cursor.fetchall()
        conn.commit()
        conn.close()
        
        return jsonify({
            "messages": [dict(msg) for msg in reversed(messages)]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@chat_bp.route('/send-message', methods=['POST'])
@require_auth
def send_message():
    try:
        data = request.get_json()
        sender_id = session['user_id']
        receiver_id = data.get('receiver_id')
        text = data.get('text', '').strip()
        
        if not receiver_id:
            return jsonify({"error": "Receiver ID required"}), 400
        
        if not text:
            return jsonify({"error": "Message text required"}), 400
        
        # Check if users are friends
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id FROM friends 
            WHERE (friend_1 = ? AND friend_2 = ?) OR (friend_1 = ? AND friend_2 = ?)
        ''', (sender_id, receiver_id, receiver_id, sender_id))
        
        if not cursor.fetchone():
            return jsonify({"error": "You can only message friends"}), 403
        
        # Insert message
        cursor.execute('''
            INSERT INTO messages (sender_id, receiver_id, text)
            VALUES (?, ?, ?)
        ''', (sender_id, receiver_id, text))
        
        message_id = cursor.lastrowid
        
        # Get the complete message data
        cursor.execute('''
            SELECT m.*, u.username, u.profile_photo_url
            FROM messages m
            JOIN users u ON u.id = m.sender_id
            WHERE m.id = ?
        ''', (message_id,))
        
        message = cursor.fetchone()
        conn.commit()
        conn.close()
        
        return jsonify({
            "message": "Message sent successfully",
            "data": dict(message)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@chat_bp.route('/upload-voice', methods=['POST'])
@require_auth
def upload_voice_note():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        receiver_id = request.form.get('receiver_id')
        sender_id = session['user_id']
        
        if not receiver_id:
            return jsonify({"error": "Receiver ID required"}), 400
        
        # Upload to Cloudinary
        result = cloudinary.uploader.upload(
            file,
            folder="teengram/voice_notes",
            resource_type="video"  # Cloudinary treats audio as video
        )
        
        # Check if users are friends
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id FROM friends 
            WHERE (friend_1 = ? AND friend_2 = ?) OR (friend_1 = ? AND friend_2 = ?)
        ''', (sender_id, receiver_id, receiver_id, sender_id))
        
        if not cursor.fetchone():
            return jsonify({"error": "You can only message friends"}), 403
        
        # Insert message
        cursor.execute('''
            INSERT INTO messages (sender_id, receiver_id, file_url)
            VALUES (?, ?, ?)
        ''', (sender_id, receiver_id, result['secure_url']))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "message": "Voice note sent successfully",
            "url": result['secure_url']
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500