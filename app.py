import os
import sys
import json
import random
import time
import gradio as gr

# 添加项目根目录到 Python 搜索路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils.db import init_db, log_performance, get_performance_by_topic, get_weak_topics, get_error_type_distribution, get_completed_q_ids
from src.utils.config import ALLOWED_TOPICS, mistakes_collection
from src.qa.question_generator import get_or_generate_questions
from src.qa.judge_code import judge_user_code
from src.retrieval.retriever import retrieve_knowledge  
from src.qa.knowledge_qa import answer_user_question  
from src.ingest.import_knowledge import import_knowledge, force_add_chunk

# 引入错题管理引擎
from src.qa.mistake_manager import add_to_mistakes, get_mistake_question, remove_from_mistakes

# 初始化数据库
init_db()

# ================= 后端核心交互逻辑 =================

def refresh_stats():
    """获取最新的学情看板数据"""
    md_text = "### 📊 知识点掌握度看板\n"
    for topic in ALLOWED_TOPICS:
        perf = get_performance_by_topic(topic)
        if topic in perf:
            correct = perf[topic]["correct"]
            total = perf[topic]["total"]
            rate = perf[topic]["rate"] * 100
            md_text += f"- **【{topic}】**: 已做 `{total}` 题 | 正确率 `{rate:.1f}%`\n"
        else:
            md_text += f"- **【{topic}】**: `未练习`\n"
            
    md_text += "\n### 🔍 智能薄弱点与核心病因分析\n"
    weak_topics = get_weak_topics(threshold=0.6)
    if not weak_topics:
        md_text += "✨ *太棒了！当前没有任何薄弱知识点（正确率皆在60%以上）。继续保持！*\n"
    else:
        for item in weak_topics:
            if isinstance(item, tuple):
                topic, rate_val = item[0], item[1] * 100
            else:
                topic, rate_val = item, 0.0
            md_text += f"- 📌 **{topic}** (正确率: `{rate_val:.1f}%`)\n"
            err_dist = get_error_type_distribution(topic)
            if err_dist:
                err_details = ", ".join([f"{err}[{count}次]" for err, count in err_dist])
                md_text += f"  - *主要丢分原因*: {err_details}\n"
    return md_text


