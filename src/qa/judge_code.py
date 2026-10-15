import sys
import os
import json
# 添加项目根目录到 Python 搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils.config import llm_client

def judge_user_code(user_code: str, solution_code: str, test_cases: list, knowledge_point: str = "未分类") -> dict:
    """
    调用 LLM 判断用户代码是否正确。
    返回: {
        "is_correct": bool,
        "error_type": str,  # "语法错误" | "逻辑错误" | "索引越界" | "其他" | None
        "feedback": str
    }
    """
    # 将测试用例转换为易读的字符串
    test_cases_str = json.dumps(test_cases, ensure_ascii=False, indent=2)
    
    # 构造评判 Prompt
    prompt = f"""
你是一位严谨的 Python 编程导师。请仔细评判用户的代码是否与标准答案在逻辑上等价，并能否通过给出的测试用例。

【当前知识点】: {knowledge_point}

【标准参考答案】:
```python
{solution_code}

```

【用户提交代码】:

```python
{user_code}

```

【预期的测试用例】:

```json
{test_cases_str}

```

【评判规则】:

1. 逻辑等价性：用户的函数名/类名或实现方式可能与标准答案不同，但只要能正确实现题目意图、逻辑正确、且能通过测试用例，即视为正确。
2. 严格分类：如果代码错误，请在 "语法错误"、"逻辑错误"、"索引越界"、"其他" 这四个标签中选择一个最贴切的填入 error_type。如果完全正确，error_type 必须为 null。
3. 导师反馈：在 feedback 中用简练的语言指出用户的亮点或错误原因，如果错误，请给出修改建议（不要直接给答案，引导其思考）。

请严格以下列 JSON 格式输出，不要包含任何多余的markdown标记或说明文字：
{{
"is_correct": true/false,
"error_type": "语法错误" / "逻辑错误" / "索引越界" / "其他" / null,
"feedback": "具体的导师评语与反馈"
}}
"""


    try:
        # 调用 SiliconFlow 接口进行评判
        response = llm_client.chat.completions.create(
            model="Qwen/Qwen2.5-72B-Instruct",  # 保持与出题引擎一致的高质量模型
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,  # 降低随机性，保证评判标准客观稳定
            response_format={"type": "json_object"}  # 强制 JSON 输出
        )
        
        raw_content = response.choices[0].message.content
        result = json.loads(raw_content)
        return result

    except Exception as e:
        print(f"❌ 代码评判执行失败: {e}")
        # 发生异常时的安全兜底返回
        return {
            "is_correct": False,
            "error_type": "其他",
            "feedback": f"评判系统暂时出现异常，请稍后重试。错误信息: {e}"
        }



# ================= 测试入口 =================

if __name__ == "__main__":
# 模拟一组测试数据
    mock_user_code = "def add(a, b): return a - b"  # 故意写错成减法
    mock_solution = "def add(a, b):\n    return a + b"
    mock_cases = [{"input": [1, 2], "output": 3}]


    print("⏳ 正在模拟评判用户代码...")
    judge_res = judge_user_code(mock_user_code, mock_solution, mock_cases, "基础语法")
    print("\n[评判结果]:")
    print(json.dumps(judge_res, ensure_ascii=False, indent=4))

