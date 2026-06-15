import os
import sys
import json
import time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_experimental.graph_transformers import LLMGraphTransformer
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_neo4j import Neo4jGraph

from parse_graph_metadata import parse_metadata

load_dotenv()

graph = Neo4jGraph(
    url=os.getenv("NEO4J_URI"),
    username=os.getenv("NEO4J_USERNAME"),
    password=os.getenv("NEO4J_PASSWORD"),
)

llm = ChatGoogleGenerativeAI(
    model=os.getenv("GEMINI_MODEL"),
    temperature=0,
)

INTER_REQUEST_DELAY = 4.5         # seconds between whole-document LLM calls


PROGRESS_FILE = os.path.join(os.path.dirname(__file__), "ingest_progress.json")

def load_progress() -> set:
    """Return the set of filenames already ingested."""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("completed", []))
    return set()

def save_progress(completed: set) -> None:
    """Persist the set of completed filenames to disk."""
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump({"completed": sorted(completed)}, f, indent=2)


ALLOWED_NODES = [
    "Operator",         # e.g. Marathon Pipe Line LLC
    "Pipeline",         # e.g. Wabash 12-inch Products Pipeline
    "FailureType",      # e.g. Material Failure, Rupture
    "Cause",            # e.g. Crack in a dent, External Corrosion
    "PipeMaterial",     # e.g. LF ERW X-46, Republic Steel
    "Commodity",        # e.g. Diesel, Gasoline
    "Location",         # e.g. Ashmore / Coles County, Illinois
    "InspectionMethod", # e.g. MFL ILI, Hydrostatic Test
    "Regulator",        # e.g. PHMSA, OPS Central Region
    "CorrectiveAction", # e.g. Pressure reduction, Type B sleeve
]

ALLOWED_RELATIONSHIPS = [
    "OPERATED_BY",       # Pipeline -> Operator
    "CAUSED_BY",         # FailureType -> Cause
    "MADE_OF",           # Pipeline -> PipeMaterial
    "TRANSPORTS",        # Pipeline -> Commodity
    "LOCATED_IN",        # Pipeline -> Location
    "INSPECTED_WITH",    # Pipeline -> InspectionMethod
    "REGULATED_BY",      # Pipeline -> Regulator
    "MITIGATED_BY",      # FailureType -> CorrectiveAction
    "OCCURRED_ON",       # FailureType -> Pipeline
    "INVOLVED_IN",       # Operator -> FailureType
]

transformer = LLMGraphTransformer(
    llm=llm,
    allowed_nodes=ALLOWED_NODES,
    allowed_relationships=ALLOWED_RELATIONSHIPS,
    node_properties=["date", "cost", "commodity", "location"],
    relationship_properties=False,
)


CLEANED_DIR = "./data/md_clean"

all_files = sorted(f for f in os.listdir(CLEANED_DIR) if f.endswith(".txt") or f.endswith(".md"))

if not all_files:
    print(f"No .txt/.md files found in {CLEANED_DIR}")
    sys.exit(1)

completed = load_progress()
pending = [f for f in all_files if f not in completed]

print(f"Total files in corpus : {len(all_files)}")
print(f"Already completed     : {len(completed)} files")
print(f"To process this run   : {len(pending)} files")
print(f"Inter-request delay   : {INTER_REQUEST_DELAY}s")
est_minutes = len(pending) * INTER_REQUEST_DELAY / 60
print(f"Estimated run time    : ~{est_minutes:.1f} min\n")

if not pending:
    print("All files already ingested.")
    sys.exit(0)

for i, filename in enumerate(pending):
    file_path = os.path.join(CLEANED_DIR, filename)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            text_content = f.read()

        # Whole document passed as a single Document — the LLM sees full context
        # so cross-section relationships (e.g. Pipeline OPERATED_BY Operator) are captured.
        metadata = parse_metadata(text_content, filename)
        doc = Document(page_content=text_content, metadata=metadata)

        if i > 0:
            print(f"  └─ waiting {INTER_REQUEST_DELAY}s...")
            time.sleep(INTER_REQUEST_DELAY)

        graph_documents = transformer.convert_to_graph_documents([doc])

        graph.add_graph_documents(
            graph_documents,
            baseEntityLabel=True,
            include_source=True,
        )

        completed.add(filename)
        save_progress(completed)

        print(f"[OK] ({len(completed)}/{len(all_files)}) {filename} — "
              f"{sum(len(gd.nodes) for gd in graph_documents)} nodes, "
              f"{sum(len(gd.relationships) for gd in graph_documents)} relationships")

    except Exception as e:
        print(f"[ERROR] {filename}: {e}")
        continue

graph.refresh_schema()
print(f"\nIngestion complete. {len(completed)} / {len(all_files)} files ingested total.")
print(f"Progress saved to: {PROGRESS_FILE}")
