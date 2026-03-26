import json, os, glob
import pandas as pd

DATA_DIR = os.environ.get("SAP_DATA_DIR", "sap-o2c-data")

def _load(folder):
    rows = []
    path = os.path.join(DATA_DIR, folder)
    if not os.path.exists(path):
        return pd.DataFrame()
    for f in glob.glob(os.path.join(path, "*.jsonl")):
        with open(f) as fp:
            for line in fp:
                l = line.strip()
                if l: rows.append(json.loads(l))
    return pd.DataFrame(rows) if rows else pd.DataFrame()

# Load once at import
_so  = _load("sales_order_headers")
_soi = _load("sales_order_items")
_dh  = _load("outbound_delivery_headers")
_di  = _load("outbound_delivery_items")
_bh  = _load("billing_document_headers")
_bi  = _load("billing_document_items")
_bc  = _load("billing_document_cancellations")
_je  = _load("journal_entry_items_accounts_receivable")
_pay = _load("payments_accounts_receivable")
_bp  = _load("business_partners")
_pd  = _load("product_descriptions")

_bp_name = dict(zip(_bp["customer"], _bp["businessPartnerFullName"])) if not _bp.empty else {}
_prod_name = dict(zip(_pd["product"], _pd["productDescription"])) if not _pd.empty else {}

# Pre-build join maps
_del_to_so = {}
if not _di.empty:
    for _, r in _di.iterrows():
        _del_to_so[str(r.get("deliveryDocument",""))] = str(r.get("referenceSdDocument",""))

_bill_to_del = {}
if not _bi.empty:
    for _, r in _bi.iterrows():
        _bill_to_del[str(r.get("billingDocument",""))] = str(r.get("referenceSdDocument",""))

def _so_for_bill(bill_id):
    deldoc = _bill_to_del.get(str(bill_id),"")
    return _del_to_so.get(deldoc, deldoc)


