import os
import uuid
import json
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
import chromadb
from chromadb.config import Settings

# ================= 1. 加载环境变量 =================
load_dotenv()
API_KEY = os.getenv("SILICONFLOW_API_KEY")
if not API_KEY:
    raise ValueError("❌ 请在 .env 文件中设置 SILICONFLOW_API_KEY")

# ================= 2. 初始化客户端 =================
# 初始化 SiliconFlow 客户端（兼容OpenAI接口）
client = OpenAI(
    api_key=API_KEY,
    base_url="https://api.siliconflow.cn/v1"
)

# 初始化 ChromaDB（持久化到本地 ./chroma_db 目录）
chroma_client = chromadb.PersistentClient(path="./chroma_db")
# 获取或创建题型库集合（物理隔离）
questions_collection = chroma_client.get_or_create_collection(
    name="questions",
    metadata={"hnsw:space": "cosine"}  # 使用余弦相似度
)

# ================= 3. 定义统一词表与校验 =================
ALLOWED_TOPICS = [
    "基础语法",
    "数据类型",
    "条件判断",
    "循环结构",
    "函数定义",
    "列表推导式",
    "字典操作",
    "异常处理"
]

def validate_topics(df):
    """校验Excel中的知识点是否都在词表内"""
    invalid_topics = set()
    for topic in df["knowledge_point"].dropna().unique():
        if topic not in ALLOWED_TOPICS:
            invalid_topics.add(topic)
    if invalid_topics:
        raise ValueError(f"❌ 发现未授权的知识点标签: {invalid_topics}\n"
                         f"请修改Excel后重试，允许的词表为: {ALLOWED_TOPICS}")
    print("✅ 知识点词表校验通过")

# ================= 4. 向量化与入库函数 =================
def import_questions(excel_path: str):
    """读取Excel并将题目导入ChromaDB"""
    print(f"📂 正在读取文件: {excel_path}")
    df = pd.read_excel(excel_path)
    
    # 必填列检查
    required_cols = ["question_text", "solution_code", "knowledge_point", "difficulty"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"❌ Excel缺少必填列: {col}")
    
    # 填充空值（starter_code 和 test_cases 可选）
    df["starter_code"] = df.get("starter_code", "").fillna("")
    df["test_cases"] = df.get("test_cases", "").fillna("[]")
    
    # 校验词表
    validate_topics(df)
    
    # 批量入库
    total = len(df)
    print(f"📥 准备导入 {total} 道题目...")
    
    for idx, row in df.iterrows():
        # 生成唯一ID
        q_id = f"q_{uuid.uuid4().hex[:8]}"
        
        # 1. 构建文档内容（用于向量化，以题干为核心）
        doc_content = row["question_text"]
        
        # 2. 构建元数据（ChromaDB支持str/int/float/bool，复杂结构转JSON字符串）
        metadata = {
            "knowledge_point": row["knowledge_point"],
            "difficulty": row["difficulty"],
            "starter_code": row["starter_code"],  # 空字符串也允许
            "solution_code": row["solution_code"],
            "test_cases": json.dumps(row["test_cases"])  # 转为JSON字符串存储
        }
        
        # 3. 调用 SiliconFlow 生成向量（Embedding）
        try:
            response = client.embeddings.create(
                model="BAAI/bge-m3",  # 硅基流动上的通用嵌入模型，中英文都支持
                input=doc_content
            )
            embedding = response.data[0].embedding
        except Exception as e:
            print(f"⚠️ 第 {idx+1} 题向量化失败（跳过）: {e}")
            continue
        
        # 4. 存入ChromaDB
        questions_collection.add(
            documents=[doc_content],
            embeddings=[embedding],
            metadatas=[metadata],
            ids=[q_id]
        )
        print(f"✅ [{idx+1}/{total}] 入库成功: {q_id} -> {row['knowledge_point']}")
    
    print(f"🎉 全部导入完成！当前题型库共 {questions_collection.count()} 条记录")

# ================= 5. 执行入口 =================
if __name__ == "__main__":
    # 请确认Excel文件名，如果放在同级目录下直接写文件名即可
    import_questions("seed_questions.xlsx")