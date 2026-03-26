# SAP O2C Graph Query System

Interactive graph visualization + natural language query interface over the SAP Order-to-Cash dataset.

## Stack
- **NetworkX** — graph construction  
- **PyVis** — interactive HTML visualization (vis-network)  
- **Streamlit** — web UI  
- **Groq** (optional, free) — LLM natural language responses via `llama-3.3-70b-versatile`

## Flow Modeled
```
Customer → Sales Order → Delivery → Invoice → Journal Entry → Payment
```

## Setup

```bash
pip install pandas networkx pyvis streamlit groq
```

Place the `sap-o2c-data/` folder in the same directory, then:

```bash
streamlit run app.py
```

Groq API key is **optional** — get a free one at [console.groq.com](https://console.groq.com). Without it, structured results still display.

## Supported Queries

| Query | What it returns |
|---|---|
| `flow` / `trace 740506` | Full O2C chain for a document ID |
| `customer revenue` | Revenue per customer |
| `incomplete flows` | Orders missing delivery/billing/payment |
| `cancelled invoices` | Cancelled billing documents + amounts |
| `top products by billing` | Products with most invoice lines |
| `payment summary` | Total payments by customer |
| `delivery status` | Goods movement status breakdown |

## Guardrails
Off-topic queries (not about O2C domain) are rejected:
> "This system is designed to answer questions related to the SAP Order-to-Cash dataset only."

## Architecture Decision
- LLM used **only for natural language formatting** of structured results — not for data retrieval. This prevents hallucination.
- Full dataset traversed in Python (NetworkX + pandas) to guarantee factual accuracy.
- PyVis renders as self-contained HTML embedded in Streamlit via `components.html`.