def handle_get_question(topic, prefer_mistake, history_q_ids):
    """
    终极防重复 & 强鲁棒性出题引擎 (已修正参数并增强防空兜底)
    """
    q = None
    is_from_mistake = False
    
    # 0. 从数据库读取已完成题目 ID，实现跨会话防重复
    completed_ids = get_completed_q_ids(topic)
    current_session_ids = history_q_ids if history_q_ids else []
    all_excluded_ids = list(set(completed_ids + current_session_ids))
    print(f"🔒 防重复题库: 数据库已完成 {len(completed_ids)} 题 | 当前会话 {len(current_session_ids)} 题 | 总计排除 {len(all_excluded_ids)} 题")
    
    # 1. 实时读取 SQLite 正确率
    perf = get_performance_by_topic(topic)
    is_perfect = False
    if perf and topic in perf:
        if perf[topic].get("total", 0) > 0 and perf[topic].get("rate", 0) >= 1.0:
            is_perfect = True
            
    # 2. 路由一：优先抽错题
    if prefer_mistake and not is_perfect:
        print(f"🔄 正在尝试从错题集中检索【{topic}】的错题...")
        try:
            q = get_mistake_question(topic)
            if q:
                is_from_mistake = True
                print(f"🎯 成功捞出历史错题: {q['q_id']}")
        except Exception as e:
            print(f"⚠️ 读取错题库失败，自动切回常规模式: {e}")

    # 3. 路由二：常规 RAG 题库
    if not q:
        if prefer_mistake and is_perfect:
            print(f"✨ 【{topic}】已通关，开启防重复全新练兵模式...")
            
        print(f"🔍 正在从本地知识库检索与【{topic}】相关的教材切片...")
        context_str = ""
        try:
            retrieved_chunks = retrieve_knowledge(query=topic, top_k=2)
            if retrieved_chunks:
                # 随机打乱检索切片增加题目多样性
                random.shuffle(retrieved_chunks)
                context_str = "\n".join([f"【出处: {c['title_path']}】\n{c['content']}" for c in retrieved_chunks])
        except Exception as e:
            print(f"⚠️ 知识库检索失败: {e}")
        
        # 混入时间戳和随机数作为 Prompt 噪声，强力防大模型输出重复题目
        context_str += f"\n[随机种子标记: {random.randint(1000, 9999)} - {time.time()}]"
        
        try:
            print(f"📡 正在请求大模型生成/抽取【{topic}】的题目...")
            # 💡 核心修正：
            # 1. 移除不支持的 context 参数
            # 2. 将 history_q_ids 传给函数的第三个参数 exclude_ids 
            questions = get_or_generate_questions(
                knowledge_point=topic, 
                count=1, 
                exclude_ids=all_excluded_ids
            ) 
            if questions and len(questions) > 0:
                q = questions[0]
        except Exception as e:
            print(f"❌ 实时生成题目时发生异常: {e}")

    # 4. 终极本地防崩溃保底 (防止大模型解析错误、网络超时、格式不兼容等问题导致的报错)
    if not q:
        print("🚨 [出题引擎保底机制触发] 正在生成本地保底题目...")
        q_id = f"local_{topic}_{random.randint(100,999)}"
        q = {
            "q_id": q_id,
            "knowledge_point": topic,
            "question_text": f"请编写一个 Python 程序，展示【{topic}】的核心语法，并用 `print()` 输出验证结果。",
            "starter_code": "def solution():\n    # 请在这里编写你的代码\n    pass",
            "solution_code": "def solution():\n    pass",
            "test_cases": []
        }
        error_html = f"""
        <div style="background-color: #fef2f2 !important; border-left: 5px solid #ef4444 !important; padding: 15px !important; border-radius: 6px !important; margin: 10px 0 !important;">
            <h4 style="color: #991b1b !important; margin: 0 0 4px 0 !important; font-size: 15px !important; font-weight: bold !important;">⚠️ 导师系统提示</h4>
            <p style="color: #7f1d1d !important; margin: 0 !important; font-size: 14px !important;">大模型接口响应异常或超时，系统已自动切换为本地常规保底练习，请在下方作答。</p>
        </div>
        """
        # 如果是本地兜底，history_q_ids 保持不变
        return q["question_text"], q["starter_code"], error_html, q, history_q_ids

    # 5. 提取骨架代码，做好防空处理
    starter_code = q.get("starter_code", "")
    if not starter_code or not starter_code.strip():
        starter_code = "def solution():\n    # 请在这里完善你的代码\n    pass"

    # 6. 渲染前端组件内容 (确保所有传递给 Markdown 组件的都是格式化好的 str)
    if is_from_mistake:
        question_md = f"🔥 **【错题重做强化】** 本题来自您的错题笔记本，请认真审题，消灭它！\n\n### 📝 题目要求：\n{q['question_text']}"
        feedback_display_text = f"""
        <div style="background-color: #fffbeb !important; border-left: 5px solid #f59e0b !important; padding: 15px !important; border-radius: 6px !important; margin: 10px 0 !important; box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;">
            <h4 style="color: #b45309 !important; margin: 0 0 8px 0 !important; font-size: 15px !important; font-weight: bold !important;">💡 历史错误反馈参考</h4>
            <p style="color: #451a03 !important; margin: 0 !important; line-height: 1.6 !important; font-size: 14px !important;">{q.get('ai_feedback', '暂无特定反馈记录')}</p>
        </div>
        """
        if q.get("last_wrong_code"):
            starter_code = q.get("last_wrong_code")
    else:
        prefix = "✨ **【全新挑战】** 已为您加载全新题目，快来练手吧！\n\n" if (prefer_mistake and is_perfect) else ""
        question_md = f"{prefix}### 📝 题目要求：\n{q['question_text']}"
        feedback_display_text = f"""
        <div style="background-color: #ebf5ff !important; border-left: 5px solid #2563eb !important; padding: 15px !important; border-radius: 6px !important; margin: 10px 0 !important; box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;">
            <h4 style="color: #1e3a8a !important; margin: 0 0 8px 0 !important; font-size: 15px !important; font-weight: bold !important;">🤖 AI 导师在线守护中</h4>
            <p style="color: #1e293b !important; margin: 0 !important; line-height: 1.6 !important; font-size: 14px !important;">已经为你锁定 <b>【{topic}】</b> 考点。请在下方“代码输入区”编写解题代码，并点击下方按钮提交批改。</p>
        </div>
        """

    # 7. 更新历史做题 ID
    new_history = history_q_ids if history_q_ids else []
    q_id = q.get("q_id")
    if q_id and q_id not in new_history:
        new_history.append(q_id)

    return question_md, starter_code, feedback_display_text, q, new_history


