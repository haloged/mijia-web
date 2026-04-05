document.addEventListener('DOMContentLoaded', () => {
    // 1. 初始化 UI 状态
    const powerSwitch = document.getElementById('power-switch');
    const briSlider = document.getElementById('brightness-slider');
    const ctSlider = document.getElementById('ct-slider');
    const powerText = document.getElementById('power-text');
    const statusBadge = document.getElementById('status-badge');

    // 渲染状态
    function updateUI() {
        // 电源
        if (powerSwitch) powerSwitch.checked = currentOn;
        powerText.textContent = currentOn ? '设备已开启' : '设备已关闭';
        powerText.style.color = currentOn ? 'var(--primary)' : 'var(--text-sub)';
        
        // 启用/禁用滑块
        const sliders = [briSlider, ctSlider];
        sliders.forEach(s => {
            if (s) s.disabled = !currentOn;
        });

        // 显示支持的控件区域
        if ('brightness' in initialState) document.getElementById('control-brightness').style.display = 'block';
        if ('color_temperature' in initialState) document.getElementById('control-ct').style.display = 'block';

        // 回显初始值
        if (briSlider && 'brightness' in initialState) {
            briSlider.value = initialState.brightness;
            document.getElementById('brightness-val').textContent = initialState.brightness + '%';
        }
        if (ctSlider && 'color_temperature' in initialState) {
            ctSlider.value = initialState.color_temperature;
            document.getElementById('ct-val').textContent = initialState.color_temperature + 'K';
        }
        
        statusBadge.textContent = '已连接';
        statusBadge.style.background = '#d1fae5';
        statusBadge.style.color = '#065f46';
    }

    updateUI();

    // 2. 发送指令函数
    function sendCommand(prop, value) {
        fetch(`/api/device/${deviceDid}/prop`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({prop, value})
        })
        .then(r => r.json())
        .then(res => {
            if (res.success) {
                showToast('✅ 控制成功');
            } else {
                showToast('❌ ' + res.error, 2000, true);
                // 如果失败，简单刷新一次页面状态以防 UI 漂移
                setTimeout(() => location.reload(), 1000);
            }
        })
        .catch(e => showToast('🌐 网络请求失败'));
    }

    // 3. 绑定开关
    if (powerSwitch) {
        powerSwitch.addEventListener('change', (e) => {
            currentOn = e.target.checked;
            sendCommand('on', currentOn ? 1 : 0);
            updateUI(); // 立即更新 UI 响应
        });
    }

    // 4. 绑定亮度滑块 (防抖)
    if (briSlider) {
        let timeout;
        briSlider.addEventListener('input', (e) => {
            document.getElementById('brightness-val').textContent = e.target.value + '%';
        });
        briSlider.addEventListener('change', (e) => {
            clearTimeout(timeout);
            sendCommand('brightness', parseInt(e.target.value));
        });
    }

    // 5. 绑定色温滑块
    if (ctSlider) {
        ctSlider.addEventListener('input', (e) => {
            document.getElementById('ct-val').textContent = e.target.value + 'K';
        });
        ctSlider.addEventListener('change', (e) => {
            sendCommand('color_temperature', parseInt(e.target.value));
        });
    }

    // 6. 全局快捷场景函数
    window.setScene = function(mode) {
        // 确保灯是开着的
        if (!currentOn) {
            sendCommand('on', 1);
            currentOn = true;
        }
        
        let targetBri, targetCt;
        switch(mode) {
            case 'reading': targetBri = 80; targetCt = 5000; break;
            case 'movie':   targetBri = 20; targetCt = 3000; break;
            case 'night':   targetBri = 10; targetCt = 2700; break;
        }

        if (briSlider && 'brightness' in initialState) {
            briSlider.value = targetBri;
            document.getElementById('brightness-val').textContent = targetBri + '%';
            sendCommand('brightness', targetBri);
        }
        
        // 延迟一点再调色温，体验更好
        setTimeout(() => {
            if (ctSlider && 'color_temperature' in initialState) {
                ctSlider.value = targetCt;
                document.getElementById('ct-val').textContent = targetCt + 'K';
                sendCommand('color_temperature', targetCt);
            }
        }, 200);
    };

    // Toast 提示工具
    function showToast(msg, duration = 1500, isError = false) {
        let t = document.getElementById('toast');
        if (!t) {
            t = document.createElement('div');
            t.id = 'toast';
            t.className = 'toast';
            document.body.appendChild(t);
        }
        t.textContent = msg;
        t.style.background = isError ? '#ef4444' : '#333';
        t.classList.add('show');
        setTimeout(() => t.classList.remove('show'), duration);
    }
});