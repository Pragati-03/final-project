import streamlit as st
import streamlit.components.v1 as components
import os, sys

st.set_page_config(page_title="SAP O2C Graph Query", layout="wide")

# ── Build graph on first run ────────────────────────────────────
@st.cache_resource
def load_graph():
    sys.path.insert(0, os.path.dirname(__file__))
    from graph import build_graph, build_html
    G = build_graph()
    build_html(G, "graph.html")
    return G

G = load_graph()

# ── Groq NL conversion (optional, free) ────────────────────────
def to_natural_language(structured: str, query: str, api_key: str) -> str:
    if not api_key:
        return structured
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": (
                    "You are a business analyst assistant. The user asked a question about SAP Order-to-Cash data. "
                    "You are given structured data. Convert it into a clear, concise natural language response. "
                    "Keep IDs/amounts intact. Be brief. If the data says the system can't answer, relay that message unchanged."
                )},
                {"role": "user", "content": f"Question: {query}\n\nData:\n{structured}"}
            ],
            max_tokens=400
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"{structured}\n\n*(Groq unavailable: {e})*"

# ── Layout ──────────────────────────────────────────────────────
st.title("🔗 SAP O2C Context Graph")

col_graph, col_chat = st.columns([3, 2])

with col_graph:
    st.markdown(f"**{G.number_of_nodes()} nodes · {G.number_of_edges()} edges** | Click a node to inspect")
    try:
        with open("graph.html", "r", encoding="utf-8") as f:
            html = f.read()
        components.html(html, height=720, scrolling=False)
    except FileNotFoundError:
        st.error("graph.html not found. Ensure graph.py ran correctly.")

with col_chat:
    st.markdown("### 💬 Query Interface")
    # groq_key = st.text_input("Groq API Key (optional — free at console.groq.com):",
    #                           type="password", placeholder="gsk_...")
    
    st.caption("Query the transaction graph using natural language")
    # Quick queries
    st.markdown("**Quick queries:**")
    qcols = st.columns(2)
    quick = [
        "Show O2C flow summary", "Customer revenue",
        "Incomplete flows", "Cancelled invoices",
        "Top products by billing", "Payment summary",
    ]
    for i, q in enumerate(quick):
        if qcols[i % 2].button(q, use_container_width=True):
            st.session_state["prefill"] = q

    # Chat history
    if "history" not in st.session_state:
        st.session_state.history = []

    with st.container():
        for role, msg in st.session_state.history:
            with st.chat_message(role):
                st.markdown(msg)

    prefill = st.session_state.pop("prefill", "")
    user_q = st.chat_input("Ask about orders, deliveries, billing, payments…")
    if prefill and not user_q:
        user_q = prefill

    if user_q:
        st.session_state.history.append(("user", user_q))
        with st.chat_message("user"):
            st.markdown(user_q)

        from query import get_structured_answer
        result = get_structured_answer(user_q)
        structured = result["result"]
        answer = to_natural_language(structured, user_q, groq_key)

        st.session_state.history.append(("assistant", answer))
        with st.chat_message("assistant"):
            st.markdown(answer)

    # Legend
    st.markdown("---")
    st.markdown("""
**Node colors:**
🟡 Customer &nbsp; 🔵 Sales Order &nbsp; 🟢 Delivery  
🟣 Invoice &nbsp; 🩵 Journal Entry &nbsp; 🟩 Payment
""")
st.markdown("---")
st.markdown(
    "🚀 Powered by Streamlit • NetworkX • PyVis • Groq AI  \n"
    "📊 Graph-Based Business Query System"
)