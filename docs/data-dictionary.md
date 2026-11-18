# Data dictionary

The dashboard reads eight tables. The synthetic generator produces all of
them; to use your own data, write them as CSV files with these columns
(`python scripts/generate_data.py` gives a complete example) and set
`MC_DATA_SOURCE=csv` and `MC_DATA_DIR` in `.env`. Missing tables or columns are
reported on the sidebar in plain words.

## Order lifecycle

```
contract (CON-...)   a customer's purchase, priced and approved
   └── release (REL-...)   part of a contract sent to the loading queue
          └── lift (LFT-...)   one truck load taken out against a release
```

For a contract, `done_t` is the tonnage released so far; for a release, the
tonnage lifted so far. Open tonnage is `qty_t - done_t`.

## customers

| Column | Type | Meaning |
| --- | --- | --- |
| customer_id | text | Unique customer key |
| customer_name | text | Trading name |
| channel | text | Distributor, Retail or Project |
| region, state, town | text | Sales region, Nigerian state, town |
| lat, lon | number | Delivery site location |
| sales_rep, sales_rep_email | text | Area sales rep |
| serving_point | text | Usual works or depot code |
| receive_open, receive_close | integer | Receiving hours (24 h clock) |
| bays | integer | Offloading bays on site |

## orders

| Column | Type | Meaning |
| --- | --- | --- |
| order_id | text | CON-... for contracts, REL-... for releases |
| level | text | contract or release |
| contract_id | text | Parent contract of a release (blank for contracts) |
| customer_id | text | Customer key |
| product | text | Product name |
| terms | text | DEL (Delivered) or COL (Collect) |
| point_code | text | Loading works or depot |
| qty_t | number | Tonnes ordered (contract) or released (release) |
| done_t | number | Tonnes released (contract) or lifted (release) |
| price_ngn_t | number | Price per tonne, NGN |
| created_at, required_by, closed_at | datetime | Dates |
| status | text | OPEN, PARTIAL, CLOSED or CANCELLED |

## lifts

`lift_id, release_id, customer_id, product, point_code, qty_t, lifted_at`: one
row per truck load taken out.

## demand_daily

`date, customer_id, product, qty_t`: tonnes ordered per customer per day,
usually 18 months or more. The demand forecast learns from it.

## targets

`customer_id, daily_target_t`: the run rate each customer is planned at.

## credit

`customer_id, credit_limit_ngn, balance_ngn, on_hold, hold_reason`.

## trucks

`truck_id, plate, transporter, capacity_t, body (Bag or Bulk), home_point`.

## recipients

`name, email, role, region, point_code`. Roles: dispatch, fleet, credit,
customer, sales (by region), point (by works or depot).
