import sys
import os
import time

# 添加项目根目录到 Python 搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils.config import llm_client
from src.retrieval.retriever import retrieve_knowledge

def answer_user_question(query: str) -> tuple:
    """
    根据本地知识库检索并回答用户提问
    返回: (answer_markdown, sources_html)
    """
    if not query.strip():
        return "⚠️ 请输入您想了解或查询的 Python 知识点！", ""

    # 1. 前台显式检索：从本地向量库查找与用户提问最相关的 3 个教材片段
    print(f"🔍 正在检索本地知识库: '{query}'...")
    retrieved_chunks = retrieve_knowledge(query=query, top_k=3)
    
    # 设置相似度阈值，只有距离小于这个值的内容才认为是相关的
    # ChromaDB 余弦距离：距离越小越相似，0 表示完全相同，1 表示完全不同
    RELEVANCE_THRESHOLD = 0.6
    
    # 过滤相关的检索结果
    relevant_chunks = [c for c in retrieved_chunks if c.get("distance", 1.0) < RELEVANCE_THRESHOLD]
    
    context_str = ""
    sources_html = "<div style='margin-top: 10px;'>"
    
    if relevant_chunks:
        print(f"✅ 找到 {len(relevant_chunks)} 个相关知识点")
        for idx, c in enumerate(relevant_chunks):
            # 组装给大模型的上下文
            context_str += f"【切片 {idx+1} | 出处: {c['title_path']} | 相似度: {1 - c['distance']:.2%}】\n{c['content']}\n\n"
            # 组装给前端展示的“溯源双显” HTML
            sources_html += f"""
            <div style='background: #f8fafc; border: 1px solid #e2e8f0; padding: 10px; margin-bottom: 8px; border-radius: 6px;'>
                <b style='color: #2563eb; font-size: 13px;'>📍 依据出处 {idx+1}: {c['title_path']} (相关度: {(1 - c['distance'])*100:.0f}%)</b>
                <pre style='white-space: pre-wrap; font-size: 12px; color: #475569; margin: 4px 0 0 0; font-family: Consolas, monospace;'>{c['content']}</pre>
            </div>
            """
        sources_html += "</div>"
    else:
        print(f"❌ 未找到相关知识点 (检索到 {len(retrieved_chunks)} 条，但均低于相关性阈值 {RELEVANCE_THRESHOLD})")
        sources_html = "<p style='color: #64748b; font-size: 13px;'><i>😶 本次查询未在本地知识库中匹配到密切相关的教材原文，以下解答基于大模型专业知识。</i></p>"

    # 2. 构造智能路由 Prompt，引导大模型进行差异化作答
    prompt = f"""
你是一位极具耐心的 Python 编程导师。现在学生向你请教问题：“{query}”。

【本地教材参考原文】
{context_str if context_str else "（向量库中未检索到密切相关的本地教材切片）"}

请遵循以下作答规则：
1. 【相关性判定】：请先判断【本地教材参考原文】与学生问的问题“{query}”是否**真正高度相关**。
2. 【高相关情况】：如果高度相关，请务必以此原文的讲述逻辑、代码风格为主，结合原文为学生系统地解答。
3. 【弱相关或无关情况】：如果原文只是顺带提到了该知识点（例如：学生在问 try-except 基础语法，但原文只是在讲生成器迭代时顺便用到了 try-except 捕获 StopIteration），**千万不要被原文的主题（如生成器、yield）带偏！** 请直接发挥你作为 Python 专家的专业知识，为学生系统、纯粹地讲解“{query}”本身，并可以委婉地指出“虽然本地教材在迭代器章节中用到了该语法，但它的核心原理是...”。
4. 解释时要通俗易懂，结构清晰，多用代码示例。
"""

    max_retries = 3  # 最大重试次数
    retry_delay = 2  # 每次重试等待 2 秒
    
    for attempt in range(max_retries):
        try:
            print(f"🤖 正在请求大模型生成答疑内容 (第 {attempt + 1} 次尝试)...") 
            
            response = llm_client.chat.completions.create(
                model="Qwen/Qwen2.5-72B-Instruct",  
                messages=[
                    {"role": "system", "content": "你是一位极具耐心的 Python 编程导师。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            answer = response.choices[0].message.content
            return answer, sources_html

        except Exception as e:
            # 检查是否是 429 限流报错
            if "429" in str(e) and attempt < max_retries - 1:
                print(f"⚠️ 服务器繁忙(429)，{retry_delay}秒后自动重试...")
                time.sleep(retry_delay)
                continue
                
            # 如果是其他严重错误，或者超过重试次数，则彻底报错
            error_msg = f"❌ 大模型调用失败: {str(e)}"
            print(error_msg) 
            return f"答疑失败：{error_msg}，请检查网络或配置。", sources_html