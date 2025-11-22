import random
import string
import hashlib
from datetime import datetime, timedelta

def generate_teengram_number(username):
    """Generate Teengram contact number: 9 + 2 username chars + 3 random digits"""
    prefix = "9"
    username_part = username[:2].upper()
    random_part = str(random.randint(100, 999))
    return prefix + username_part + random_part

def generate_device_fingerprint(user_agent, ip_address):
    """Generate device fingerprint for multi-account prevention"""
    data = f"{user_agent}{ip_address}"
    return hashlib.md5(data.encode()).hexdigest()

def award_points(user_id, points, reason):
    """Award points to user"""
    from database import db
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # Add to points table
    cursor.execute(
        'INSERT INTO points (user_id, points, reason) VALUES (?, ?, ?)',
        (user_id, points, reason)
    )
    
    # Update user total points
    cursor.execute(
        'UPDATE users SET points = points + ? WHERE id = ?',
        (points, user_id)
    )
    
    conn.commit()
    conn.close()

def check_ban_status(user_id):
    """Check if user is currently banned"""
    from database import db
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM bans 
        WHERE user_id = ? AND (is_permanent = TRUE OR ban_end > CURRENT_TIMESTAMP)
        ORDER BY ban_start DESC LIMIT 1
    ''', (user_id,))
    
    ban = cursor.fetchone()
    conn.close()
    
    if ban:
        return {
            'is_banned': True,
            'reason': ban['reason'],
            'ban_end': ban['ban_end'],
            'is_permanent': ban['is_permanent']
        }
    
    return {'is_banned': False}

def validate_file_upload(file):
    """Validate uploaded files"""
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'mp3', 'wav'}
    max_size = 10 * 1024 * 1024  # 10MB
    
    if not file:
        return False, "No file provided"
    
    if file.content_length > max_size:
        return False, "File too large"
    
    extension = file.filename.rsplit('.', 1)[1].lower()
    if extension not in allowed_extensions:
        return False, "Invalid file type"
    
    return True, "Valid file"