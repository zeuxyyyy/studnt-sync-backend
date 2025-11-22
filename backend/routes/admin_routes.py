from flask import Blueprint, request, jsonify, session
import bcrypt
from database import db
from datetime import datetime, timedelta

admin_bp = Blueprint('admin', __name__)

def require_admin(f):
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            return jsonify({"error": "Admin authentication required"}), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

@admin_bp.route('/login', methods=['POST'])
def admin_login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({"error": "Username and password required"}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM admin WHERE username = ?', (username,))
        admin = cursor.fetchone()
        conn.close()
        
        if not admin or not bcrypt.checkpw(password.encode('utf-8'), admin['password_hash'].encode('utf-8')):
            return jsonify({"error": "Invalid credentials"}), 401
        
        session['admin_id'] = admin['id']
        session['admin_username'] = admin['username']
        
        return jsonify({"message": "Admin login successful"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/dashboard')
@require_admin
def dashboard():
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get statistics
        cursor.execute('SELECT COUNT(*) FROM users WHERE status = "pending"')
        pending_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE status = "approved"')
        approved_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM posts')
        total_posts = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM reports WHERE status = "pending"')
        pending_reports = cursor.fetchone()[0]
        
        conn.close()
        
        return jsonify({
            "stats": {
                "pending_users": pending_users,
                "approved_users": approved_users,
                "total_posts": total_posts,
                "pending_reports": pending_reports
            }
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/pending-users')
@require_admin
def get_pending_users():
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, username, full_name, age, city, college_name, 
                   college_id_url, profile_photo_url, created_at
            FROM users 
            WHERE status = 'pending'
            ORDER BY created_at ASC
        ''')
        
        users = cursor.fetchall()
        conn.close()
        
        return jsonify({
            "users": [dict(user) for user in users]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/approve-user', methods=['POST'])
@require_admin
def approve_user():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({"error": "User ID required"}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'UPDATE users SET status = "approved" WHERE id = ?',
            (user_id,)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({"message": "User approved successfully"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/reject-user', methods=['POST'])
@require_admin
def reject_user():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({"error": "User ID required"}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'UPDATE users SET status = "rejected" WHERE id = ?',
            (user_id,)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({"message": "User rejected successfully"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/reports')
@require_admin
def get_reports():
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT r.*, 
                   u1.username as reporter_username,
                   u2.username as reported_username,
                   p.text as post_text
            FROM reports r
            LEFT JOIN users u1 ON u1.id = r.reporter_id
            LEFT JOIN users u2 ON u2.id = r.reported_user_id
            LEFT JOIN posts p ON p.id = r.reported_post_id
            WHERE r.status = 'pending'
            ORDER BY r.created_at DESC
        ''')
        
        reports = cursor.fetchall()
        conn.close()
        
        return jsonify({
            "reports": [dict(report) for report in reports]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/ban-user', methods=['POST'])
@require_admin
def ban_user():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        reason = data.get('reason')
        duration = data.get('duration')  # '24h', '7d', 'permanent'
        
        if not user_id or not reason:
            return jsonify({"error": "User ID and reason required"}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        if duration == 'permanent':
            ban_end = None
            is_permanent = True
        else:
            is_permanent = False
            if duration == '24h':
                ban_end = datetime.now() + timedelta(hours=24)
            elif duration == '7d':
                ban_end = datetime.now() + timedelta(days=7)
            else:
                return jsonify({"error": "Invalid duration"}), 400
        
                cursor.execute('''
            INSERT INTO bans (user_id, reason, ban_end, is_permanent)
            VALUES (?, ?, ?, ?)
        ''', (user_id, reason, ban_end, is_permanent))
        
        conn.commit()
        conn.close()
        
        return jsonify({"message": "User banned successfully"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/resolve-report', methods=['POST'])
@require_admin
def resolve_report():
    try:
        data = request.get_json()
        report_id = data.get('report_id')
        action = data.get('action')  # 'dismiss' or 'action_taken'
        
        if not report_id or not action:
            return jsonify({"error": "Report ID and action required"}), 400
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            'UPDATE reports SET status = ? WHERE id = ?',
            (action, report_id)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({"message": "Report resolved successfully"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/logout', methods=['POST'])
@require_admin
def admin_logout():
    session.clear()
    return jsonify({"message": "Admin logged out successfully"}), 200