import sys
import re
import os
import json
import random
import time

# 添加项目根目录到 Python 搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils.config import llm_client, questions_collection

def get_questions_by_topic(knowledge_point: str, count: int = 1, exclude_ids: list = None) -> list:
    """从题库中按知识点抽取题目，并排除已做题目"""
    exclude_ids = exclude_ids or []
    try:
        all_questions = questions_collection.get()
        filtered = []
        for idx, meta in enumerate(all_questions["metadatas"]):
            if meta.get("knowledge_point") == knowledge_point:
                q_id = all_questions["ids"][idx]
                if q_id not in exclude_ids:
                    filtered.append({
                        "q_id": q_id,
                        "knowledge_point": knowledge_point,
                        "question_text": all_questions["documents"][idx],
                        "starter_code": meta.get("starter_code", ""),
                        "solution_code": meta.get("solution_code", ""),
                        "test_cases": meta.get("test_cases", [])
                    })
        random.shuffle(filtered)
        return filtered[:count]
    except Exception as e:
        print(f"❌ 从题库抽取失败: {e}")
        return []

def generate_question_with_llm(knowledge_point: str):
    """调用大模型生成一道关于指定知识点的编程题目"""
    try:
        question_types = [
            "基础语法练习",
            "实际应用场景",
            "边界条件测试",
            "算法思维训练",
            "代码优化挑战",
            "综合应用题",
            "错误排查题",
            "逻辑推理题"
        ]
        difficulty_levels = ["入门", "基础", "中等", "进阶"]
        random_type = random.choice(question_types)
        random_difficulty = random.choice(difficulty_levels)
        
        prompt = f"""
你是一位专业的Python编程导师，请生成一道关于【{knowledge_point}】的编程练习题。

题目类型：{random_type}
难度级别：{random_difficulty}

要求：
1. 题目要考察该知识点的核心用法，难度适中
2. 题目描述要清晰明确，包含具体的输入输出要求
3. 包含完整的题目描述、starter_code（骨架代码）、solution_code（参考解答）和 test_cases（测试用例）
4. 输出必须是纯JSON格式，不要包含markdown代码块标记
5. 确保题目内容与之前生成的题目不同，避免重复

JSON格式要求：
{{
    "question_text": "题目描述",
    "starter_code": "def solution():\\n    pass",
    "solution_code": "def solution():\\n    # 完整解答代码",
    "test_cases": [{{"input": "输入", "expected": "期望输出"}}]
}}

随机种子：{random.randint(1000000, 9999999)}
"""
        response = llm_client.chat.completions.create(
            model="Qwen/Qwen2.5-72B-Instruct",
            messages=[
                {"role": "system", "content": "你是一位专业的Python编程教育专家，擅长生成高质量、多样化的编程练习题。每次生成的题目都要与之前不同。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.85,
            max_tokens=1024
        )

    # 解析大模型响应    
        content = response.choices[0].message.content.strip()
        print(f"📤 大模型原始响应 (前500字符): {content[:500]}")
        # 清理 markdown 标记
        content = re.sub(r'^```json\s*', '', content)
        content = re.sub(r'\s*```$', '', content)
        content = re.sub(r'^```\s*', '', content)
        
        try:
            result = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"❌ JSON解析失败: {e}")
            print(f"📄 原始内容: {content}")
            
            try:
                # 尝试用正则提取 JSON 部分
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    fixed_content = match.group(0)
                    print(f"🔧 尝试提取JSON部分: {fixed_content[:200]}...")
                    result = json.loads(fixed_content)
                else:
                    raise
            except Exception as e2:
                print(f"❌ 二次解析也失败: {e2}")
                return None
        
        q_id = f"llm_{knowledge_point}_{random.randint(100000, 999999)}_{int(time.time())}"
        
        return {
            "q_id": q_id,
            "knowledge_point": knowledge_point,
            "question_text": result.get("question_text", f"请编写一个Python程序，展示【{knowledge_point}】的核心语法。"),
            "starter_code": result.get("starter_code", "def solution():\n    # 请在这里编写你的代码\n    pass"),
            "solution_code": result.get("solution_code", "def solution():\n    pass"),
            "test_cases": result.get("test_cases", [])
        }
        
    except Exception as e:
        print(f"❌ 大模型生成题目失败: {e}")
        return None


def get_or_generate_questions(knowledge_point: str, count: int = 1, exclude_ids: list = None):
    exclude_ids = exclude_ids or []
    questions = []
    
    # 1. 尝试从本地库抽取
    existing_qs = get_questions_by_topic(knowledge_point, count=count, exclude_ids=exclude_ids)
    if existing_qs:
        questions.extend(existing_qs)
        
    # 2. 如果不足则实时生成
    if len(questions) < count:
        remaining = count - len(questions)
        for _ in range(remaining):
            new_q = generate_question_with_llm(knowledge_point)
            if new_q and new_q["q_id"] not in exclude_ids:
                questions.append(new_q)
        
    return questions