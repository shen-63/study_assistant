import os
from dotenv import load_dotenv
from openai import OpenAI
import chromadb

load_dotenv()

API_KEY = os.getenv("SILICONFLOW_API_KEY")
if not API_KEY:
    raise ValueError("❌ 请在 .env 中设置 SILICONFLOW_API_KEY")

# SiliconFlow 客户端（兼容 OpenAI）
llm_client = OpenAI(
    api_key=API_KEY,
    base_url="https://api.siliconflow.cn/v1"
)

# ChromaDB 持久化客户端
chroma_client = chromadb.PersistentClient(path="./data/chroma_db")

# 三个集合（物理隔离）
questions_collection = chroma_client.get_or_create_collection(
    name="questions",
    metadata={"hnsw:space": "cosine"}
)
knowledge_collection = chroma_client.get_or_create_collection(
    name="knowledges",
    metadata={"hnsw:space": "cosine"}
)
mistakes_collection = chroma_client.get_or_create_collection(
    name="mistakes",
    metadata={"hnsw:space": "cosine"}
)

# 统一知识点词表（与你的 Excel 保持一致）
ALLOWED_TOPICS = [
    "基础语法", "数据类型", "条件判断", "循环结构",
    "函数定义", "列表推导式", "字典操作", "异常处理"
]

print("✅ 配置加载完成")