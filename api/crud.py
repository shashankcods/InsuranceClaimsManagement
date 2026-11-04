"""Generic CRUD over whitelisted tables/views.

Identifiers (table, column, sort) come ONLY from the RESOURCES whitelist below;
values always go through %s placeholders, so user input never becomes SQL text.
"""
from fastapi import HTTPException

from .db import execute, query, query_one

# resource -> config. "table" takes the writes; "view" (optional) serves the reads and may add
# joined columns ("read_extra", e.g. city/state from pincode); "readonly" blocks all writes.
RESOURCES = {
    "pincodes": dict(
        table="pincode", pk="pincode", pk_writable=True,
        columns=["pincode", "city", "state"],
        search=["pincode", "city", "state"], filters=["city", "state"], default_sort="pincode"),
    "customers": dict(
        table="customer", view="v_customer_directory", pk="customer_id",
        columns=["first_name", "last_name", "dob", "gender", "email", "phone", "address_line", "pincode"],
        read_extra=["city", "state"],
        search=["first_name", "last_name", "email", "phone", "city", "pincode"],
        filters=["city", "state", "gender", "pincode"], default_sort="customer_id"),
    "agents": dict(
        table="agent", pk="agent_id",
        columns=["first_name", "last_name", "email", "phone", "branch_city", "hire_date",
                 "commission_rate", "manager_id"],
        search=["first_name", "last_name", "email", "branch_city"],
        filters=["branch_city", "manager_id"], default_sort="agent_id"),
    "policy-types": dict(
        table="policy_type", pk="type_id",
        columns=["type_name", "description", "min_sum_assured", "max_sum_assured",
                 "base_rate_pct", "max_term_years"],
        search=["type_name", "description"], filters=[], default_sort="type_id"),
    "providers": dict(
        table="provider", view="v_provider_directory", pk="provider_id",
        columns=["name", "provider_type", "pincode", "phone", "is_network"],
        read_extra=["city", "state"],
        search=["name", "city"], filters=["provider_type", "city", "is_network"], default_sort="provider_id"),
    "adjusters": dict(
        table="adjuster", pk="adjuster_id",
        columns=["first_name", "last_name", "email", "phone", "approval_limit"],
        search=["first_name", "last_name", "email"], filters=[], default_sort="adjuster_id"),
    "nominees": dict(
        table="nominee", pk="nominee_id",
        columns=["policy_id", "full_name", "relationship", "dob", "share_pct"],
        search=["full_name"], filters=["policy_id", "relationship"], default_sort="nominee_id"),
    # read-only: instalments are raised by sp_sell_policy / sp_generate_instalments
    # and paid through POST /api/payments/{id}/pay (sp_pay_premium)
    "payments": dict(
        table="premium_payment", pk="payment_id", readonly=True,
        columns=["policy_id", "instalment_no", "due_date", "amount", "status", "paid_on", "method"],
        search=[], filters=["policy_id", "status", "method"], default_sort="due_date"),
    "documents": dict(
        table="claim_document", pk="doc_id",
        columns=["claim_id", "doc_type", "file_name"],
        search=["file_name"], filters=["claim_id", "doc_type"], default_sort="doc_id"),
}

# Read-only list endpoints over views
VIEW_LISTS = {
    "policies": dict(
        view="v_policy_overview", pk="policy_id",
        search=["policy_number", "customer_name", "agent_name"],
        filters=["status", "type_name", "customer_id", "agent_id", "city"],
        sortable=["policy_id", "policy_number", "start_date", "end_date", "sum_assured", "premium_amount",
                  "status", "customer_name", "type_name", "days_to_expiry", "overdue_instalments", "claim_count"],
        default_sort="policy_id"),
    "claims": dict(
        view="v_claim_summary", pk="claim_id",
        search=["claim_number", "customer_name", "policy_number", "provider_name"],
        filters=["status", "type_name", "claim_type", "risk_band", "policy_id", "adjuster_id", "fraud_flag", "customer_id"],
        sortable=["claim_id", "claim_number", "filed_on", "incident_date", "claimed_amount", "approved_amount",
                  "paid_amount", "status", "fraud_score", "customer_name", "type_name"],
        default_sort="filed_on"),
    "overdue": dict(
        view="v_overdue_premiums", pk="payment_id",
        search=["policy_number", "customer_name", "phone"],
        filters=["policy_status", "type_name", "policy_id"],
        sortable=["due_date", "days_overdue", "amount", "customer_name", "policy_number"],
        default_sort="days_overdue"),
}

