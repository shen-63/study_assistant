import re

def extract_code_blocks(text: str) -> list:
    """
    从文本中提取所有 Python 代码块，返回混合块列表。
    每个块为 {'type': 'code'|'text', 'content': str}
    """
    blocks = []
    
    # 1. 提取 ```python ... ``` 围栏块
    pattern_fenced = r"```python\s*(.*?)```"
    matches = re.findall(pattern_fenced, text, re.DOTALL)
    if matches:
        for code in matches:
            blocks.append({"type": "code", "content": code})
        text = re.sub(pattern_fenced, "", text, flags=re.DOTALL)
    
    # 2. 提取连续缩进块（至少4空格或1个tab，且连续≥3行）
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^[ \t]{4,}", line) or re.match(r"^\t", line):
            code_lines = []
            while i < len(lines) and (re.match(r"^[ \t]{4,}", lines[i]) or re.match(r"^\t", lines[i])):
                code_lines.append(lines[i])
                i += 1
            if len(code_lines) >= 3:
                blocks.append({"type": "code", "content": "\n".join(code_lines)})
                continue
        # 非缩进行作为普通文字
        blocks.append({"type": "text", "content": line})
        i += 1
    
    return blocks