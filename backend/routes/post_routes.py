from flask import Blueprint, request, jsonify, session
import cloudinary.uploader
from database import db
from utils import award_points

post_bp = Blueprint('posts', __name__)

def require_auth(f):
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

@post_bp.route('/create', methods=['POST'])
@require_auth
def create_post():
    try:
        data = request.get_json()
        user_id = session['user_id']
        text = data.get('text', '').strip()
        image_url = data.get('image_url')
        
        if not text and not image_url:
            return jsonify({"error": "Post must contain text or image"}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO posts (user_id, text, image_url)
            VALUES (?, ?, ?)
        ''', (user_id, text, image_url))
        
        post_id = cursor.lastrowid
        
        # Award points for posting
        award_points(user_id, 5, 'New post')
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "message": "Post created successfully",
            "post_id": post_id
        }), 201
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@post_bp.route('/upload-image', methods=['POST'])
@require_auth
def upload_post_image():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        
        # Upload to Cloudinary
        result = cloudinary.uploader.upload(
            file,
            folder="teengram/posts",
            transformation=[
                {'width': 800, 'height': 800, 'crop': 'limit'},
                {'quality': 'auto'}
            ]
        )
        
        return jsonify({
            "message": "Image uploaded successfully",
            "url": result['secure_url']
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@post_bp.route('/feed')
@require_auth
def get_feed():
    try:
        user_id = session['user_id']
        feed_type = request.args.get('type', 'latest')  # latest, recommended, friends
        page = int(request.args.get('page', 1))
        limit = 20
        offset = (page - 1) * limit
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        if feed_type == 'friends':
            # Only posts from friends
            cursor.execute('''
                SELECT p.*, u.username, u.full_name, u.profile_photo_url,
                       (SELECT COUNT(*) FROM likes WHERE post_id = p.id) as likes_count,
                       (SELECT COUNT(*) FROM comments WHERE post_id = p.id) as comments_count,
                       (SELECT COUNT(*) FROM likes WHERE post_id = p.id AND user_id = ?) as user_liked
                FROM posts p
                JOIN users u ON u.id = p.user_id
                WHERE p.user_id IN (
                    SELECT CASE 
                                               WHEN friend_1 = ? THEN friend_2
                        ELSE friend_1
                    END
                    FROM friends 
                    WHERE friend_1 = ? OR friend_2 = ?
                )
                ORDER BY p.created_at DESC
                LIMIT ? OFFSET ?
            ''', (user_id, user_id, user_id, user_id, limit, offset))
        else:
            # All posts (latest or recommended)
            order_by = "p.created_at DESC" if feed_type == 'latest' else "p.likes_count DESC, p.created_at DESC"
            
            cursor.execute(f'''
                SELECT p.*, u.username, u.full_name, u.profile_photo_url,
                       (SELECT COUNT(*) FROM likes WHERE post_id = p.id) as likes_count,
                       (SELECT COUNT(*) FROM comments WHERE post_id = p.id) as comments_count,
                       (SELECT COUNT(*) FROM likes WHERE post_id = p.id AND user_id = ?) as user_liked
                FROM posts p
                JOIN users u ON u.id = p.user_id
                WHERE u.status = 'approved'
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
            ''', (user_id, limit, offset))
        
        posts = cursor.fetchall()
        conn.close()
        
        return jsonify({
            "posts": [dict(post) for post in posts]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@post_bp.route('/like', methods=['POST'])
@require_auth
def like_post():
    try:
        data = request.get_json()
        post_id = data.get('post_id')
        user_id = session['user_id']
        
        if not post_id:
            return jsonify({"error": "Post ID required"}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Check if already liked
        cursor.execute(
            'SELECT id FROM likes WHERE post_id = ? AND user_id = ?',
            (post_id, user_id)
        )
        
        if cursor.fetchone():
            # Unlike
            cursor.execute(
                'DELETE FROM likes WHERE post_id = ? AND user_id = ?',
                (post_id, user_id)
            )
            
            # Update post likes count
            cursor.execute(
                'UPDATE posts SET likes_count = likes_count - 1 WHERE id = ?',
                (post_id,)
            )
            
            message = "Post unliked"
            liked = False
        else:
            # Like
            cursor.execute(
                'INSERT INTO likes (post_id, user_id) VALUES (?, ?)',
                (post_id, user_id)
            )
            
            # Update post likes count
            cursor.execute(
                'UPDATE posts SET likes_count = likes_count + 1 WHERE id = ?',
                (post_id,)
            )
            
            # Award points to post author
            cursor.execute('SELECT user_id FROM posts WHERE id = ?', (post_id,))
            post_author = cursor.fetchone()
            if post_author and post_author['user_id'] != user_id:
                award_points(post_author['user_id'], 1, 'Post liked')
            
            message = "Post liked"
            liked = True
        
        # Get updated likes count
        cursor.execute('SELECT likes_count FROM posts WHERE id = ?', (post_id,))
        likes_count = cursor.fetchone()['likes_count']
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "message": message,
            "liked": liked,
            "likes_count": likes_count
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@post_bp.route('/comment', methods=['POST'])
@require_auth
def add_comment():
    try:
        data = request.get_json()
        post_id = data.get('post_id')
        text = data.get('text', '').strip()
        user_id = session['user_id']
        
        if not post_id or not text:
            return jsonify({"error": "Post ID and comment text required"}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO comments (post_id, user_id, text)
            VALUES (?, ?, ?)
        ''', (post_id, user_id, text))
        
        # Update post comments count
        cursor.execute(
            'UPDATE posts SET comments_count = comments_count + 1 WHERE id = ?',
            (post_id,)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({"message": "Comment added successfully"}), 201
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@post_bp.route('/<int:post_id>/comments')
@require_auth
def get_comments(post_id):
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT c.*, u.username, u.full_name, u.profile_photo_url
            FROM comments c
            JOIN users u ON u.id = c.user_id
            WHERE c.post_id = ?
            ORDER BY c.created_at ASC
        ''', (post_id,))
        
        comments = cursor.fetchall()
        conn.close()
        
        return jsonify({
            "comments": [dict(comment) for comment in comments]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@post_bp.route('/stories/create', methods=['POST'])
@require_auth
def create_story():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        user_id = session['user_id']
        
        # Upload to Cloudinary
        result = cloudinary.uploader.upload(
            file,
            folder="teengram/stories",
            resource_type="auto"
        )
        
        # Calculate expiry time (24 hours)
        from datetime import datetime, timedelta
        expires_at = datetime.now() + timedelta(hours=24)
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO stories (user_id, file_url, expires_at)
            VALUES (?, ?, ?)
        ''', (user_id, result['secure_url'], expires_at))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "message": "Story created successfully",
            "url": result['secure_url']
        }), 201
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@post_bp.route('/stories')
@require_auth
def get_stories():
    try:
        user_id = session['user_id']
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get stories from friends that haven't expired
        cursor.execute('''
            SELECT s.*, u.username, u.full_name, u.profile_photo_url
            FROM stories s
            JOIN users u ON u.id = s.user_id
            WHERE s.expires_at > CURRENT_TIMESTAMP
            AND (s.user_id = ? OR s.user_id IN (
                SELECT CASE 
                    WHEN friend_1 = ? THEN friend_2
                    ELSE friend_1
                END
                FROM friends 
                WHERE friend_1 = ? OR friend_2 = ?
            ))
            ORDER BY s.created_at DESC
        ''', (user_id, user_id, user_id, user_id))
        
        stories = cursor.fetchall()
        conn.close()
        
        return jsonify({
            "stories": [dict(story) for story in stories]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@post_bp.route('/stories/<int:story_id>/view', methods=['POST'])
@require_auth
def view_story(story_id):
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Increment view count
        cursor.execute(
            'UPDATE stories SET view_count = view_count + 1 WHERE id = ?',
            (story_id,)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({"message": "Story viewed"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
                        