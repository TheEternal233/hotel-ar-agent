from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os

load_dotenv()

def get_llm():
    api_key=os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("please input api_key")
    return ChatOpenAI(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com/v1",
        api_key=api_key,
        temperature=0,
    )