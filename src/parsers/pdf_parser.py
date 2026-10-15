import fitz
import re

def parse_pdf(file_path: str) -> dict:
    doc = fitz.open(file_path)
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    doc.close()
    
    print("=== PDF 原始文本预览（前500字符）===")
    print(full_text[:500])
    print("======================================\n")
    
    chunks = split_by_headings(full_text)
    return {
        "doc_id": file_path.split("\\")[-1].replace(".pdf", ""),
        "chunks": chunks

    }

def split_by_headings(text: str) -> list:
    """
    按标题切分文本，每个标题（即使无内容）都成为独立块。
    """
    lines = text.splitlines()
    chunks = []
    current_chunk = None  # 格式：{"title_path": str, "content_lines": list}
    
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        
        # 判断是否为标题行
        is_heading = False
        if stripped.startswith("第") or re.match(r'^\d+\.', stripped) or stripped.startswith('#'):
            is_heading = True
        
        print(f"行 {idx+1}: {'[标题]' if is_heading else '[内容]'} -> {stripped[:50]}")
        
        if is_heading:
            # 如果已有当前块，先保存到chunks（无论是否为空）
            if current_chunk is not None:
                content = "\n".join(current_chunk["content_lines"]).strip()
                chunks.append({
                    "title_path": current_chunk["title_path"],
                    "content": content
                })
            # 创建新块
            clean_title = re.sub(r'^#+\s*', '', stripped)
            current_chunk = {
                "title_path": clean_title,
                "content_lines": []
            }
        else:
            # 内容行
            if current_chunk is None:
                # 如果还没有标题，默认为"根目录"
                current_chunk = {
                    "title_path": "根目录",
                    "content_lines": []
                }
            current_chunk["content_lines"].append(stripped)
    
    # 保存最后一个块
    if current_chunk is not None:
        content = "\n".join(current_chunk["content_lines"]).strip()
        chunks.append({
            "title_path": current_chunk["title_path"],
            "content": content
        })
    
    return chunks