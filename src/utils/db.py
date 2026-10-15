import sqlite3
import os
from datetime import datetime

# 获取当前 db.py 所在的绝对路径
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__)) # src/utils
# 向上退两级到项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))

# 确保 data 文件夹一定存在
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 锁定唯一的数据库文件绝对路径
DB_PATH = os.path.join(DATA_DIR, "study_assistant.db")
print(f"📂 本地 SQLite 数据库路径已被锁定为: {DB_PATH}")

def init_db():
    """初始化数据库，创建 user_performance 表"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()   # 创建游标
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            q_id TEXT NOT NULL,
            knowledge_point TEXT NOT NULL,
            is_correct BOOLEAN NOT NULL,
            error_type TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()   # 提交事务
    conn.close()   # 关闭连接
    print("✅ 数据库初始化完成")

def log_performance(q_id: str, knowledge_point: str, is_correct: bool, error_type: str = None):
    """记录一次答题结果"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO user_performance (q_id, knowledge_point, is_correct, error_type, timestamp)
        VALUES (?, ?, ?, ?, ?)
    ''', (q_id, knowledge_point, is_correct, error_type, datetime.now()))
    conn.commit()
    conn.close()

def get_performance_by_topic(knowledge_point: str = None) -> dict:
    """
    获取各知识点的答题统计。
    如果指定 knowledge_point，只返回该知识点的统计。
    返回: dict { "知识点": {"correct": int, "total": int, "rate": float} }
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if knowledge_point:
        c.execute('''
            SELECT knowledge_point, 
                   SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct,
                   COUNT(*) as total
            FROM user_performance
            WHERE knowledge_point = ?
            GROUP BY knowledge_point
        ''', (knowledge_point,))
    else:
        # 如果没有指定知识点，查询所有知识点的统计
        c.execute('''
            SELECT knowledge_point, 
                   SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct,
                   COUNT(*) as total
            FROM user_performance
            GROUP BY knowledge_point
        ''')
    rows = c.fetchall()
    conn.close()
    
    result = {}
    for row in rows:
        topic, correct, total = row
        result[topic] = {
            "correct": correct,
            "total": total,
            "rate": correct / total if total > 0 else 0.0
        }
    return result

def get_weak_topics(threshold=0.6):
    """
    修复后的薄弱点分析
    """
    import sqlite3
    
    # 直接使用你脚本顶部定义好的 DB_PATH，防止路径混乱
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    weak_topics = []
    try:
        # 严格按知识点聚合计算总数与正确数
        query = """
            SELECT knowledge_point, 
                   SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct_cnt,
                   COUNT(*) as total_cnt
            FROM user_performance
            GROUP BY knowledge_point
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        
        for row in rows:
            topic, correct_cnt, total_cnt = row[0], row[1], row[2]
            if total_cnt > 0:
                rate = correct_cnt / total_cnt
                # 如果正确率低于设定的阈值（例如 60%），则列为薄弱点
                if rate < threshold:
                    weak_topics.append((topic, rate))
                    
        # 按正确率从低到高排序，让最差的排在最前面
        weak_topics.sort(key=lambda x: x[1])
    except Exception as e:
        print(f"❌ 提取薄弱知识点失败: {e}")
    finally:
        conn.close()
        
    return weak_topics

def get_error_type_distribution(knowledge_point: str) -> list:
    """
    获取某个知识点下用户的错误类型频次分布（按频次从高到低排序）
    返回: [("逻辑错误", 3), ("语法错误", 1)]
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT error_type, COUNT(*) as count
        FROM user_performance
        WHERE knowledge_point = ? AND is_correct = 0 AND error_type IS NOT NULL
        GROUP BY error_type
        ORDER BY count DESC
    ''', (knowledge_point,))
    rows = c.fetchall()
    conn.close()
    return rows


def get_completed_q_ids(knowledge_point: str = None) -> list:
    """
    获取用户已经完成过的题目 ID 列表，用于防重复出题
    如果指定 knowledge_point，只返回该知识点下的已完成题目 ID
    返回: ["q_id1", "q_id2", ...]
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if knowledge_point:
        c.execute('''
            SELECT DISTINCT q_id
            FROM user_performance
            WHERE knowledge_point = ?
        ''', (knowledge_point,))
    else:
        c.execute('''
            SELECT DISTINCT q_id
            FROM user_performance
        ''')
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]