"""The tables the dashboard reads, their columns and types.

Any source (the synthetic generator, CSV files, or a database adapter you
write) must hand over these tables with these columns. `validate` reports
what is missing in plain words instead of failing deep inside a chart.

Order lifecycle
---------------
contract  A customer's purchase, priced and approved. Not yet loadable.
release   A part of a contract released to the loading queue at a works or
          depot. Trucks lift releases in loads.
For a contract, done_t is the tonnage released so far. For a release,
done_t is the tonnage lifted so far. open_t = qty_t - done_t.
"""

TABLES = {
    "customers": {
        "customer_id": "str", "customer_name": "str", "channel": "str",
        "region": "str", "state": "str", "town": "str",
        "lat": "float", "lon": "float", "sales_rep": "str",
        "sales_rep_email": "str", "serving_point": "str",
        "receive_open": "int", "receive_close": "int", "bays": "int",
    },
    "orders": {
        "order_id": "str", "level": "str", "contract_id": "str",
        "customer_id": "str", "product": "str", "terms": "str",
        "point_code": "str", "qty_t": "float", "done_t": "float",
        "price_ngn_t": "float", "created_at": "datetime",
        "required_by": "datetime", "closed_at": "datetime", "status": "str",
    },
    "lifts": {
        "lift_id": "str", "release_id": "str", "customer_id": "str",
        "product": "str", "point_code": "str", "qty_t": "float",
        "lifted_at": "datetime",
    },
    "demand_daily": {
        "date": "datetime", "customer_id": "str", "product": "str",
        "qty_t": "float",
    },
    "targets": {
        "customer_id": "str", "daily_target_t": "float",
    },
    "credit": {
        "customer_id": "str", "credit_limit_ngn": "float",
        "balance_ngn": "float", "on_hold": "bool", "hold_reason": "str",
    },
    "trucks": {
        "truck_id": "str", "plate": "str", "transporter": "str",
        "capacity_t": "float", "body": "str", "home_point": "str",
    },
    "recipients": {
        "name": "str", "email": "str", "role": "str", "region": "str",
        "point_code": "str",
    },
}

ORDER_LEVELS = ("contract", "release")
ORDER_STATUSES = ("OPEN", "PARTIAL", "CLOSED", "CANCELLED")
TERMS = {"DEL": "Delivered", "COL": "Collect"}


def validate(frames):
    """Return a list of problems, empty when every table looks right."""
    problems = []
    for name, cols in TABLES.items():
        df = frames.get(name)
        if df is None:
            problems.append(f"Table '{name}' is missing.")
            continue
        missing = [c for c in cols if c not in df.columns]
        if missing:
            problems.append(f"Table '{name}' has no column(s): {', '.join(missing)}.")
    orders = frames.get("orders")
    if orders is not None and "level" in orders.columns:
        bad = set(orders["level"].dropna().unique()) - set(ORDER_LEVELS)
        if bad:
            problems.append(f"orders.level has unknown values: {sorted(bad)}.")
    return problems


def coerce(frames):
    """Cast every known column to its declared type, in place."""
    import pandas as pd
    for name, cols in TABLES.items():
        df = frames.get(name)
        if df is None:
            continue
        for col, kind in cols.items():
            if col not in df.columns:
                continue
            if kind == "datetime":
                df[col] = pd.to_datetime(df[col], errors="coerce")
            elif kind == "float":
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
            elif kind == "int":
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")
            elif kind == "bool":
                df[col] = df[col].astype(str).str.lower().isin(("true", "1", "yes", "y"))
            else:
                df[col] = df[col].fillna("").astype(str)
    return frames
