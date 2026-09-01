#!/usr/bin/env python3
"""
PREMIUM LICENSE SERVER - FULLY ENCRYPTED
Custom Key Generation - Beautiful Admin Panel
"""

import os
import json
import time
import base64
import hashlib
import secrets
import sqlite3
import hmac as hmac_lib
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, Response
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)

# ==================== YOUR GENERATED KEYS ====================
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', 'bLz3tCIMOK8swF9V8kKcDcluOujcJNk-1dX7vXemlzH1r5qyOpNi7pp7Xqclmuly')
HMAC_SECRET = os.environ.get('HMAC_SECRET', '0NJEZZ_TzdatKylxit9xngI2JT2nZVnpnGkIC5c3XmMNpB1rlM3cHozyh_Jcbscc')
app.secret_key = os.environ.get('SECRET_KEY', '2abaee32567fe4d9f80475ead5d949e004a3babd75f68775abe825fefd24f095')

ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'RQ8bGmz108J52Z52qr7F_A')

DATABASE_PATH = 'database.db'

# ==================== LOGGING ====================
logger = logging.getLogger(__name__)
handler = RotatingFileHandler('server.log', maxBytes=5000000, backupCount=3)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ==================== CRYPTO ====================
class CryptoManager:
    def __init__(self):
        self.enc_key = self._derive_key(ENCRYPTION_KEY, b'ENC_SALT_2024_X9')
        self.hmac_key = self._derive_key(HMAC_SECRET, b'HMAC_SALT_2024_X9')
        self.fernet = Fernet(self.enc_key)
    
    def _derive_key(self, secret, salt):
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=500000,
        )
        return base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    
    def encrypt(self, data):
        return self.fernet.encrypt(data.encode()).decode()
    
    def decrypt(self, encrypted):
        return self.fernet.decrypt(encrypted.encode()).decode()
    
    def sign(self, data):
        return hmac_lib.new(self.hmac_key, data.encode(), hashlib.sha256).hexdigest()
    
    def verify(self, data, signature):
        return hmac_lib.compare_digest(self.sign(data), signature)
    
    def create_response(self, data_dict):
        encrypted = self.encrypt(json.dumps(data_dict))
        signature = self.sign(encrypted)
        return {'payload': encrypted, 'signature': signature}
    
    def create_error(self, message, code):
        return self.create_response({'success': False, 'message': message, 'error_code': code})

crypto = CryptoManager()

