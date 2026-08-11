"""酒店应收会计 AI 智能体系统 - 工具注册与配置"""
import os
from dotenv import load_dotenv
from enums.paths import BASE_DIR, CONFIG_DIR

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))