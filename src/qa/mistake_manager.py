import sys
import os
import json
import random

# 添加项目根目录到 Python 搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils.config import mistakes_collection

def add_to_mistakes(q_id: str, knowledge_point: str, question_text: str, starter_code: str, solution_code: str, test_cases: list, user_wrong_code: str, ai_feedback: str):
    """
    自动将做错的题目落库到 mistakes_collection 集合中
    """
    # 使用原题目的 ID 作为错题 ID，方便后续定位和删除
    mistake_id = f"mistake_{q_id}"
    # 构建元数据
    metadata = {
        "q_id": q_id,
        "knowledge_point": knowledge_point,
        "starter_code": starter_code if starter_code else "",
        "solution_code": solution_code if solution_code else "",
        "test_cases": json.dumps(test_cases) if isinstance(test_cases, list) else str(test_cases),
        "last_wrong_code": user_wrong_code if user_wrong_code else "",
        "ai_feedback": ai_feedback if ai_feedback else ""
    }
    
    # 因为错题库数量一般不会极其庞大，且我们主要是按标签准确抽取，这里直接用题干的哑向量或空向量简化，
    # 也可以简单为题干算一个 Embedding，方便以后扩展做“同类错题语义推荐”。这里我们直接存入以便后续直接获取。
    try:  # 存入 ChromaDB
        # 为了避免 Embedding 维度冲突，我们跳过 Chroma 的自动生成，
        # 如果需要保留 question_text，我们让它自己算。为了绝对安全，加上重试或简化处理。
        
        mistakes_collection.add(
            documents=[question_text],
            metadatas=[metadata],
            ids=[mistake_id]
        )
        print(f"💾 错题已全自动同步至错题库: {mistake_id} ({knowledge_point})")
    except Exception as e:
        print(f"⚠️ 错题入库失败，可能因为 Embedding 维度冲突，错误信息: {e}")


def get_mistake_question(knowledge_point: str) -> dict:
    """
    根据知识点随机抽取一道历史错题用于重做
    返回: dict（包含核心题目字段）或 None
    """
    try:  # 从 ChromaDB 读取所有错题
        all_mistakes = mistakes_collection.get()
        filtered_mistakes = []
        # 过滤出指定知识点的错题
        for idx, meta in enumerate(all_mistakes["metadatas"]):
            if meta.get("knowledge_point") == knowledge_point:
                filtered_mistakes.append({
                    "q_id": meta.get("q_id"),
                    "question_text": all_mistakes["documents"][idx],
                    "starter_code": meta.get("starter_code"),
                    "solution_code": meta.get("solution_code"),
                    "test_cases": meta.get("test_cases"),
                    "last_wrong_code": meta.get("last_wrong_code"),
                    "ai_feedback": meta.get("ai_feedback"),
                    "is_from_mistake": True  # 标记此题来自错题本
                })
        # 从过滤后的错题中随机抽取一道
        if filtered_mistakes:
            return random.choice(filtered_mistakes)
    except Exception as e:
        print(f"❌ 读取错题库失败: {e}")
        
    return None


def remove_from_mistakes(q_id: str):
    """
    消灭错题：当用户重新做对时，将错题彻底从集合中抹去
    """
    mistake_id = f"mistake_{q_id}"
    try:
        # 检查是否存在，存在则删除
        existing = mistakes_collection.get(ids=[mistake_id])
        if existing and existing["ids"]:
            mistakes_collection.delete(ids=[mistake_id])
            print(f"✨ 恭喜！错题 {mistake_id} 已成功消灭，从错题本中移除！")
    except Exception as e:
        print(f"⚠️ 尝试移除错题时失败: {e}")