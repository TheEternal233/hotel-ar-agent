"""酒店应收会计 AI 智能体系统 - 工具注册与配置"""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")

ALL_TOOLS = []

def register_tool(tool):
    ALL_TOOLS.append(tool)
    return tool