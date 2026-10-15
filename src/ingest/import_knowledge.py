import os
import sys
# 添加项目根目录到 Python 搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import hashlib
from typing import List, Dict
from src.parsers.pdf_parser import parse_pdf
from src.parsers.word_parser import parse_word
from src.utils.text_processor import extract_code_blocks
from src.utils.config import llm_client, knowledge_collection, ALLOWED_TOPICS

# 去重阈值（余弦相似度）
DUPLICATE_THRESHOLD = 0.92

def extract_knowledge_point(title_path: str) -> str:
    """
    从标题路径中提取知识点标签。
    """
    import re
    match = re.search(r'第[一二三四五六七八九十\d]+章\s*(.*)', title_path)
    if match:
        return match.group(1).strip() or "未分类"
    match = re.search(r'\d+\.\d+\s*(.*)', title_path)
    if match:
        return match.group(1).strip() or "未分类"
    return title_path.strip() or "未分类"


def force_add_chunk(content: str, embedding: list, title: str, knowledge_point: str, doc_id: str) -> str:
    """
    物理入库函数：由前端人工裁决确认后，强行将单个块塞入 ChromaDB 向量库
    """
    chunk_id = f"{doc_id}--{title}--{hashlib.md5(content.encode()).hexdigest()[:8]}"
    knowledge_collection.add(
        documents=[content],
        embeddings=[embedding],
        metadatas=[{
            "doc_id": doc_id,
            "title_path": title,
            "knowledge_point": knowledge_point
        }],
        ids=[chunk_id]
    )
    return chunk_id


def import_knowledge(file_path: str, scan_only: bool = False) -> dict:
    """
    导入教材核心逻辑（支持预扫描双模运行）
    
    参数:
      file_path: 文件路径
      scan_only: 是否仅做预扫描。
                 若为 True，无冲突的块会自动入库，而有冲突的块会被拦截并完整返回，由前端人工裁决。
    """
    result = {
        "success": False,
        "chunks_added": 0,
        "duplicates": [],  # 冲突块列表
        "errors": []
    }
    
    # 1. 解析文档
    ext = os.path.splitext(file_path)[-1].lower()
    try:
        if ext == ".pdf":
            parsed = parse_pdf(file_path)
        elif ext in [".docx", ".doc"]:
            parsed = parse_word(file_path)
        else:
            result["errors"].append(f"不支持的文件格式: {ext}")
            return result
    except Exception as e:
        result["errors"].append(f"解析文件失败: {e}")
        return result
        
    doc_id = parsed["doc_id"]
    chunks = parsed["chunks"]
    
    # 2. 逐块进行语义比对与去重判定
    for chunk in chunks:
        title = chunk["title_path"]
        content = chunk["content"]
        
        if not content.strip():
            continue
            
        # 提取或匹配知识点分类
        knowledge_point = "未分类"
        extracted = extract_knowledge_point(title)
        for t in ALLOWED_TOPICS:
            if t in extracted or extracted in t:
                knowledge_point = t
                break
        
        # 生成新块的 Embedding 向量
        try:
            response = llm_client.embeddings.create(
                model="BAAI/bge-m3",
                input=content
            )
            embedding = response.data[0].embedding
        except Exception as e:
            result["errors"].append(f"向量化失败 (标题: {title}): {e}")
            continue
            
        # 在已有库中进行余弦相似度比对（ChromaDB 默认用 L2 距离，但我们初始化时设为了余弦空间 cosine）
        # 余弦相似度 = 1 - 余弦距离
        is_dup = False
        try:
            similar = knowledge_collection.query(
                query_embeddings=[embedding],
                n_results=1
            )
            if similar and similar["distances"] and similar["distances"][0]:
                distance = similar["distances"][0][0]
                similarity = 1.0 - distance  # 计算出相似度
                
                if similarity >= DUPLICATE_THRESHOLD:
                    is_dup = True
                    existing_title = similar["metadatas"][0][0].get("title_path", "未知标题")
                    existing_content = similar["documents"][0][0]
                    
                    # 记录冲突信息（连同 embedding 向量一起返回，方便后续用户同意后直接强制入库，避免重复调 API 算向量）
                    result["duplicates"].append({
                        "content": content,
                        "embedding": embedding,
                        "title_path": title,
                        "knowledge_point": knowledge_point,
                        "doc_id": doc_id,
                        "similar_title": existing_title,
                        "similar_content": existing_content,
                        "similarity": similarity
                    })
                    print(f"⚠️ 预扫描检测到潜在重复: '{title}' 与已有 '{existing_title}' 相似度 {similarity:.4f}")
        except Exception as e:
            result["errors"].append(f"去重查询失败 (标题: {title}): {e}")
            pass
            
        # 3. 执行入库决策
        if not is_dup:
            # 无冲突，直接入库
            try:
                force_add_chunk(content, embedding, title, knowledge_point, doc_id)
                result["chunks_added"] += 1
                print(f"✅ 自动入库成功: {title}")
            except Exception as e:
                result["errors"].append(f"入库失败 (标题: {title}): {e}")
        else:
            # 有冲突
            if not scan_only:
                # 兼容原版逻辑：若未开启预扫描，则直接无脑跳过
                print(f"🤫 已自动跳过重复块: {title}")
            else:
                # 开启预扫描：不执行写入，等前端复审
                print(f"⏳ 冲突块已保留，等待前端复审: {title}")
                
    result["success"] = len(result["errors"]) == 0
    return result