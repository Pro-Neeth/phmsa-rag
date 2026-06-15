import os
from dotenv import load_dotenv
 
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_neo4j import Neo4jGraph, GraphCypherQAChain
from langchain_core.prompts import PromptTemplate
 
load_dotenv()
 
 
graph = Neo4jGraph(
    url=os.getenv("NEO4J_URI"),
    username=os.getenv("NEO4J_USERNAME"),
    password=os.getenv("NEO4J_PASSWORD"),
    refresh_schema=True, 
)
 
llm = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite",
    temperature=0.2,
    max_retries=2,
)
 
 
CYPHER_PROMPT = PromptTemplate(
    input_variables=["schema", "question"],
    template="""You are a helpful assistant that translates natural language questions \
about PHMSA pipeline incident data into Cypher queries for a Neo4j graph database.

Rules:
1. Only use node labels, relationship types, and properties that exist in the schema below.
2. Do not use outside knowledge — derive everything from the schema.
3. If the question cannot be answered from the schema, return an empty string.

Schema:
{schema}

Question: {question}

Cypher Query:"""
)

QA_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template="""You are a helpful assistant that answers questions about pipeline \
incident reports published by PHMSA. You provide detailed causal analysis based \
on graph query results.

Rules:
1. Only use the provided context. Do not use outside knowledge.
2. For causal analysis questions, be thorough and specific.
3. Always cite specific values from the context (incident IDs, operator names, dates, etc.) for every claim you make.
4. If the context does not contain enough information to answer, say 'I don't know, sorry.'

Context:
{context}

Question: {question}

Answer:"""
)

chain = GraphCypherQAChain.from_llm(
    llm=llm,
    graph=graph,
    cypher_prompt=CYPHER_PROMPT,
    qa_prompt=QA_PROMPT,
    verbose=True,
    allow_dangerous_requests=True,
    return_intermediate_steps=True,
)

 
def query_graph(question):

    result = chain.invoke({"query": question})
 
    answer = result.get("result", "No answer returned.")
    steps  = result.get("intermediate_steps", [])
 
  
    cypher = ""
    for step in steps:
        if isinstance(step, dict) and "query" in step:
            cypher = step["query"]
            break
 
    return answer, cypher
 
 
def save_query_log(question, answer, cypher, log_path="./evaluation/graph_query_log.txt"):
    
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"Q: {question}\n")
        f.write(f"Cypher: {cypher}\n")
        f.write(f"A: {answer}\n")
        f.write("-" * 60 + "\n")
 
 
 
print("PHMSA GraphRAG Pipeline")
print("Queries are translated to Cypher and executed against Neo4j Aura.")
print("Type 'exit' to quit, 'schema' to print the current graph schema.\n")
 
while True:
    question = input("Query: ").strip()
 
    if not question:
        continue
 
    if question.lower() in ("exit", "quit"):
        break
 
    if question.lower() == "schema":
        print(graph.schema)
        continue
 
    answer, cypher = query_graph(question)
    save_query_log(question, answer, cypher)
    print(f"\n{answer}\n")
