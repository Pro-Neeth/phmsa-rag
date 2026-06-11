import re
import os


def clean_md(text_content):

    text_content = re.sub(r'\*\*(.*?)\*\*', r'\1', text_content)
    text_content = re.sub(r'\*(.*?)\*', r'\1', text_content)
    text_content = re.sub(r'__(.*?)__', r'\1', text_content)
    text_content = re.sub(r'_(.*?)_', r'\1', text_content)

    text_content = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text_content)

    text_content = re.sub(r'^\s*[-*+]\s+', '', text_content, flags=re.MULTILINE)
    text_content = re.sub(r'^\s*\d+\.\s+', '', text_content, flags=re.MULTILINE)

    text_content = re.sub(r'\n\s*\n', '\n\n', text_content)
    text_content = re.sub(r'[ \t]+', ' ', text_content)

    text_content = text_content.replace('&amp;', '&')

    return text_content.strip()


RAW_DIR    = "Replace with path to raw md files"
CLEANED_DIR = "Replace with path to save cleaned md files"
 
os.makedirs(CLEANED_DIR, exist_ok=True)
 
files = [f for f in os.listdir(RAW_DIR) if f.endswith(".txt")]
 
if not files:
    print(f"No .txt files found in {RAW_DIR}")
else:
    for filename in files:
        raw_path     = os.path.join(RAW_DIR, filename)
        cleaned_path = os.path.join(CLEANED_DIR, filename)
 
        if os.path.exists(cleaned_path):
            print(f"[SKIP] Already cleaned: {filename}")
            continue
 
        try:
            with open(raw_path, "r", encoding="utf-8") as f:
                text_content = f.read()
 
            cleaned = clean_md(text_content)
 
            with open(cleaned_path, "w", encoding="utf-8") as f:
                f.write(cleaned)
 
            print(f"[OK] {filename}")
 
        except Exception as e:
            print(f"[ERROR] {filename}: {e}")
 
    print("Preprocessing complete.")