def handle_submit_code(user_code, current_question, topic):
    """
    升级后的批改函数：支持自动沉淀错题和消灭错题
    """
    if not current_question or not isinstance(current_question, dict) or "solution_code" not in current_question:
        warning_html = f"""
        <div style="background-color: #fef2f2 !important; border-left: 5px solid #ef4444 !important; padding: 12px !important; border-radius: 4px !important;">
            <p style="color: #991b1b !important; margin: 0 !important; font-size: 14px !important;">⚠️ 请先抽取一道题目再提交代码！</p>
        </div>
        """
        return warning_html, refresh_stats()
        
    if not user_code.strip() or "请在这里完善你的代码" in user_code:
        warning_html2 = f"""
        <div style="background-color: #fef2f2 !important; border-left: 5px solid #ef4444 !important; padding: 12px !important; border-radius: 4px !important;">
            <p style="color: #991b1b !important; margin: 0 !important; font-size: 14px !important;">⚠️ 提交的代码不能为空或未作答！</p>
        </div>
        """
        return warning_html2, refresh_stats()
        
    test_cases = current_question.get("test_cases", [])
    if isinstance(test_cases, str):
        try: 
            test_cases = json.loads(test_cases)
        except Exception as e: 
            print(f"⚠️ 解析测试用例 JSON 失败: {e}")
            test_cases = []

    judge_res = judge_user_code(
        user_code=user_code,
        solution_code=current_question["solution_code"],
        test_cases=test_cases
    )
    
    is_correct = bool(judge_res.get("is_correct"))
    error_type = judge_res.get("error_type")
    ai_feedback = judge_res.get("feedback", "")
    
    q_id = current_question.get("q_id", "temp_id")

    try:
        log_performance(
            q_id=q_id,
            knowledge_point=topic,
            is_correct=is_correct,
            error_type=error_type
        )
        print(f"💾 [SQLite] 成功记录答题表现 -> 题号: {q_id} | 结果: {'正确' if is_correct else '错误'}")
    except Exception as db_err:
        print(f"❌ [SQLite] 写入答题历史失败: {db_err}")
    
    if not is_correct:
        try:
            add_to_mistakes(
                q_id=q_id,
                knowledge_point=topic,
                question_text=current_question["question_text"],
                starter_code=current_question.get("starter_code", ""),
                solution_code=current_question["solution_code"],
                test_cases=test_cases,
                user_wrong_code=user_code,
                ai_feedback=ai_feedback
            )
            print(f"📥 [ChromaDB] 错题已入库 -> {q_id}")
        except Exception as chroma_err:
            print(f"⚠️ [ChromaDB] 错题入库失败 (可能网络波动超时): {chroma_err}")
            
        bg_color = "#fef2f2"
        border_color = "#ef4444"
        title_color = "#991b1b"
        text_color = "#7f1d1d"
        status_icon = f"❌ 【回答错误】 (错误类型: {error_type if error_type else '逻辑错误'})"
        archive_tip = "*💾 该错题已被智能错题本自动收录，后续可开启“错题重做”模式专门巩固。*"
    else:
        try:
            remove_from_mistakes(q_id=q_id)
            print(f"🧹 [ChromaDB] 错题已被移除/消灭 -> {q_id}")
        except Exception as chroma_err:
            print(f"⚠️ [ChromaDB] 尝试消灭错题失败 (可能网络波动超时): {chroma_err}")
            
        bg_color = "#f0fdf4"
        border_color = "#22c55e"
        title_color = "#166534"
        text_color = "#14532d"
        status_icon = "✅ 【完全正确！】"
        archive_tip = "*✨ 太棒了！此题解答正确。如果它曾在错题本中，现在已被彻底消灭！*"

    # 精美前端 HTML 强力渲染，覆盖 Gradio 全局浅色字体
    result_html = f"""
    <div style="background-color: {bg_color} !important; border-left: 5px solid {border_color} !important; padding: 15px !important; border-radius: 6px !important; margin: 10px 0 !important; box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;">
        <h3 style="color: {title_color} !important; margin: 0 0 10px 0 !important; font-size: 16px !important; font-weight: bold !important;">{status_icon}</h3>
        <div style="margin-bottom: 12px !important;">
            <strong style="color: #1e293b !important; font-size: 14px !important;">💡 导师详细反馈：</strong>
            <p style="color: {text_color} !important; font-size: 14px !important; margin: 4px 0 0 0 !important; line-height: 1.6 !important; white-space: pre-wrap !important; font-weight: normal !important;">{ai_feedback}</p>
        </div>
        <p style="color: #475569 !important; font-size: 13px !important; margin: 0 !important; font-style: italic !important;">{archive_tip}</p>
    </div>
    """
    return result_html, refresh_stats()


