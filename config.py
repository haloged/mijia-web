import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-key-change-in-prod')
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    
    # mijia-api 认证文件路径（默认 ~/.config/mijia-api/auth.json）
    MIJIA_AUTH_PATH = os.getenv('MIJIA_AUTH_PATH', None)
    
    # 是否启用调试
    DEBUG = os.getenv('FLASK_DEBUG', 'False') == 'True'