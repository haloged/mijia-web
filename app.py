import os
import sys
import time
import json
import threading
import re
from datetime import datetime, timedelta
from urllib import parse
from pathlib import Path
from functools import wraps
from typing import Optional

import requests
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

from mijiaAPI import mijiaAPI, mijiaDevice
from mijiaAPI.errors import LoginError

# ================= Flask 初始化 =================
app = Flask(__name__)

# 🔑 强制设置 secret_key，避免 session 崩溃
app.secret_key = os.environ.get('SECRET_KEY', 'mijia-web-secure-key-change-in-prod-2026')
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# ================= 非阻塞 Web 登录管理器 =================
class WebLoginManager:
    def __init__(self, auth_path: Optional[str] = None):
        self.lock = threading.Lock()
        self.auth_path = Path(auth_path) if auth_path else Path.home() / ".config" / "mijia-api" / "auth.json"
        # 仅存储可 JSON 序列化的状态
        self.state = {"status": "idle", "qr_url": None, "msg": ""}
        # 内部私有状态（不暴露给前端）
        self._session = None
        self._lp_url = None
        self._headers = None
        self._start_time = 0

    def _ensure_auth_dir(self) -> bool:
        try:
            self.auth_path.parent.mkdir(parents=True, exist_ok=True)
            test_file = self.auth_path.parent / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            return True
        except Exception as e:
            print(f"⚠️ 认证目录不可写: {self.auth_path.parent} | {e}")
            return False

    def start(self, api: mijiaAPI) -> dict:
        with self.lock:
            if self.state["status"] in ("ready", "waiting"):
                return self._safe_response()
            
            if not self._ensure_auth_dir():
                self.state.update({"status": "error", "msg": f"认证目录不可写: {self.auth_path.parent}"})
                return self._safe_response()
            
            try:
                loc = api._get_location()
                if loc.get("code") == 0 and loc.get("message") == "刷新Token成功":
                    api._save_auth_data()
                    self.state.update({"status": "success", "msg": "Token有效，已自动登录"})
                    print("✅ Token已存在，自动登录成功")
                    return self._safe_response()

                loc.update({
                    "theme": "", "bizDeviceType": "", "_hasLogo": "false",
                    "_qrsize": "240", "_dc": str(int(time.time() * 1000)),
                })
                url = api.login_url + "?" + parse.urlencode(loc)
                headers = {
                    "User-Agent": api.user_agent,
                    "Accept-Encoding": "gzip",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Connection": "keep-alive",
                }
                ret = requests.get(url, headers=headers)
                login_data = api._handle_ret(ret)

                # 保存内部会话状态
                self._session = requests.Session()
                self._lp_url = login_data["lp"]
                self._headers = headers
                self._start_time = time.time()

                self.state.update({
                    "status": "waiting",
                    "msg": "请打开手机米家APP扫码",
                    "qr_url": login_data["qr"]
                })
                print("📱 二维码已生成，等待扫码...")
            except Exception as e:
                print(f"❌ 启动登录失败: {e}")
                self.state.update({"status": "error", "msg": f"启动失败: {str(e)}"})
            
            return self._safe_response()

    def check(self, api: mijiaAPI) -> dict:
        with self.lock:
            if self.state["status"] != "waiting":
                return self._safe_response()

            # 120秒超时保护
            if time.time() - self._start_time > 120:
                self.state.update({"status": "error", "msg": "二维码已过期 (120s)"})
                return self._safe_response()

            try:
                # 短超时轮询（3秒），未扫码时服务器会阻塞并触发 Timeout
                ret = self._session.get(self._lp_url, headers=self._headers, timeout=3)
                lp_data = api._handle_ret(ret)

                # 扫码成功！提取核心凭证
                for key in ["psecurity", "nonce", "ssecurity", "passToken", "userId", "cUserId"]:
                    api.auth_data[key] = lp_data[key]
                
                # 执行 callback 获取 serviceToken 等 cookies
                self._session.get(lp_data["location"], headers=self._headers)
                cookies = self._session.cookies.get_dict()
                api.auth_data.update(cookies)
                api.auth_data.update({
                    "expireTime": int((datetime.now() + timedelta(days=30)).timestamp() * 1000),
                    "ua": api.user_agent,
                })
                
                # 🔑 关键：显式保存文件 & 重载 Session
                api._save_auth_data()
                api._init_session()
                print("✅ 扫码成功，Token已保存并生效")
                
                self.state.update({"status": "success", "msg": "登录成功"})
                self._reset_internal()
                
            except requests.exceptions.Timeout:
                pass  # 正常等待中
            except Exception as e:
                print(f"❌ 轮询异常: {e}")
                self.state.update({"status": "error", "msg": f"轮询异常: {str(e)}"})
                self._reset_internal()
                
            return self._safe_response()

    def manual_verify(self, api: mijiaAPI) -> dict:
        with self.lock:
            if self.auth_path.exists():
                try:
                    api._init_session()
                    api.get_homes_list()
                    self.state.update({"status": "success", "msg": "手动验证成功"})
                    return self._safe_response()
                except Exception:
                    pass
            self.state.update({"status": "error", "msg": "验证失败：未检测到有效认证文件"})
            return self._safe_response()

    def reset(self):
        with self.lock:
            self.state = {"status": "idle", "qr_url": None, "msg": ""}
            self._reset_internal()

    def _reset_internal(self):
        self._session = None
        self._lp_url = None
        self._headers = None
        self._start_time = 0

    def _safe_response(self) -> dict:
        """仅返回 JSON 可序列化的纯文本字段"""
        return {
            "status": self.state["status"],
            "qr_url": self.state["qr_url"],
            "msg": self.state["msg"],
            "auth_path": str(self.auth_path)
        }

