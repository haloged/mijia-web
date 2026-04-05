import os
import sys
import re
import time
import subprocess
import threading
from flask import request, jsonify, session, redirect, url_for, render_template

# ================= 登录状态管理 =================
login_state = {
    'status': 'idle',   # idle, starting, ready, waiting, success, error
    'qr_url': None,
    'msg': '',
    'pid': None
}

def monitor_login_process(proc):
    """后台线程：实时捕获子进程输出并更新状态"""
    url_pattern = re.compile(r'(https?://[^\s\'\"<>]+)')
    
    print("🔄 [线程启动] 开始监控登录进程...")
    try:
        # 逐行读取输出（阻塞但安全）
        for line_bytes in proc.stdout:
            # 1. 安全解码（彻底避免 utf-8/gbk 冲突）
            text = line_bytes.decode('utf-8', errors='replace').strip()
            if not text: continue
            
            print(f"📤 [Worker] {text}")  # 终端实时打印调试信息

            # 2. 提取二维码链接
            if login_state['status'] in ('starting', 'ready'):
                match = url_pattern.search(text)
                if match:
                    login_state['qr_url'] = match.group(1)
                    login_state['status'] = 'waiting'
                    login_state['msg'] = '已生成，请扫码'
                    print(f"✅ [Worker] 提取到二维码: {login_state['qr_url']}")

            # 3. 检测登录成功
            if '登录成功' in text or 'Login_SUCCESS' in text:
                login_state['status'] = 'success'
                login_state['msg'] = '登录成功，正在跳转...'
                print("🎉 [Worker] 登录成功！")
                # 清除旧 API 实例，强制重载新 Token
                if hasattr(app, 'mijia'):
                    del app.mijia
                break
                
            # 4. 检测登录失败
            if '失败' in text or 'error' in text.lower() or 'Exception' in text:
                login_state['status'] = 'error'
                login_state['msg'] = text
                print(f"❌ [Worker] 登录失败: {text}")
                break
                
    except Exception as e:
        login_state['status'] = 'error'
        login_state['msg'] = f"监控线程异常: {str(e)}"
        print(f"💥 [Worker] 线程异常: {e}")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/api/login/start', methods=['POST'])
def start_login():
    """启动登录子进程"""
    # 防止重复点击
    if login_state['status'] in ('starting', 'ready', 'waiting'):
        return jsonify({'success': True, 'msg': '登录已在进行中'})

    # 重置状态
    login_state.update({'status': 'starting', 'qr_url': None, 'msg': '正在初始化...', 'pid': None})

    # 构造命令行（直接内联执行，无需额外文件）
    cmd = [sys.executable, '-c', 'from mijiaAPI import mijiaAPI; mijiaAPI().login()']
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'  # 关键：强制实时输出 print

    try:
        # 启动子进程
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, text=False  # 二进制模式读取
        )
        login_state['pid'] = proc.pid
        print(f"🚀 [主进程] 已启动登录子进程 PID: {proc.pid}")

        # 启动监控线程
        threading.Thread(target=monitor_login_process, args=(proc,), daemon=True).start()
        return jsonify({'success': True})
    except Exception as e:
        login_state['status'] = 'error'
        login_state['msg'] = str(e)
        return jsonify({'success': False, 'msg': str(e)}), 500

@app.route('/api/login/status')
def login_status():
    return jsonify(login_state)