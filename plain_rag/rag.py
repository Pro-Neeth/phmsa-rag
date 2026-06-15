import os
from dotenv import load_dotenv

from langchain_qdrant import QdrantVectorStore, RetrievalMode
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate

load_dotenv()  

os.environ["HF_TOKEN"] = os.getenv("HF_TOKEN")
embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-base-en-v1.5")

vector_store = QdrantVectorStore.from_existing_collection(
        collection_name="phmsa_vectordb",
        embedding=embedding_model,
        prefer_grpc=True,
        url = os.getenv("QDRANT_URL"),
        api_key=os.getenv("QDRANT_API_KEY"),
        retrieval_mode=RetrievalMode.DENSE,
    )

llm = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite",
    temperature=0.2,
    max_tokens=None,
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


def retrieve(query, k=15):
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

    eval_path = "./evaluation/chunk_retrieval.txt"
    os.makedirs(os.path.dirname(eval_path), exist_ok=True)
    with open(eval_path, "w", encoding="utf-8") as f:
        f.write(f"Query: {query}\n\n")
        f.write("\n\n".join(str(doc) for doc in docs))

    return response.content


if __name__ == "__main__":
    print("PHMSA RAG Pipeline — type 'exit' to quit\n")

    while True:
        query = input("Query: ").strip()
        if not query:
            continue
        if query.lower() in ("exit", "quit"):
            break

        answer = query_pipeline(query)
        print(f"\n{answer}\n")