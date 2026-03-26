import os, glob, json
import pandas as pd
import networkx as nx
from pyvis.network import Network

DATA_DIR = os.environ.get("SAP_DATA_DIR", "sap-o2c-data")

def load_jsonl(folder):
    rows = []
    path = os.path.join(DATA_DIR, folder)
    if not os.path.exists(path):
        return pd.DataFrame()
    for f in glob.glob(os.path.join(path, "*.jsonl")):
        with open(f) as fp:
            for line in fp:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return pd.DataFrame(rows) if rows else pd.DataFrame()

def build_graph():
    so_h  = load_jsonl("sales_order_headers")
    so_i  = load_jsonl("sales_order_items")
    del_h = load_jsonl("outbound_delivery_headers")
    del_i = load_jsonl("outbound_delivery_items")
    bil_h = load_jsonl("billing_document_headers")
    bil_i = load_jsonl("billing_document_items")
    je    = load_jsonl("journal_entry_items_accounts_receivable")
    pay   = load_jsonl("payments_accounts_receivable")
    bp    = load_jsonl("business_partners")
    pd_   = load_jsonl("product_descriptions")

    G = nx.DiGraph()

    bp_name = dict(zip(bp["customer"], bp["businessPartnerFullName"])) if not bp.empty else {}
    prod_name = dict(zip(pd_["product"], pd_["productDescription"])) if not pd_.empty else {}

    # Customers
    for _, r in bp.iterrows():
        G.add_node(f"cust_{r['customer']}", type="customer",
                   label=r.get("businessPartnerFullName","")[:25],
                   id=r["customer"])

    # Sales Orders
    for _, r in so_h.iterrows():
        cust = r.get("soldToParty","")
        amt  = r.get("totalNetAmount","0")
        G.add_node(f"so_{r['salesOrder']}", type="order",
                   label=f"SO {r['salesOrder']}", amount=amt,
                   currency=r.get("transactionCurrency","INR"),
                   delivery_status=r.get("overallDeliveryStatus",""),
                   billing_status=r.get("overallOrdReltdBillgStatus",""))
        if cust and f"cust_{cust}" in G:
            G.add_edge(f"cust_{cust}", f"so_{r['salesOrder']}", label="PLACED")

    # Deliveries (link via delivery_items -> referenceSdDocument = SO)
    del_to_so = {}
    if not del_i.empty:
        for _, r in del_i.iterrows():
            so = str(r.get("referenceSdDocument",""))
            deldoc = str(r.get("deliveryDocument",""))
            if so and deldoc:
                del_to_so[deldoc] = so

    for _, r in del_h.iterrows():
        deldoc = str(r.get("deliveryDocument",""))
        G.add_node(f"del_{deldoc}", type="delivery",
                   label=f"DEL {deldoc}",
                   goods_status=r.get("overallGoodsMovementStatus",""),
                   picking_status=r.get("overallPickingStatus",""))
        if deldoc in del_to_so:
            so = del_to_so[deldoc]
            if f"so_{so}" in G:
                G.add_edge(f"so_{so}", f"del_{deldoc}", label="DELIVERED_VIA")

    # Billing docs (link via billing_items -> referenceSdDocument = delivery)
    bill_to_del = {}
    if not bil_i.empty:
        for _, r in bil_i.iterrows():
            refdoc = str(r.get("referenceSdDocument",""))
            billdoc = str(r.get("billingDocument",""))
            if refdoc and billdoc:
                bill_to_del[billdoc] = refdoc

    for _, r in bil_h.iterrows():
        billdoc = str(r.get("billingDocument",""))
        amt = r.get("totalNetAmount","0")
        cancelled = r.get("billingDocumentIsCancelled", False)
        G.add_node(f"bill_{billdoc}", type="invoice",
                   label=f"INV {billdoc}", amount=amt,
                   cancelled=cancelled,
                   currency=r.get("transactionCurrency","INR"))
        refdel = bill_to_del.get(billdoc,"")
        if refdel and f"del_{refdel}" in G:
            G.add_edge(f"del_{refdel}", f"bill_{billdoc}", label="BILLED_AS")
        # fallback: link to SO if delivery not found
        elif refdel and f"so_{refdel}" in G:
            G.add_edge(f"so_{refdel}", f"bill_{billdoc}", label="BILLED_AS")

    # Journal Entries
    je_seen = set()
    for _, r in je.iterrows():
        jeid = str(r.get("accountingDocument",""))
        refdoc = str(r.get("referenceDocument",""))
        if jeid not in je_seen:
            G.add_node(f"je_{jeid}", type="journal",
                       label=f"JE {jeid}",
                       amount=r.get("amountInTransactionCurrency","0"),
                       currency=r.get("transactionCurrency","INR"))
            je_seen.add(jeid)
        if refdoc and f"bill_{refdoc}" in G:
            G.add_edge(f"bill_{refdoc}", f"je_{jeid}", label="POSTED_TO")

    # Payments
    pay_seen = set()
    for _, r in pay.iterrows():
        clear = str(r.get("clearingAccountingDocument",""))
        acct  = str(r.get("accountingDocument",""))
        if clear and clear not in pay_seen:
            G.add_node(f"pay_{clear}", type="payment",
                       label=f"PAY {clear}",
                       amount=r.get("amountInTransactionCurrency","0"),
                       currency=r.get("transactionCurrency","INR"),
                       date=str(r.get("clearingDate",""))[:10])
            pay_seen.add(clear)
        if acct and f"je_{acct}" in G:
            G.add_edge(f"je_{acct}", f"pay_{clear}", label="CLEARED_BY")

    return G

TYPE_COLORS = {
    "customer": "#f59e0b",
    "order":    "#3b82f6",
    "delivery": "#10b981",
    "invoice":  "#8b5cf6",
    "journal":  "#06b6d4",
    "payment":  "#22c55e",
}

def build_html(G, output="graph.html"):
    net = Network(height="720px", width="100%", directed=True, notebook=False)
    for node, attrs in G.nodes(data=True):
        t = attrs.get("type","order")
        color = TYPE_COLORS.get(t, "#888")
        label = attrs.get("label", node)
        title = f"<b>{label}</b><br>Type: {t}"
        for k, v in attrs.items():
            if k not in ("type","label"):
                title += f"<br>{k}: {v}"
        size = 20 if t == "customer" else 14
        net.add_node(node, label=label, title=title, color=color, size=size, shape="dot")
    for src, dst, attrs in G.edges(data=True):
        net.add_edge(src, dst, title=attrs.get("label",""), arrows="to")
    net.set_options(json.dumps({
        "physics": {"enabled": True,
                    "hierarchicalRepulsion": {"centralGravity":0.0,"springLength":180,"springConstant":0.01,"nodeDistance":220},
                    "solver": "hierarchicalRepulsion"},
        "layout": {"hierarchical": {"enabled":True,"direction":"LR","sortMethod":"directed"}},
        "edges": {"arrows":{"to":{"enabled":True,"scaleFactor":1}},"smooth":{"type":"cubicBezier"}},
        "interaction": {"hover": True, "tooltipDelay": 100}
    }))
    net.save_graph(output)
    print(f"Graph saved → {output}  ({G.number_of_nodes()} nodes, {G.number_of_edges()} edges)")
    return G

if __name__ == "__main__":
    G = build_graph()
    build_html(G)
