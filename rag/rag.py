import os
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate

load_dotenv()  

embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-base-en-v1.5")

vector_store = Chroma(
    collection_name="phmsa_vectordb",
    embedding_function=embedding_model,
    persist_directory="./chroma_db",
)

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0.5,
    max_tokens=None,
    reasoning_format="parsed",
    timeout=None,
    max_retries=2,
)


prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a helpful assistant that answers questions about pipeline \
incident reports published by PHMSA. You provide detailed causal analysis based \
on the retrieved report sections.

Rules:
1. Only use the provided context. Do not use outside knowledge.
2. For causal analysis questions, be thorough and specific.
3. Always cite the source document (filename and section) for every claim you make.
4. If the context does not contain enough information to answer, say 'I don't know, sorry.'"""),
    ("user", "Query: {query}\n\nContext:\n{context}")
])


def retrieve(query, k=14):
    docs = vector_store.similarity_search(query, k=k)
    return docs

def format_context(docs):
    sections = []
    for doc in docs:
        filename = doc.metadata.get("Filename", "unknown")
        section  = doc.metadata.get("File Section", "unknown section")
        sections.append(f"[{filename} — {section}]\n{doc.page_content}")
    return "\n\n".join(sections)

def query_pipeline(query):
    docs    = retrieve(query)
    context = format_context(docs)
    chain   = prompt | llm
    response = chain.invoke({"query": query, "context": context})

    # save retrieved chunks for inspection
    eval_path = "./data/evaluation/validation/chunk_retrieval.txt"
    os.makedirs(os.path.dirname(eval_path), exist_ok=True)
    with open(eval_path, "w", encoding="utf-8") as f:
        f.write(f"Query: {query}\n\n")
        f.write("\n\n".join(str(doc) for doc in docs))

    return response.content


print("PHMSA RAG Pipeline — type 'exit' to quit\n")

while True:
    query = input("Query: ").strip()
    if not query:
        continue
    if query.lower() in ("exit", "quit"):
        break

    answer = query_pipeline(query)
    print(f"\n{answer}\n")