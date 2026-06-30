import os
from uuid import uuid4
from dotenv import load_dotenv

from sentence_transformers import SentenceTransformer

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Document

from parse_document import process_document


load_dotenv()  

def chunking(text):
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=100,
        chunk_overlap=20,
        length_function=len,
        is_separator_regex=False,
    )
    return text_splitter.split_text(text)

def embedding(section, id_num, vector_store):
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


def main(cleaned_dir="./data/md_clean"):

    embedding_model = SentenceTransformer("BAAI/bge-base-en-v1.5")

    vector_store = QdrantVectorStore.from_existing_collection(
        collection_name="phmsa_vectordb",
        embedding=embedding_model,
        prefer_grpc=True,
        url = os.getenv("QDRANT_URL"),
        api_key=os.getenv("QDRANT_API_KEY"),
        retrieval_mode=RetrievalMode.DENSE,
    )

    files = [f for f in os.listdir(cleaned_dir) if f.endswith(".txt") or f.endswith(".md")]
 
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
                chunks = chunking(section["Section Content"])
                section["Chunks"] = chunks
                embedding(section, id_num, vector_store)
 
            print(f"[OK] Embedded: {filename} ({len(processed_sections)} sections)")
 
        except Exception as e:
            print(f"[ERROR] {filename}: {e}")
            continue
 
    print("Chunking and ingestion complete.")
 
 
if __name__ == "__main__":
    main()