MAX_LIMIT = 500


def _list(source, pk, search_cols, filter_cols, sortable, default_sort, params):
    where, args = [], []
    search = params.get("search")
    if search and search_cols:
        where.append("(" + " OR ".join(f"`{c}` LIKE %s" for c in search_cols) + ")")
        args += [f"%{search}%"] * len(search_cols)
    for col in filter_cols:
        val = params.get(col)
        if val not in (None, ""):
            vals = str(val).split(",")
            where.append(f"`{col}` IN ({', '.join(['%s'] * len(vals))})")
            args += vals
    sort = params.get("sort") or default_sort
    if sort not in sortable:
        raise HTTPException(400, f"Cannot sort by '{sort}'. Allowed: {', '.join(sortable)}")
    order = "DESC" if str(params.get("order", "asc")).lower() == "desc" else "ASC"
    limit = max(1, min(int(params.get("limit") or 50), MAX_LIMIT))
    offset = max(0, int(params.get("offset") or 0))
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total = query_one(f"SELECT COUNT(*) AS n FROM `{source}`{where_sql}", args)["n"]
    rows = query(f"SELECT * FROM `{source}`{where_sql} ORDER BY `{sort}` {order}, `{pk}` {order} "
                 f"LIMIT %s OFFSET %s", args + [limit, offset])
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def config(resource):
    cfg = RESOURCES.get(resource)
    if not cfg:
        raise HTTPException(404, f"Unknown resource '{resource}'")
    return cfg


def _read_source(cfg):
    return cfg.get("view", cfg["table"])


def _writable(resource):
    cfg = config(resource)
    if cfg.get("readonly"):
        raise HTTPException(405, f"'{resource}' is read-only through generic CRUD; use its dedicated endpoints")
    return cfg


def list_rows(resource, params):
    cfg = config(resource)
    sortable = list(dict.fromkeys([cfg["pk"]] + cfg["columns"] + cfg.get("read_extra", [])))
    return _list(_read_source(cfg), cfg["pk"], cfg["search"], cfg["filters"], sortable, cfg["default_sort"], params)


def list_view(name, params):
    cfg = VIEW_LISTS[name]
    return _list(cfg["view"], cfg["pk"], cfg["search"], cfg["filters"], cfg["sortable"], cfg["default_sort"], params)


def get_row(resource, row_id):
    cfg = config(resource)
    row = query_one(f"SELECT * FROM `{_read_source(cfg)}` WHERE `{cfg['pk']}` = %s", (row_id,))
    if not row:
        raise HTTPException(404, f"{resource} {row_id} not found")
    return row


def _clean(cfg, body, partial):
    unknown = set(body) - set(cfg["columns"])
    if unknown:
        raise HTTPException(422, f"Unknown or read-only field(s): {', '.join(sorted(unknown))}")
    data = {k: (None if v == "" else v) for k, v in body.items()}
    if not partial and not data:
        raise HTTPException(422, "No fields supplied")
    return data


def create_row(resource, body):
    cfg = _writable(resource)
    data = _clean(cfg, body, partial=False)
    cols = ", ".join(f"`{c}`" for c in data)
    _, new_id = execute(f"INSERT INTO `{cfg['table']}` ({cols}) VALUES ({', '.join(['%s'] * len(data))})",
                        list(data.values()))
    return get_row(resource, data[cfg["pk"]] if cfg.get("pk_writable") else new_id)


def update_row(resource, row_id, body):
    cfg = _writable(resource)
    data = _clean(cfg, body, partial=True)
    if not data:
        return get_row(resource, row_id)
    get_row(resource, row_id)
    sets = ", ".join(f"`{c}` = %s" for c in data)
    execute(f"UPDATE `{cfg['table']}` SET {sets} WHERE `{cfg['pk']}` = %s", list(data.values()) + [row_id])
    # a writable key (pincode) may itself have changed; ON UPDATE CASCADE carries it to the children
    return get_row(resource, data.get(cfg["pk"], row_id))


def delete_row(resource, row_id):
    cfg = _writable(resource)
    count, _ = execute(f"DELETE FROM `{cfg['table']}` WHERE `{cfg['pk']}` = %s", (row_id,))
    if count == 0:
        raise HTTPException(404, f"{resource} {row_id} not found")
    return {"deleted": row_id}
