import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils.config import llm_client, knowledge_collection

def retrieve_knowledge(query: str, top_k: int = 3) -> list:
    """
    从知识库中检索与查询最相关的内容块。
    返回: list of dict, 每个包含 title_path, content, distance
    """
    if not query.strip():
        return []

    # 1. 将查询转为向量
    try:
        response = llm_client.embeddings.create(
            model="BAAI/bge-m3",
            input=query
        )
        query_embedding = response.data[0].embedding
        
        # 💡 [关键调试代码] 强行打印转换出来的向量维度
        dim = len(query_embedding)
        print(f"📡 [DEBUG] 检索文本: '{query}' | 生成的向量维度为: {dim}")
        
    except Exception as e:
        print(f"❌ 查询向量化失败: {e}")
        return []
    
    # 2. 在知识库中检索
    try:
        results = knowledge_collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
    except Exception as e:
        # 💡 如果因为维度报错，在这里给出最直观的修复指引
        print(f"❌ ChromaDB 检索失败: {e}")
        print("💡 解决方案提示：当前向量库集合创建的维度与你请求的 Embedding 维度不匹配。请尝试清空 chroma 缓存文件夹重新导入数据。")
        return []
    
    # 3. 整理返回结果
    retrieved = []
    if results["documents"] and results["documents"][0]:
        for i, doc in enumerate(results["documents"][0]):
            retrieved.append({
                "title_path": results["metadatas"][0][i].get("title_path", "未知标题"),
                "content": doc,
                "distance": results["distances"][0][i] if "distances" in results else 0
            })
            
    return retrieved