# ================= 知识库维护与人工裁决交互 =================

def handle_knowledge_upload(file_obj):
    """处理前端上传文件：执行预扫描 scan_only=True"""
    if file_obj is None:
        return "⚠️ 请先选择或拖入一个 PDF 或 Docx 文件！", [], gr.update(visible=False), "当前无冲突", "", "", "", 0
    
    file_path = file_obj.name 
    original_name = os.path.basename(file_path)
    
    try:
        res = import_knowledge(file_path, scan_only=True)
        report_md = f"""
### 📊 文件处理报告: `{original_name}`
- **处理状态**: {"✅ 成功" if res["success"] else "⚠️ 部分块处理存在异常"}
- **无冲突块 (已自动入库)**: `{res["chunks_added"]}` 个
- **待人工裁决冲突块**: `{len(res["duplicates"])}` 个
"""
        if res["errors"]:
            report_md += f"\n- **异常提示**: {', '.join(res['errors'])}"
            
        duplicates = res["duplicates"]
        
        if len(duplicates) > 0:
            first_dup = duplicates[0]
            progress_text = f"### ⏳ 正在裁决第 `1/{len(duplicates)}` 个冲突"
            new_text = f"**📌 新上传块标题**: `{first_dup['title_path']}`\n\n```python\n{first_dup['content']}\n```"
            old_text = f"**📌 数据库已有块**: `{first_dup['similar_title']}`\n\n```python\n{first_dup['similar_content']}\n```"
            sim_text = f"### ⚖️ 语义相似度: <span style='color:#ef4444;'>{first_dup['similarity']*100:.1f}%</span>"
            
            return report_md, duplicates, gr.update(visible=True), progress_text, new_text, old_text, sim_text, 0
        else:
            report_md += "\n\n✨ *恭喜！该文档所有知识点均为全新内容，已自动全部安全入库。*"
            return report_md, [], gr.update(visible=False), "当前无冲突", "", "", "", 0
            
    except Exception as e:
        return f"❌ 解析入库失败: {e}", [], gr.update(visible=False), "当前无冲突", "", "", "", 0


