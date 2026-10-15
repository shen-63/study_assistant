from src.parsers.pdf_parser import parse_pdf
from src.parsers.word_parser import parse_word
from src.utils.text_processor import extract_code_blocks

# 测试代码块提取函数
sample = """
```python
def greet(name):
    print(f"Hello, {name}")
```
普通文字内容。
缩进代码行
第二行缩进
"""
blocks = extract_code_blocks(sample)
print("=== 代码块提取测试 ===")
for b in blocks:
    print(f"{b['type']}: {b['content'][:60]}...")

# 测试 PDF 解析
print("\n=== PDF 解析测试 ===")
try:
    pdf_result = parse_pdf("data/raw/test.pdf")
    print(f"文档ID: {pdf_result['doc_id']}")
    print(f"共 {len(pdf_result['chunks'])} 个块")
    for i, chunk in enumerate(pdf_result["chunks"]):
        print(f"\n块{i+1}: {chunk['title_path']}")

    # 打印前 100 个字符
    print(f"内容预览: {chunk['content'][:200]}...")

except FileNotFoundError:
    print("❌ 未找到 data/raw/test.pdf，请先创建测试文件")