login_mgr = WebLoginManager()

# ================= 辅助函数 =================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def get_api() -> mijiaAPI:
    if not hasattr(app, 'mijia'):
        app.mijia = mijiaAPI()
    return app.mijia

# ================= 路由 =================
@app.route('/login')
def login():
    if session.get('logged_in'):
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/api/login/start', methods=['POST'])
def api_login_start():
    api = get_api()
    result = login_mgr.start(api)
    if result["status"] == "success":
        session['logged_in'] = True
        if hasattr(app, 'mijia'): del app.mijia
    return jsonify(result)

@app.route('/api/login/status')
def api_login_status():
    api = get_api()
    result = login_mgr.check(api)
    if result["status"] == "success":
        session['logged_in'] = True
        if hasattr(app, 'mijia'): del app.mijia
        login_mgr.reset()
    return jsonify(result)

@app.route('/api/login/verify', methods=['POST'])
def api_login_verify():
    api = get_api()
    result = login_mgr.manual_verify(api)
    if result["status"] == "success":
        session['logged_in'] = True
        if hasattr(app, 'mijia'): del app.mijia
        login_mgr.reset()
    return jsonify(result)

@app.route('/logout')
def logout():
    session.clear()
    login_mgr.reset()
    if hasattr(app, 'mijia'): del app.mijia
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    try:
        api = get_api()
        devices = api.get_devices_list() + api.get_shared_devices_list()
        LIGHT_KEYS = ['light', 'lamp', 'bulb', 'strip', 'candle', 'yeelink', 'philips.light', 'mijia.light']
        filtered = []
        for d in devices:
            model = str(d.get('model', '')).lower()
            if any(k in model for k in LIGHT_KEYS):
                val = d.get('isOnline', d.get('online', d.get('is_online', 0)))
                online = val == 1 if isinstance(val, (int, float)) else str(val).lower() in ('true', '1', 'online')
                filtered.append({
                    'did': d.get('did', ''),
                    'name': d.get('name', d.get('nick_name', '未命名')),
                    'model': d.get('model', ''),
                    'room': d.get('roomname', d.get('room_name', '未分配')),
                    'online': online
                })
        return render_template('index.html', devices=filtered)
    except Exception as e:
        print(f"❌ 首页加载异常: {e}")
        return render_template('index.html', devices=[], error=str(e))

@app.route('/device/<did>')
@login_required
def device_detail(did):
    try:
        api = get_api()
        device = mijiaDevice(api, did=did)
        props = {}
        for p in ['on', 'brightness', 'color_temperature', 'mode']:
            try:
                v = getattr(device, p)
                if v is not None: props[p] = v
            except: pass
        return render_template('device.html', did=did, name=device.name, props=props)
    except Exception as e:
        print(f"❌ 设备页加载异常: {e}")
        return render_template('device.html', did=did, name="未知设备", props={}, error=str(e))

@app.route('/api/device/<did>/prop', methods=['POST'])
@login_required
def set_property(did):
    try:
        data = request.json
        prop, value = data.get('prop'), data.get('value')
        if not prop or value is None:
            return jsonify({'error': '缺少参数'}), 400
        if prop in ('brightness', 'bright'): value = max(1, min(100, int(value)))
        elif prop in ('color_temperature', 'ct', 'color_temp'): value = int(value)
        device = mijiaDevice(get_api(), did=did)
        setattr(device, prop, value)
        return jsonify({'success': True, 'prop': prop, 'value': getattr(device, prop, value)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ================= 启动入口 =================
if __name__ == '__main__':
    print("="*50)
    print("🏠 米家 Web 控制台 v0.3.3")
    print("🌐 访问: http://localhost:5000")
    print("="*50)
    app.run(host='0.0.0.0', port=5000, debug=True)