def handle_resolve_conflict(action, duplicates, current_index):
    """裁决按钮响应逻辑"""
    if not duplicates or current_index >= len(duplicates):
        return gr.update(visible=False), "🎉 所有冲突块已裁决完毕！", "", "", "", current_index
    
    curr_dup = duplicates[current_index]
    
    if action == "force":
        try:
            force_add_chunk(
                content=curr_dup["content"],
                embedding=curr_dup["embedding"],
                title=curr_dup["title_path"],
                knowledge_point=curr_dup["knowledge_point"],
                doc_id=curr_dup["doc_id"]
            )
            print(f"➡️ 人工裁决：允许强制入库 -> {curr_dup['title_path']}")
        except Exception as e:
            print(f"❌ 强制入库失败: {e}")
            
    next_index = current_index + 1
    
    if next_index >= len(duplicates):
        complete_md = f"### 🎉 裁决全部完成！\n本次上传的所有待审冲突块均已处理。新知识库状态已就绪。"
        return gr.update(visible=False), complete_md, "", "", "", next_index
    else:
        next_dup = duplicates[next_index]
        progress_text = f"### ⏳ 正在裁决第 `{next_index + 1}/{len(duplicates)}` 个冲突"
        new_text = f"**📌 新上传块标题**: `{next_dup['title_path']}`\n\n```python\n{next_dup['content']}\n```"
        old_text = f"**📌 数据库已有块**: `{next_dup['similar_title']}`\n\n```python\n{next_dup['similar_content']}\n```"
        sim_text = f"### ⚖️ 语义相似度: <span style='color:#ef4444;'>{next_dup['similarity']*100:.1f}%</span>"
        
        return gr.update(visible=True), progress_text, new_text, old_text, sim_text, next_index


# ================= Tab 4：错题本静态查询逻辑 =================

def handle_view_mistakes(topic):
    """查询错题本中指定知识点的所有错题，并拼接成精美的 HTML/Markdown 内容"""
    try:
        all_mistakes = mistakes_collection.get()
        filtered = []
        for idx, meta in enumerate(all_mistakes["metadatas"]):
            if meta.get("knowledge_point") == topic:
                filtered.append({
                    "q_id": meta.get("q_id"),
                    "question_text": all_mistakes["documents"][idx],
                    "last_wrong_code": meta.get("last_wrong_code"),
                    "ai_feedback": meta.get("ai_feedback")
                })
        
        if not filtered:
            return f"### 📄 错题本暂无记录\n目前在【{topic}】目录下没有错题记录。说明你掌握得非常棒，请继续保持！"
            
        html_output = f"### 📋 【{topic}】下共计 `{len(filtered)}` 道历史错题：\n\n"
        for idx, item in enumerate(filtered):
            html_output += (
                f"---\n"
                f"#### ❌ 错题 {idx+1} (题ID: {item['q_id']})\n\n"
                f"**❓ 题目要求：**\n{item['question_text']}\n\n"
                f"<details>\n"
                f"<summary><b>🛠️ 查看您当时编写的错误代码 (点击展开)</b></summary>\n\n"
                f"```python\n{item['last_wrong_code']}\n```\n"
                f"</details>\n\n"
                f"<div style='background-color: #fffbeb !important; border-left: 4px solid #f59e0b !important; padding: 12px !important; margin-top: 10px !important; border-radius: 0 6px 6px 0 !important;'>\n"
                f"<b style='color: #b45309 !important;'>💡 AI 导师诊断：</b><br/>\n"
                f"<span style='color: #451a03 !important;'>{item['ai_feedback']}</span>\n"
                f"</div>\n\n"
            )
        return html_output

    except Exception as e:
        return f"❌ 读取错题本出错: {e}"

# ================= Gradio 界面布局 =================