# ==================== DATABASE ====================
def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS licenses
                 (license_key TEXT PRIMARY KEY,
                  is_active INTEGER DEFAULT 1,
                  expires_at TEXT,
                  max_devices INTEGER DEFAULT 1,
                  notes TEXT DEFAULT '',
                  created_at TEXT,
                  created_by TEXT DEFAULT 'admin',
                  duration_type TEXT DEFAULT 'days',
                  duration_value INTEGER DEFAULT 30)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS devices
                 (hwid TEXT,
                  license_key TEXT,
                  device_name TEXT DEFAULT 'Unknown',
                  android_version TEXT DEFAULT 'Unknown',
                  device_model TEXT DEFAULT 'Unknown',
                  ip_address TEXT DEFAULT '',
                  country TEXT DEFAULT '',
                  registered_at TEXT,
                  last_login TEXT,
                  login_count INTEGER DEFAULT 0,
                  PRIMARY KEY (hwid, license_key))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  license_key TEXT,
                  hwid TEXT,
                  ip TEXT,
                  user_agent TEXT DEFAULT '',
                  success INTEGER,
                  message TEXT,
                  response_time REAL DEFAULT 0,
                  time TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS admin_logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  admin TEXT,
                  action TEXT,
                  details TEXT,
                  ip TEXT,
                  time TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS sessions
                 (token TEXT PRIMARY KEY,
                  license_key TEXT,
                  hwid TEXT,
                  created_at TEXT,
                  expires_at TEXT,
                  is_active INTEGER DEFAULT 1)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS api_keys
                 (api_key TEXT PRIMARY KEY,
                  name TEXT DEFAULT 'Default',
                  is_active INTEGER DEFAULT 1,
                  created_at TEXT)''')
    
    conn.commit()
    conn.close()

init_db()

# ==================== HELPERS ====================
def gen_key():
    return "-".join(secrets.token_hex(2).upper() for _ in range(4))

def get_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

def get_ua():
    return request.headers.get('User-Agent', 'Unknown')

def log_login(license_key, hwid, ip, ua, success, message, rt):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO logs (license_key, hwid, ip, user_agent, success, message, response_time, time) VALUES (?,?,?,?,?,?,?,?)",
              (license_key, hwid, ip, ua, success, message, rt, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

def log_admin(admin, action, details, ip):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO admin_logs (admin, action, details, ip, time) VALUES (?,?,?,?,?)",
              (admin, action, details, ip, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'admin' not in session:
            return redirect('/admin')
        return f(*args, **kwargs)
    return decorated

# ==================== LOGIN API ====================
@app.route('/api/login', methods=['POST'])
def api_login():
    start = time.time()
    ip = get_ip()
    
    try:
        data = request.get_json()
        
        if not data or 'payload' not in data or 'signature' not in data:
            return jsonify(crypto.create_error('Invalid request', 'INVALID_REQUEST')), 400
        
        if not crypto.verify(data['payload'], data['signature']):
            return jsonify(crypto.create_error('Signature failed', 'TAMPERING_DETECTED')), 403
        
        decrypted = crypto.decrypt(data['payload'])
        login_data = json.loads(decrypted)
        
        hwid = login_data.get('hwid')
        license_key = login_data.get('license_key')
        
        if not hwid or not license_key:
            return jsonify(crypto.create_error('Missing fields', 'MISSING_FIELDS')), 400
        
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM licenses WHERE license_key = ?", (license_key,))
        lic = c.fetchone()
        
        if not lic:
            log_login(license_key, hwid, ip, get_ua(), 0, 'Invalid key', time.time() - start)
            conn.close()
            return jsonify(crypto.create_error('Invalid license key', 'INVALID_KEY')), 401
        
        if lic[1] != 1:
            log_login(license_key, hwid, ip, get_ua(), 0, 'Key disabled', time.time() - start)
            conn.close()
            return jsonify(crypto.create_error('License disabled', 'KEY_DISABLED')), 403
        
        if lic[2] and datetime.strptime(lic[2], '%Y-%m-%d %H:%M:%S') < datetime.now():
            log_login(license_key, hwid, ip, get_ua(), 0, 'Key expired', time.time() - start)
            conn.close()
            return jsonify(crypto.create_error('License expired', 'KEY_EXPIRED')), 403
        
        c.execute("SELECT * FROM devices WHERE hwid = ? AND license_key = ?", (hwid, license_key))
        existing = c.fetchone()
        
        if existing:
            c.execute("UPDATE devices SET last_login = ?, login_count = login_count + 1, ip_address = ? WHERE hwid = ? AND license_key = ?",
                     (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ip, hwid, license_key))
            conn.commit()
            token = secrets.token_urlsafe(48)
            c.execute("INSERT INTO sessions (token, license_key, hwid, created_at, expires_at) VALUES (?,?,?,?,?)",
                     (token, license_key, hwid, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), (datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            log_login(license_key, hwid, ip, get_ua(), 1, 'Login success', time.time() - start)
            conn.close()
            return jsonify(crypto.create_response({'success': True, 'message': 'Login successful', 'session_token': token, 'expires_at': lic[2]}))
        
        c.execute("SELECT COUNT(*) FROM devices WHERE license_key = ?", (license_key,))
        device_count = c.fetchone()[0]
        
        if device_count >= lic[3]:
            log_login(license_key, hwid, ip, get_ua(), 0, 'Max devices', time.time() - start)
            conn.close()
            return jsonify(crypto.create_error('Maximum devices reached', 'MAX_DEVICES')), 403
        
        c.execute("INSERT INTO devices (hwid, license_key, device_name, android_version, device_model, ip_address, registered_at, last_login, login_count) VALUES (?,?,?,?,?,?,?,?,?)",
                 (hwid, license_key, login_data.get('device_name', 'Unknown'), login_data.get('android_version', 'Unknown'), login_data.get('device_model', 'Unknown'), ip, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 1))
        conn.commit()
        
        token = secrets.token_urlsafe(48)
        c.execute("INSERT INTO sessions (token, license_key, hwid, created_at, expires_at) VALUES (?,?,?,?,?)",
                 (token, license_key, hwid, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), (datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        log_login(license_key, hwid, ip, get_ua(), 1, 'New device', time.time() - start)
        conn.close()
        return jsonify(crypto.create_response({'success': True, 'message': 'Device registered', 'session_token': token, 'expires_at': lic[2]}))
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify(crypto.create_error('Server error', 'SERVER_ERROR')), 500

# ==================== VALIDATE API ====================
@app.route('/api/validate', methods=['POST'])
def api_validate():
    try:
        data = request.get_json()
        if not data or 'payload' not in data or 'signature' not in data:
            return jsonify(crypto.create_error('Invalid request', 'INVALID_REQUEST')), 400
        
        if not crypto.verify(data['payload'], data['signature']):
            return jsonify(crypto.create_error('Signature failed', 'TAMPERING_DETECTED')), 403
        
        decrypted = crypto.decrypt(data['payload'])
        validate_data = json.loads(decrypted)
        
        token = validate_data.get('session_token')
        hwid = validate_data.get('hwid')
        
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM sessions WHERE token = ? AND hwid = ? AND is_active = 1", (token, hwid))
        sess = c.fetchone()
        conn.close()
        
        if sess:
            expires = datetime.strptime(sess[4], '%Y-%m-%d %H:%M:%S')
            if expires > datetime.now():
                return jsonify(crypto.create_response({'success': True, 'session_valid': True}))
        
        return jsonify(crypto.create_response({'success': False, 'session_valid': False}))
        
    except Exception as e:
        return jsonify(crypto.create_error('Server error', 'SERVER_ERROR')), 500

# ==================== ADMIN ROUTES ====================
@app.route('/admin')
def admin_login():
    if 'admin' in session:
        return redirect('/admin/dashboard')
    return render_template('admin.html', login=True)

@app.route('/admin/login', methods=['POST'])
def admin_login_post():
    username = request.form.get('username')
    password = request.form.get('password')
    
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session['admin'] = True
        session['admin_name'] = username
        log_admin(username, 'LOGIN', 'Admin logged in', get_ip())
        return redirect('/admin/dashboard')
    
    return render_template('admin.html', login=True, error='Invalid credentials')

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    return render_template('admin.html', login=False)

@app.route('/admin/logout')
@admin_required
def admin_logout():
    log_admin(session.get('admin_name', 'admin'), 'LOGOUT', 'Admin logged out', get_ip())
    session.clear()
    return redirect('/admin')

# ==================== ADMIN API - GENERATE ====================
@app.route('/api/admin/generate', methods=['POST'])
@admin_required
def admin_generate():
    try:
        data = request.get_json()
        duration_type = data.get('duration_type', 'days')
        duration_value = int(data.get('duration_value', 30))
        max_devices = int(data.get('max_devices', 1))
        notes = data.get('notes', '')
        custom_prefix = data.get('custom_prefix', '')
        
        if custom_prefix:
            key = custom_prefix.upper() + "-" + "-".join(secrets.token_hex(2).upper() for _ in range(3))
        else:
            key = gen_key()
        
        if duration_type == 'hours':
            expiry = datetime.now() + timedelta(hours=duration_value)
        elif duration_type == 'days':
            expiry = datetime.now() + timedelta(days=duration_value)
        elif duration_type == 'weeks':
            expiry = datetime.now() + timedelta(weeks=duration_value)
        elif duration_type == 'months':
            expiry = datetime.now() + timedelta(days=duration_value * 30)
        elif duration_type == 'years':
            expiry = datetime.now() + timedelta(days=duration_value * 365)
        elif duration_type == 'lifetime':
            expiry = datetime.now() + timedelta(days=36500)
        else:
            expiry = datetime.now() + timedelta(days=30)
        
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO licenses (license_key, is_active, expires_at, max_devices, notes, created_at, duration_type, duration_value) VALUES (?,?,?,?,?,?,?,?)",
                  (key, 1, expiry.strftime('%Y-%m-%d %H:%M:%S'), max_devices, notes, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), duration_type, duration_value))
        conn.commit()
        conn.close()
        
        log_admin(session.get('admin_name', 'admin'), 'GENERATE_KEY', f'Generated: {key}', get_ip())
        
        return jsonify({
            'success': True,
            'key': key,
            'expires': expiry.strftime('%Y-%m-%d %H:%M:%S'),
            'duration': f'{duration_value} {duration_type}',
            'max_devices': max_devices
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ==================== ADMIN API - BULK ====================
@app.route('/api/admin/bulk-generate', methods=['POST'])
@admin_required
def admin_bulk_generate():
    try:
        data = request.get_json()
        count = min(int(data.get('count', 10)), 100)
        duration_type = data.get('duration_type', 'days')
        duration_value = int(data.get('duration_value', 30))
        max_devices = int(data.get('max_devices', 1))
        custom_prefix = data.get('custom_prefix', '')
        
        keys = []
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        
        for _ in range(count):
            if custom_prefix:
                key = custom_prefix.upper() + "-" + "-".join(secrets.token_hex(2).upper() for _ in range(3))
            else:
                key = gen_key()
            
            if duration_type == 'hours':
                expiry = datetime.now() + timedelta(hours=duration_value)
            elif duration_type == 'days':
                expiry = datetime.now() + timedelta(days=duration_value)
            elif duration_type == 'weeks':
                expiry = datetime.now() + timedelta(weeks=duration_value)
            elif duration_type == 'months':
                expiry = datetime.now() + timedelta(days=duration_value * 30)
            elif duration_type == 'lifetime':
                expiry = datetime.now() + timedelta(days=36500)
            else:
                expiry = datetime.now() + timedelta(days=30)
            
            c.execute("INSERT INTO licenses (license_key, is_active, expires_at, max_devices, created_at, duration_type, duration_value) VALUES (?,?,?,?,?,?,?)",
                      (key, 1, expiry.strftime('%Y-%m-%d %H:%M:%S'), max_devices, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), duration_type, duration_value))
            keys.append({'key': key, 'expires': expiry.strftime('%Y-%m-%d %H:%M:%S')})
        
        conn.commit()
        conn.close()
        
        log_admin(session.get('admin_name', 'admin'), 'BULK_GENERATE', f'Generated {count} keys', get_ip())
        
        return jsonify({'success': True, 'keys': keys})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ==================== ADMIN API - STATS ====================
@app.route('/api/admin/stats')
@admin_required
def admin_stats():
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    
    stats = {}
    
    c.execute("SELECT COUNT(*) FROM licenses")
    stats['total_keys'] = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM licenses WHERE is_active = 1")
    stats['active_keys'] = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM devices")
    stats['total_devices'] = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM logs WHERE success = 1")
    stats['total_logins'] = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM logs WHERE success = 0")
    stats['failed_logins'] = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM sessions WHERE is_active = 1")
    stats['active_sessions'] = c.fetchone()[0]
    
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute("SELECT COUNT(*) FROM devices WHERE registered_at LIKE ?", (today + '%',))
    stats['today_devices'] = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM logs WHERE success = 1 AND time LIKE ?", (today + '%',))
    stats['today_logins'] = c.fetchone()[0]
    
    conn.close()
    return jsonify(stats)

# ==================== ADMIN API - KEYS ====================
@app.route('/api/admin/keys')
@admin_required
def admin_keys():
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT l.*, COUNT(d.hwid) as device_count 
        FROM licenses l 
        LEFT JOIN devices d ON l.license_key = d.license_key 
        GROUP BY l.license_key 
        ORDER BY l.created_at DESC
    """)
    keys = c.fetchall()
    conn.close()
    
    key_list = []
    for k in keys:
        key_list.append({
            'key': k[0],
            'active': k[1],
            'expires': k[2],
            'max_devices': k[3],
            'notes': k[4],
            'created': k[5],
            'duration_type': k[7] if len(k) > 7 else 'days',
            'duration_value': k[8] if len(k) > 8 else 30,
            'device_count': k[9] if len(k) > 9 else 0
        })
    
    return jsonify({'keys': key_list})

# ==================== ADMIN API - DEVICES ====================
@app.route('/api/admin/devices')
@admin_required
def admin_devices():
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM devices ORDER BY last_login DESC")
    devices = c.fetchall()
    conn.close()
    
    device_list = []
    for d in devices:
        device_list.append({
            'hwid': d[0],
            'license_key': d[1],
            'device_name': d[2],
            'android_version': d[3],
            'device_model': d[4],
            'ip': d[5],
            'country': d[6],
            'registered': d[7],
            'last_login': d[8],
            'login_count': d[9]
        })
    
    return jsonify({'devices': device_list})

# ==================== ADMIN API - LOGS ====================
@app.route('/api/admin/logs')
@admin_required
def admin_logs():
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM logs ORDER BY time DESC LIMIT 500")
    logs = c.fetchall()
    conn.close()
    
    log_list = []
    for l in logs:
        log_list.append({
            'license_key': l[1],
            'hwid': l[2],
            'ip': l[3],
            'user_agent': l[4],
            'success': l[5],
            'message': l[6],
            'response_time': l[7],
            'time': l[8]
        })
    
    return jsonify({'logs': log_list})

# ==================== ADMIN API - DELETE ====================
@app.route('/api/admin/delete-key', methods=['POST'])
@admin_required
def admin_delete_key():
    data = request.get_json()
    key = data.get('key')
    
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM licenses WHERE license_key = ?", (key,))
    c.execute("DELETE FROM devices WHERE license_key = ?", (key,))
    conn.commit()
    conn.close()
    
    log_admin(session.get('admin_name', 'admin'), 'DELETE_KEY', f'Deleted: {key}', get_ip())
    return jsonify({'success': True})

# ==================== ADMIN API - TOGGLE ====================
@app.route('/api/admin/toggle-key', methods=['POST'])
@admin_required
def admin_toggle_key():
    data = request.get_json()
    key = data.get('key')
    active = data.get('active')
    
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("UPDATE licenses SET is_active = ? WHERE license_key = ?", (active, key))
    conn.commit()
    conn.close()
    
    log_admin(session.get('admin_name', 'admin'), 'TOGGLE_KEY', f'Toggled {key}', get_ip())
    return jsonify({'success': True})

# ==================== HEALTH ====================
@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def not_found(e):
    return jsonify(crypto.create_error('Not found', 'NOT_FOUND')), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify(crypto.create_error('Server error', 'SERVER_ERROR')), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