def get_structured_answer(query: str) -> dict:
    """Returns {result: str, nodes: list[str], error: bool}"""
    q = query.lower().strip()

    # ── GUARDRAIL ──────────────────────────────────────────────
    domain_words = ["order","delivery","invoice","billing","payment","customer",
                    "product","sales","flow","trace","revenue","cancel","ship",
                    "journal","entry","complete","incomplete","missing","status",
                    "amount","quantity","material","plant","document"]
    if not any(w in q for w in domain_words):
        return {"result": "This system is designed to answer questions related to the SAP Order-to-Cash dataset only. Please ask about orders, deliveries, billing, payments, customers, or products.", "nodes": [], "error": False}

    # ── TRACE FLOW ─────────────────────────────────────────────
    if any(w in q for w in ["trace","flow","chain","end-to-end","end to end"]):
        # find a specific ID
        import re
        ids = re.findall(r'\b(\d{6,})\b', query)
        if ids:
            bid = ids[0]
            # trace: SO → DEL → BILL → JE → PAY
            lines = [f"**Tracing document: {bid}**\n"]
            # find SO
            so_match = _so[_so["salesOrder"] == bid] if not _so.empty else pd.DataFrame()
            if not so_match.empty:
                r = so_match.iloc[0]
                cust = _bp_name.get(r.get("soldToParty",""), r.get("soldToParty",""))
                lines.append(f"📦 **Sales Order** `{bid}` | Customer: {cust} | Amount: {r.get('totalNetAmount','')} {r.get('transactionCurrency','')}")
                # deliveries
                delivs = _di[_di["referenceSdDocument"]==bid]["deliveryDocument"].unique() if not _di.empty else []
                for d in delivs:
                    lines.append(f"  → 🚚 **Delivery** `{d}`")
                    bills = [k for k,v in _bill_to_del.items() if v==str(d)]
                    for b in bills:
                        brow = _bh[_bh["billingDocument"]==b]
                        amt = brow.iloc[0]["totalNetAmount"] if not brow.empty else "?"
                        lines.append(f"    → 🧾 **Invoice** `{b}` | Amount: {amt}")
                        jes = _je[_je["referenceDocument"]==b]["accountingDocument"].unique() if not _je.empty else []
                        for j in jes:
                            lines.append(f"      → 📒 **Journal Entry** `{j}`")
                            pays = _pay[_pay["accountingDocument"]==j]["clearingAccountingDocument"].unique() if not _pay.empty else []
                            for p in pays:
                                lines.append(f"        → 💰 **Payment** `{p}`")
                nodes = [f"so_{bid}"] + [f"del_{d}" for d in delivs]
            else:
                # try as billing doc
                brow = _bh[_bh["billingDocument"]==bid]
                if not brow.empty:
                    r = brow.iloc[0]
                    lines.append(f"🧾 **Invoice** `{bid}` | Amount: {r.get('totalNetAmount','')} | Cancelled: {r.get('billingDocumentIsCancelled',False)}")
                    deldoc = _bill_to_del.get(bid,"")
                    sodoc = _del_to_so.get(deldoc,"")
                    if sodoc:
                        lines.append(f"  ← 🚚 Delivery `{deldoc}` ← 📦 SO `{sodoc}`")
                    jes = _je[_je["referenceDocument"]==bid]["accountingDocument"].unique() if not _je.empty else []
                    for j in jes:
                        lines.append(f"  → 📒 JE `{j}`")
                        pays = _pay[_pay["accountingDocument"]==j]["clearingAccountingDocument"].unique() if not _pay.empty else []
                        for p in pays: lines.append(f"    → 💰 PAY `{p}`")
                    nodes = [f"bill_{bid}",f"del_{deldoc}",f"so_{sodoc}"] + [f"je_{j}" for j in jes]
                else:
                    lines.append(f"No document found with ID {bid}.")
                    nodes = []
            return {"result": "\n".join(lines), "nodes": nodes}
        else:
            # generic flow overview
            lines = ["**O2C Flow Summary**\n",
                     f"📦 Sales Orders: **{len(_so)}**",
                     f"🚚 Deliveries: **{len(_dh)}**",
                     f"🧾 Billing Docs: **{len(_bh)}**",
                     f"📒 Journal Entries: **{len(_je.drop_duplicates('accountingDocument'))}**" if not _je.empty else "📒 Journal Entries: 0",
                     f"💰 Payments: **{len(_pay.drop_duplicates('clearingAccountingDocument'))}**" if not _pay.empty else "💰 Payments: 0",
                     "\n**Flow:** Customer → Sales Order → Delivery → Invoice → Journal Entry → Payment"]
            return {"result": "\n".join(lines), "nodes": []}

    # ── CANCELLED INVOICES ─────────────────────────────────────
    if any(w in q for w in ["cancel","cancelled"]):
        if not _bc.empty:
            cancelled = _bc[_bc["billingDocumentIsCancelled"]==True] if "billingDocumentIsCancelled" in _bc else _bc
            total_amt = pd.to_numeric(cancelled["totalNetAmount"], errors="coerce").sum()
            lines = [f"**Cancelled Billing Documents: {len(cancelled)}** | Total: ₹{total_amt:,.2f}\n"]
            for _, r in cancelled.head(10).iterrows():
                cust = _bp_name.get(r.get("soldToParty",""), r.get("soldToParty",""))
                lines.append(f"• `{r['billingDocument']}` | ₹{r.get('totalNetAmount',0)} | Customer: {cust}")
            if len(cancelled) > 10: lines.append(f"  ... and {len(cancelled)-10} more")
            nodes = [f"bill_{r['billingDocument']}" for _, r in cancelled.head(20).iterrows()]
            return {"result": "\n".join(lines), "nodes": nodes}

    # ── INCOMPLETE / BROKEN FLOWS ──────────────────────────────
    if any(w in q for w in ["incomplete","broken","missing","no invoice","no billing","not billed","no payment","unpaid"]):
        lines = ["**Incomplete O2C Flows:**\n"]
        nodes = []
        billed_sos = set()
        for bid, deldoc in _bill_to_del.items():
            so = _del_to_so.get(deldoc,"")
            if so: billed_sos.add(so)

        delivered_sos = set(_del_to_so.values())
        all_sos = set(_so["salesOrder"].astype(str)) if not _so.empty else set()

        not_delivered = all_sos - delivered_sos
        delivered_not_billed = delivered_sos - billed_sos

        billed_docs = set(_bh["billingDocument"].astype(str)) if not _bh.empty else set()
        billed_in_je = set(_je["referenceDocument"].astype(str)) if not _je.empty else set()
        billed_not_je = billed_docs - billed_in_je

        je_docs = set(_je["accountingDocument"].astype(str)) if not _je.empty else set()
        je_in_pay = set(_pay["accountingDocument"].astype(str)) if not _pay.empty else set()
        je_not_paid = je_docs - je_in_pay

        lines.append(f"📦 Orders with no delivery: **{len(not_delivered)}** — {', '.join(list(not_delivered)[:5])}")
        lines.append(f"🚚 Delivered but not billed: **{len(delivered_not_billed)}** — {', '.join(list(delivered_not_billed)[:5])}")
        lines.append(f"🧾 Billed but no journal entry: **{len(billed_not_je)}**")
        lines.append(f"📒 Journal entries without payment: **{len(je_not_paid)}**")

        nodes = [f"so_{s}" for s in list(not_delivered)[:10]] + [f"so_{s}" for s in list(delivered_not_billed)[:10]]
        return {"result": "\n".join(lines), "nodes": nodes}

    # ── TOP PRODUCTS BY BILLING ─────────────────────────────────
    if any(w in q for w in ["product","material","top","highest","billing"]):
        if not _bi.empty:
            prod_counts = _bi.groupby("material")["billingDocument"].count().sort_values(ascending=False).head(10)
            prod_amounts = _bi.groupby("material")["netAmount"].apply(lambda x: pd.to_numeric(x, errors="coerce").sum())
            lines = ["**Top Products by Billing Document Count:**\n"]
            nodes = []
            for i, (mat, cnt) in enumerate(prod_counts.items(), 1):
                name = _prod_name.get(mat, mat[:20])
                amt = prod_amounts.get(mat, 0)
                lines.append(f"{i}. `{mat}` — **{cnt}** invoices | ₹{amt:,.2f} | {name}")
                nodes.append(f"prod_{mat}")
            return {"result": "\n".join(lines), "nodes": nodes}

    # ── CUSTOMER REVENUE ───────────────────────────────────────
    if any(w in q for w in ["customer","revenue","sales","who"]):
        if not _so.empty:
            _so["amt"] = pd.to_numeric(_so["totalNetAmount"], errors="coerce")
            rev = _so.groupby("soldToParty")["amt"].sum().sort_values(ascending=False)
            lines = ["**Customer Revenue (by Sales Order Amount):**\n"]
            nodes = []
            for cust, amt in rev.items():
                name = _bp_name.get(cust, cust)
                count = len(_so[_so["soldToParty"]==cust])
                lines.append(f"• **{name}** (`{cust}`) — ₹{amt:,.2f} | {count} orders")
                nodes.append(f"cust_{cust}")
            return {"result": "\n".join(lines), "nodes": nodes}

    # ── DELIVERY STATUS ────────────────────────────────────────
    if any(w in q for w in ["delivery","deliver","ship"]):
        if not _dh.empty:
            status_counts = _dh["overallGoodsMovementStatus"].value_counts()
            lines = ["**Delivery Status Summary:**\n",
                     f"Total deliveries: **{len(_dh)}**\n"]
            status_map = {"A": "Not Started", "B": "Partial", "C": "Complete"}
            for s, cnt in status_counts.items():
                lines.append(f"• {status_map.get(s, s)}: **{cnt}**")
            return {"result": "\n".join(lines), "nodes": []}

    # ── PAYMENT SUMMARY ────────────────────────────────────────
    if any(w in q for w in ["payment","paid","clear","amount"]):
        if not _pay.empty:
            _pay["amt"] = pd.to_numeric(_pay["amountInTransactionCurrency"], errors="coerce")
            total = _pay["amt"].sum()
            by_cust = _pay.groupby("customer")["amt"].sum().sort_values(ascending=False)
            lines = [f"**Payment Summary — Total: ₹{total:,.2f}**\n"]
            for c, a in by_cust.items():
                name = _bp_name.get(c, c)
                lines.append(f"• {name}: ₹{a:,.2f}")
            nodes = [f"pay_{r['clearingAccountingDocument']}" for _, r in _pay.head(20).iterrows()]
            return {"result": "\n".join(lines), "nodes": nodes}

    return {"result": "I couldn't find a specific match. Try asking about: flow, customers, revenue, cancelled invoices, incomplete flows, top products, deliveries, or payments.", "nodes": [], "error": False}
