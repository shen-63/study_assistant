from docx import Document

def parse_word(file_path: str) -> dict:
    doc = Document(file_path)
    chunks = []
    current_title = "根目录"
    current_content = []
    
    for para in doc.paragraphs:
        if para.style.name and "Heading" in para.style.name:
            # 如果是标题段落
            if current_content:
                chunks.append({
                    "title_path": current_title,
                    "content": "\n".join(current_content).strip()
                })
                current_content = []
            current_title = para.text.strip()
        else:
            # 如果是普通段落
            if para.text.strip():
                current_content.append(para.text.strip())
    # 保存最后一个块
    if current_content:
        chunks.append({
            "title_path": current_title,
            "content": "\n".join(current_content).strip()
        })
    
    return {
        "doc_id": file_path.split("\\")[-1].replace(".docx", ""),
        "chunks": chunks
    }