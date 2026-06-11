import re
import os
from uuid import uuid4
 
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_experimental.text_splitter import SemanticChunker
from langchain_huggingface import HuggingFaceEmbeddings


def process_document(text_content, filename):

    metadata = {
        "Filename": filename,
        "URL": None,
        "Subject": None,
        "Date of Failure": None,
        "Commodity Released": None,
        "City, County, and State": None,
        "OpID & Operator Name": None,
        "Unit # & Unit Name": None,
        "SMART Activity #": None,
        "Milepost/Location": None,
        "Type of Failure": None,
        "File Section": None,
    }

    subject_match = re.search(r'^Subject\s*\n\s*(.+?)(?=\n\n|\n##)', text_content, re.MULTILINE | re.DOTALL)
    if subject_match:
        metadata["Subject"] = subject_match.group(1).strip()

    field_patterns = [
        (
            r'Date of Failure\s*\n\s*([^\n]+)',
            r'\|\s*Date of Failure\s*\|\s*([^\|\n]+?)\s*\|',
            'Date of Failure'
        ),
        (
            r'Commodity Released\s*\n\s*([^\n]+)',
            r'\|\s*Commodity Released\s*\|\s*([^\|\n]+?)\s*\|',
            'Commodity Released'
        ),
        (
            r'City[/,]?\s*Parish[,\s]*&?\s*State\s*\n\s*([^\n]+)',
            r'\|\s*City[,\s]*Parish[,\s]*(?:and|&)\s*State\s*\|\s*([^\|\n]+?)\s*\|',
            'City, County, and State'
        ),
        (
            r'OpID\s*&\s*Operator Name\s*\n\s*([^\n]+)',
            r'\|\s*OpID\s*(?:and|&)\s*Operator Name\s*\|\s*([^\|\n]+?)\s*\|',
            'OpID & Operator Name'
        ),
        (
            r'Unit\s*#\s*&\s*Unit Name\s*\n\s*([^\n]+)',
            r'\|\s*Unit\s*#\s*(?:and|&)\s*Unit Name\s*\|\s*([^\|\n]+?)\s*\|',
            'Unit # & Unit Name'
        ),
        (
            r'(?:SMART|WMS)\s*Activity\s*#\s*\n\s*([^\n]+)',
            r'\|\s*(?:SMART|WMS)Activity\s*#\s*\|\s*([^\|\n]+?)\s*\|',
            'SMART Activity #'
        ),
        (
            r'Milepost\s*[/\s]*Location\s*\n\s*([^\n]+)',
            r'\|\s*Milepost\s*[/\s]*Location\s*\|\s*([^\|\n]+?)\s*\|',
            'Milepost/Location'
        ),
        (
            r'Type of Failure\s*\n\s*([^\n]+)',
            r'\|\s*Type of Failure\s*\|\s*([^\|\n]+?)\s*\|',
            'Type of Failure'
        )
    ]

    operator_section_match = re.search(
        r'##\s*Operator,?\s*Location,?\s*&?\s*Consequences\s*\n(.*?)(?=\n##|\Z)',
        text_content,
        re.DOTALL | re.IGNORECASE
    )

    if operator_section_match:
        operator_content = operator_section_match.group(1)

        for vertical_pattern, table_pattern, metadata_key in field_patterns:
            match = re.search(vertical_pattern, operator_content, re.IGNORECASE)

            if match:
                metadata[metadata_key] = match.group(1).strip()
            else:
                match = re.search(table_pattern, operator_content, re.IGNORECASE)
                if match:
                    metadata[metadata_key] = match.group(1).strip()

    sections = re.split(r'\n(?=## )', text_content)

    cleaned_text_sections = []

    for section in sections:
        section = section.strip()

        if not section or not section.startswith('##'):
            continue

        if re.match(r'##\s*Operator,?\s*Location,?\s*&?\s*Consequences', section, re.IGNORECASE):
            continue

        lines = section.split('\n', 1)
        header = lines[0].strip()
        section_title = re.sub(r'^##\s*', '', header).strip()

        section_content = lines[1].strip() if len(lines) > 1 else ""

        section_content = re.sub(r'^\s*\n+', '', section_content)
        section_content = re.sub(r'\n+\s*$', '', section_content)

        section_doc = {
            "Section Title": section_title,
            "Executive Summary": None,
            "Section Content": section_content,
            "Metadata": metadata.copy(),
            "Chunks": []
        }

        section_doc["Metadata"]["File Section"] = section_title

        cleaned_text_sections.append(section_doc)

    return cleaned_text_sections

embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-base-en-v1.5")
 
vector_store = Chroma(
    collection_name="phmsa_vectordb",
    embedding_function=embedding_model,
    persist_directory="./chroma_db",
)
 
def semantic_chunking(text):
    text_splitter = SemanticChunker(
        embedding_model, breakpoint_threshold_type="gradient"
    )
    return text_splitter.split_text(text)

def vectorize(section, id_num):
    documents = []
    for chunk in section["Chunks"]:
        document = Document(
            page_content=chunk,
            metadata=section["Metadata"],
            id=id_num,
        )
        documents.append(document)
    uuids = [str(uuid4()) for _ in range(len(documents))]
    vector_store.add_documents(documents, ids=uuids)


def chunk_and_vectorize_all(cleaned_dir="./data/cleaned_md"):

    files = [f for f in os.listdir(cleaned_dir) if f.endswith(".txt")]
 
    if not files:
        print(f"No .txt files found in {cleaned_dir}")
        return
 
    for filename in files:
        file_path = os.path.join(cleaned_dir, filename)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text_content = f.read()

            processed_sections = process_document(text_content, filename)
 
            for id_num, section in enumerate(processed_sections):
                chunks = semantic_chunking(section["Section Content"])
                section["Chunks"] = chunks
                vectorize(section, id_num)
 
            print(f"[OK] Vectorized: {filename} ({len(processed_sections)} sections)")
 
        except Exception as e:
            print(f"[ERROR] {filename}: {e}")
            continue
 
    print("Chunking and vectorization complete.")
 
 
if __name__ == "__main__":
    chunk_and_vectorize_all()
