from flask_socketio import emit, join_room, leave_room, disconnect
from flask import session, request
from database import db
import json

# Store active users
active_users = {}
typing_users = {}

def authenticated_only(f):
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            disconnect()
        else:
            return f(*args, **kwargs)
    return wrapped

@socketio.on('connect')
@authenticated_only
def on_connect():
    user_id = session['user_id']
    active_users[request.sid] = user_id
    
    # Join user's personal room
    join_room(f"user_{user_id}")
    
    emit('connected', {'message': 'Connected to chat server'})
    print(f"User {user_id} connected")

@socketio.on('disconnect')
def on_disconnect():
    if request.sid in active_users:
        user_id = active_users[request.sid]
        del active_users[request.sid]
        
        # Remove from typing users
        if request.sid in typing_users:
            del typing_users[request.sid]
        
        print(f"User {user_id} disconnected")

@socketio.on('join_chat')
@authenticated_only
def on_join_chat(data):
    user_id = session['user_id']
    other_user_id = data['other_user_id']
    
    # Create room name (consistent ordering)
    room = f"chat_{min(user_id, other_user_id)}_{max(user_id, other_user_id)}"
    join_room(room)
    
    emit('joined_chat', {'room': room, 'other_user_id': other_user_id})

@socketio.on('leave_chat')
@authenticated_only
def on_leave_chat(data):
    user_id = session['user_id']
    other_user_id = data['other_user_id']
    
    room = f"chat_{min(user_id, other_user_id)}_{max(user_id, other_user_id)}"
    leave_room(room)
    
    emit('left_chat', {'room': room})

@socketio.on('send_message')
@authenticated_only
def on_send_message(data):
    try:
        sender_id = session['user_id']
        receiver_id = data['receiver_id']
        text = data['text']
        
        # Verify friendship
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id FROM friends 
            WHERE (friend_1 = ? AND friend_2 = ?) OR (friend_1 = ? AND friend_2 = ?)
        ''', (sender_id, receiver_id, receiver_id, sender_id))
        
        if not cursor.fetchone():
            emit('error', {'message': 'You can only message friends'})
            return
        
        # Insert message
        cursor.execute('''
            INSERT INTO messages (sender_id, receiver_id, text)
            VALUES (?, ?, ?)
        ''', (sender_id, receiver_id, text))
        
        message_id = cursor.lastrowid
        
        # Get complete message data
        cursor.execute('''
            SELECT m.*, u.username, u.profile_photo_url
            FROM messages m
            JOIN users u ON u.id = m.sender_id
            WHERE m.id = ?
        ''', (message_id,))
        
        message = dict(cursor.fetchone())
        
        conn.commit()
        conn.close()
        
        # Send to both users
        room = f"chat_{min(sender_id, receiver_id)}_{max(sender_id, receiver_id)}"
        socketio.emit('new_message', message, room=room)
        
        # Send notification to receiver if online
        socketio.emit('message_notification', {
            'sender_id': sender_id,
            'sender_username': session.get('username'),
            'text': text
        }, room=f"user_{receiver_id}")
        
    except Exception as e:
        emit('error', {'message': str(e)})

@socketio.on('typing_start')
@authenticated_only
def on_typing_start(data):
    user_id = session['user_id']
    other_user_id = data['other_user_id']
    
    typing_users[request.sid] = {
        'user_id': user_id,
        'other_user_id': other_user_id
    }
    
    room = f"chat_{min(user_id, other_user_id)}_{max(user_id, other_user_id)}"
    socketio.emit('user_typing', {
        'user_id': user_id,
        'username': session.get('username')
    }, room=room, include_self=False)

@socketio.on('typing_stop')
@authenticated_only
def on_typing_stop(data):
    user_id = session['user_id']
    other_user_id = data['other_user_id']
    
    if request.sid in typing_users:
        del typing_users[request.sid]
    
    room = f"chat_{min(user_id, other_user_id)}_{max(user_id, other_user_id)}"
    socketio.emit('user_stopped_typing', {
        'user_id': user_id
    }, room=room, include_self=False)

@socketio.on('mark_seen')
@authenticated_only
def on_mark_seen(data):
    try:
        user_id = session['user_id']
        other_user_id = data['other_user_id']
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Mark messages as seen
        cursor.execute('''
            UPDATE messages SET is_seen = 1 
            WHERE sender_id = ? AND receiver_id = ? AND is_seen = 0
        ''', (other_user_id, user_id))
        
        conn.commit()
        conn.close()
        
        # Notify sender that messages were seen
        socketio.emit('messages_seen', {
            'seen_by': user_id
        }, room=f"user_{other_user_id}")
        
    except Exception as e:
        emit('error', {'message': str(e)})