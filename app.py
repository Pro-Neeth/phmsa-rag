import sys
import os

# Make sub-packages importable from project root
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PHMSA RAG Chat",
    page_icon="🛢️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Import font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Dark background */
    .stApp {
        background: #0f1117;
        color: #e2e8f0;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: #161b27;
        border-right: 1px solid #1e2a3a;
    }

    /* Chat messages */
    [data-testid="stChatMessage"] {
        background: #1a2035;
        border: 1px solid #1e2a3a;
        border-radius: 12px;
        margin-bottom: 8px;
        padding: 4px 8px;
    }

    /* Input box */
    [data-testid="stChatInput"] textarea {
        background: #1a2035 !important;
        border: 1px solid #2d3a52 !important;
        border-radius: 12px !important;
        color: #e2e8f0 !important;
    }

    /* Badge pill */
    .mode-badge {
        display: inline-block;
        padding: 3px 12px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        margin-bottom: 12px;
    }
    .badge-plain {
        background: #1e3a5f;
        color: #60a5fa;
        border: 1px solid #2563eb44;
    }
    .badge-graph {
        background: #1e3a2f;
        color: #34d399;
        border: 1px solid #10b98144;
    }

    /* Cypher block */
    .cypher-block {
        background: #0d1117;
        border: 1px solid #2d3a52;
        border-radius: 8px;
        padding: 10px 14px;
        font-family: 'Fira Code', monospace;
        font-size: 0.82rem;
        color: #a5f3fc;
        margin-top: 8px;
        white-space: pre-wrap;
    }

    /* Chunk cards */
    .chunk-card {
        background: #111827;
        border: 1px solid #1e2a3a;
        border-left: 3px solid #3b82f6;
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 10px;
    }
    .chunk-header {
        font-size: 0.78rem;
        font-weight: 600;
        color: #60a5fa;
        margin-bottom: 6px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .chunk-index {
        background: #1e3a5f;
        color: #93c5fd;
        border-radius: 4px;
        padding: 1px 7px;
        font-size: 0.75rem;
        font-weight: 700;
    }
    .chunk-meta {
        color: #94a3b8;
        font-size: 0.75rem;
    }
    .chunk-body {
        font-size: 0.82rem;
        color: #cbd5e1;
        margin-top: 6px;
        line-height: 1.55;
        white-space: pre-wrap;
    }

    hr {
        border-color: #1e2a3a !important;
    }

    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #0f1117; }
    ::-webkit-scrollbar-thumb { background: #2d3a52; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)


# ── Lazy model loaders (cached so connections are reused) ─────────────────────
@st.cache_resource(show_spinner="Loading Plain RAG pipeline…")
def load_plain_rag():
    from plain_rag.rag import query_pipeline
    return query_pipeline


@st.cache_resource(show_spinner="Loading Graph RAG pipeline…")
def load_graph_rag():
    from graph_rag_v1.graphrag_v1 import query_graph, save_query_log
    return query_graph, save_query_log


# ── Helper: render retrieved chunks expander ──────────────────────────────────
def render_chunks(docs):
    """Render a collapsible expander listing every retrieved chunk."""
    if not docs:
        return
    label = f"📄 Chunks Retrieved ({len(docs)})"
    with st.expander(label, expanded=False):
        for i, doc in enumerate(docs, start=1):
            filename = doc.metadata.get("Filename", "unknown")
            section  = doc.metadata.get("File Section", "unknown section")
            content  = doc.page_content
            st.markdown(
                f"""
<div class="chunk-card">
  <div class="chunk-header">
    <span class="chunk-index">[{i}]</span>
    <span class="chunk-meta">{filename} &mdash; {section}</span>
  </div>
  <div class="chunk-body">{content}</div>
</div>""",
                unsafe_allow_html=True,
            )


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛢️ PHMSA RAG Chat")
    st.markdown("Ask questions about pipeline incident reports.")
    st.divider()

    mode = st.radio(
        "**RAG Mode**",
        options=["Plain RAG", "Graph RAG"],
        index=0,
        help="Plain RAG uses vector similarity search. Graph RAG queries a Neo4j knowledge graph via Cypher.",
    )

    st.divider()

    if mode == "Plain RAG":
        st.markdown("""
        **Plain RAG**  
        Retrieves relevant document chunks from Qdrant using dense vector search,
        then generates an answer with Gemini.
        """)
    else:
        st.markdown("""
        **Graph RAG**  
        Translates your question into a Cypher query, runs it against a Neo4j
        knowledge graph, and synthesizes the answer with Gemini.  
        The generated Cypher query is shown beneath each answer.
        """)

    st.divider()

    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

    st.caption("Powered by Gemini · Qdrant · Neo4j")


# ── Session state ─────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

if "current_mode" not in st.session_state:
    st.session_state.current_mode = mode

# Reset history when mode switches
if st.session_state.current_mode != mode:
    st.session_state.messages = []
    st.session_state.current_mode = mode


# ── Header ────────────────────────────────────────────────────────────────────
badge_class = "badge-plain" if mode == "Plain RAG" else "badge-graph"
badge_label = "Plain RAG — Vector Search" if mode == "Plain RAG" else "Graph RAG — Neo4j Cypher"
st.markdown(
    f'<span class="mode-badge {badge_class}">{badge_label}</span>',
    unsafe_allow_html=True,
)
st.markdown("### Ask a question about PHMSA pipeline incidents")


# ── Render chat history ───────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("chunks"):
            render_chunks(msg["chunks"])
        if msg.get("cypher"):
            with st.expander("🔍 Cypher Query", expanded=False):
                st.markdown(
                    f'<div class="cypher-block">{msg["cypher"]}</div>',
                    unsafe_allow_html=True,
                )


# ── Chat input ────────────────────────────────────────────────────────────────
placeholder = (
    "e.g. What are the most common causes of pipeline incidents?"
    if mode == "Plain RAG"
    else "e.g. Which operators had the most incidents in 2022?"
)

if prompt := st.chat_input(placeholder):
    # Save and display user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate response
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                if mode == "Plain RAG":
                    query_pipeline = load_plain_rag()
                    answer, docs = query_pipeline(prompt)
                    cypher = None
                else:
                    query_graph, save_query_log = load_graph_rag()
                    answer, cypher = query_graph(prompt)
                    docs = None
                    save_query_log(prompt, answer, cypher)
            except Exception as e:
                answer = f"❌ Error: {e}"
                cypher = None
                docs = None

        st.markdown(answer)

        if docs:
            render_chunks(docs)

        if cypher:
            with st.expander("🔍 Cypher Query", expanded=False):
                st.markdown(
                    f'<div class="cypher-block">{cypher}</div>',
                    unsafe_allow_html=True,
                )

    # Save assistant message to history
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "chunks": docs,
        "cypher": cypher,
    })