with gr.Blocks(theme=gr.themes.Soft(), title="Python 智能学习助手") as demo:
    current_question_state = gr.State({})  # 存储当前题目状态
    pending_duplicates_state = gr.State([])  # 存储待处理的块列表
    current_dup_index_state = gr.State(0)  # 存储当前处理的块索引
    history_q_ids = gr.State([])  # 存储已做题的 ID 列表
    
    gr.Markdown("# 🐍 Python 智能学习助手")
    
    with gr.Tabs():
        
        # Tab 1：智能刷题
        with gr.Tab("🚀 智能刷题练兵场"):
            with gr.Row():
                # 左侧列：显示学情数据和刷新按钮
                with gr.Column(scale=1):
                    stats_output = gr.Markdown(value=refresh_stats())
                    btn_refresh = gr.Button("🔄 刷新学情数据", variant="secondary")
                # 刷题区域    
                with gr.Column(scale=2):
                    with gr.Row():
                        topic_dropdown = gr.Dropdown(
                            choices=ALLOWED_TOPICS, 
                            label="🎯 选择要练习的 Python 知识点", 
                            value=ALLOWED_TOPICS[0]
                        )
                        btn_get_q = gr.Button("🚀 基于知识库生成/抽取题目", variant="primary")
                    
                    prefer_mistake_checkbox = gr.Checkbox(
                        label="🎯 优先从我的错题集中抽取（错题重做消灭模式）", 
                        value=False
                    )
                    
                    question_display = gr.Markdown("### 📝 题目要求：\n请先选择上方知识点并点击出题按钮。")
                    
                    user_code_input = gr.Code(
                        label="💻 Python 代码输入区", 
                        language="python", 
                        lines=15,
                        value="# 选择左上方知识点并点击出题后，这里会自动生成骨架代码",
                        interactive=True
                    )
                    
                    btn_submit = gr.Button("📤 提交代码由 AI 导师批改", variant="stop")
                    
                    # 💡 初始加载时的展示骨架，这里也全面加上 !important 深度保护色
                    initial_feedback_html = """
                    <div style="background-color: #f1f5f9 !important; border-left: 5px solid #475569 !important; padding: 15px !important; border-radius: 6px !important; margin: 10px 0 !important;">
                        <h4 style="color: #1e293b !important; margin: 0 0 4px 0 !important; font-size: 15px !important; font-weight: bold !important;">🔍 批改与诊断工作台</h4>
                        <p style="color: #475569 !important; margin: 0 !important; font-size: 14px !important; font-weight: normal !important;">等待提交代码...</p>
                    </div>
                    """
                    feedback_display = gr.HTML(value=initial_feedback_html)
                    
        # Tab 2：知识检索答疑
        with gr.Tab("📚 知识库智能检索与答疑"):
            gr.Markdown("### 💡 欢迎进入知识查阅区。在这里你可以输入任何想了解的 Python 概念，系统会优先翻阅本地教材为您解答。")
            
            with gr.Row():
                with gr.Column(scale=3):
                    search_input = gr.Textbox(
                        label="🔍 输入你想查阅或提问的 Python 问题",
                        placeholder="例如：什么是字典的 get() 方法？/ 怎么使用 try-except 捕获异常？",
                        lines=2
                    )
                    
                    gr.Markdown("**🔥 高频高热点一键检索：**")
                    with gr.Row():
                        btn_fast1 = gr.Button("列表推导式语法", variant="secondary", size="sm")
                        btn_fast2 = gr.Button("字典 get 默认值", variant="secondary", size="sm")
                        btn_fast3 = gr.Button("条件判断边界", variant="secondary", size="sm")
                        btn_fast4 = gr.Button("异常处理 try-except", variant="secondary", size="sm")
                        
                    btn_search = gr.Button("📖 翻阅本地教材并让大模型解答", variant="primary")
                
                with gr.Column(scale=4):
                    qa_answer_output = gr.Markdown("### 🤖 导师解答区\n等待您的提问...")
                    gr.Markdown("---")
                    gr.Markdown("### 📍 本地教材原文存证（溯源参考）")
                    qa_source_output = gr.HTML("<p style='color: #475569; font-size: 13px;'><i>等待提问后展示参考依据...</i></p>")

        # Tab 3：知识库管理与人工裁决
        with gr.Tab("📂 知识库维护与人工去重"):
            gr.Markdown("### 🛠️ 知识库增量导入与半自动去重中心")
            
            with gr.Row():
                with gr.Column(scale=1):
                    upload_input = gr.File(
                        label="📤 上传新本地教材/笔记 (支持 .pdf, .docx)", 
                        file_types=[".pdf", ".docx"]
                    )
                    btn_upload = gr.Button("⚡ 开始解析并预扫描去重", variant="primary")
                    upload_status_output = gr.Markdown("### 📋 扫描报告\n等待上传文件并启动扫描...")
                    
                with gr.Column(scale=2):
                    with gr.Group(visible=False) as review_panel:
                        review_title = gr.Markdown("### ⏳ 正在裁决冲突...")
                        
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown("#### 🆕 刚上传的冲突段落内容")
                                new_content_box = gr.Markdown()
                            with gr.Column(scale=1):
                                gr.Markdown("#### 💾 数据库已有的高相似段落")
                                old_content_box = gr.Markdown()
                                
                        similarity_box = gr.Markdown("### ⚖️ 语义相似度:")
                        
                        gr.Markdown("💡 *请选择此处的裁决方案：如果它们属于不同章节的相似讲解，请点击“并入”；如果确系重复，点击“丢弃”。*")
                        with gr.Row():
                            btn_force_import = gr.Button("✅ 允许强制并入知识库", variant="primary")
                            btn_discard_chunk = gr.Button("❌ 确认重复-丢弃该块", variant="stop")

        # Tab 4：错题本查看页
        with gr.Tab("📋 个人错题笔记本"):
            gr.Markdown("### 📚 错题沉淀与自助温习卡片")
            with gr.Row():
                with gr.Column(scale=1):
                    mistake_topic_dropdown = gr.Dropdown(
                        choices=ALLOWED_TOPICS,
                        label="🔍 按知识点过滤错题",
                        value=ALLOWED_TOPICS[0]
                    )
                    btn_load_mistakes = gr.Button("📖 翻开错题本", variant="primary")
                with gr.Column(scale=3):
                    mistakes_display = gr.Markdown("### 📂 错题展示区\n选择左侧知识点并点击“翻开错题本”查看历史错题记录。")


    # ================= 事件绑定 =================
    
    # --- Tab 1 刷题事件 ---
    btn_refresh.click(fn=refresh_stats, outputs=stats_output)
    
    btn_get_q.click( 
        fn=handle_get_question, 
        inputs=[topic_dropdown, prefer_mistake_checkbox, history_q_ids], 
        outputs=[question_display, user_code_input, feedback_display, current_question_state, history_q_ids]
    )
    
    btn_submit.click(
        fn=handle_submit_code,
        inputs=[user_code_input, current_question_state, topic_dropdown],
        outputs=[feedback_display, stats_output]
    )
    
    # --- Tab 2 检索答疑事件 ---
    btn_search.click(
        fn=answer_user_question,
        inputs=[search_input],
        outputs=[qa_answer_output, qa_source_output]
    )
    
    def fast_click_fn(text):
        return text
        
    for btn in [btn_fast1, btn_fast2, btn_fast3, btn_fast4]:
        btn.click(fn=fast_click_fn, inputs=[btn], outputs=[search_input]).then(
            fn=answer_user_question, inputs=[search_input], outputs=[qa_answer_output, qa_source_output]
        )

    # --- Tab 3 知识维护与人工去重事件 ---
    btn_upload.click(
        fn=handle_knowledge_upload,
        inputs=[upload_input],
        outputs=[
            upload_status_output, 
            pending_duplicates_state, 
            review_panel, 
            review_title, 
            new_content_box, 
            old_content_box, 
            similarity_box, 
            current_dup_index_state
        ]
    )
    
    btn_force_import.click(
        fn=lambda dups, idx: handle_resolve_conflict("force", dups, idx),
        inputs=[pending_duplicates_state, current_dup_index_state],
        outputs=[
            review_panel, 
            review_title, 
            new_content_box, 
            old_content_box, 
            similarity_box, 
            current_dup_index_state
        ]
    )
    
    btn_discard_chunk.click(
        fn=lambda dups, idx: handle_resolve_conflict("discard", dups, idx),
        inputs=[pending_duplicates_state, current_dup_index_state],
        outputs=[
            review_panel, 
            review_title, 
            new_content_box, 
            old_content_box, 
            similarity_box, 
            current_dup_index_state
        ]
    )

    # --- Tab 4 错题本事件 ---
    btn_load_mistakes.click(
        fn=handle_view_mistakes,
        inputs=[mistake_topic_dropdown],
        outputs=[mistakes_display]
    )

    # ================= 全局加载事件 =================
    # 🎯 当网页加载或刷新时，自动触发刷新学情数据的函数
    demo.load(
        fn=refresh_stats,
        inputs=[],
        outputs=[stats_output]
    )

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True)