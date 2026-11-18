"""Martina Cement Plc: the fictional company this dashboard is built for.

Everything here is invented for a portfolio project. Martina Cement Plc,
its brands, plants, depots, transporters and people do not exist.
"""

COMPANY = {
    "name": "Martina Cement Plc",
    "short": "Martina Cement",
    "product": "FulfilmentIQ",
    "product_short": "FIQ",
    "tagline": "Strength you can build on",
    "founded": 2004,
    "headquarters": "Victoria Island, Lagos (fictional)",
    "website": "martina-cement.example",          # .example is reserved, never a real site
    "email_domain": "martina-cement.example",
    "about": ("Martina Cement Plc is a fictional cement and building solutions "
              "company with three integrated works and ten depots across "
              "Nigeria. It exists only to give this open-source dashboard a "
              "realistic setting."),
}

# Colour system. Teal for the brand, amber for accents, slate for text.
COLORS = {
    "primary": "#0E5E6F",
    "primary_dark": "#0B2E3B",
    "primary_light": "#E3F0F2",
    "accent": "#F2A541",
    "accent_light": "#FDF1DE",
    "ink": "#1F2A33",
    "muted": "#64748B",
    "line": "#E2E8F0",
    "bg": "#F5F7F8",
    "good": "#2F9E6B",
    "watch": "#E0A126",
    "bad": "#D1495B",
    "info": "#3A7CA5",
}

# One colour per series, used the same way on every chart.
SERIES = ["#0E5E6F", "#F2A541", "#3A7CA5", "#8C6BB1", "#2F9E6B", "#D1495B",
          "#6C8EAD", "#B5838D"]

REGIONS = ["Lagos", "South West", "South South", "South East",
           "North Central", "North West", "North East"]

REGION_COLORS = dict(zip(REGIONS, SERIES))

# Sales channels. A customer belongs to exactly one, set in its master record.
CHANNELS = ["Distributor", "Retail", "Project"]

# Product catalogue (invented brand names).
PRODUCTS = [
    {"code": "MPR425", "name": "Martina Prime 42.5R", "family": "Cement",
     "pack": "Bag 50kg", "price_ngn_t": 182000, "share": 0.34},
    {"code": "MFT425", "name": "Martina Forte 42.5N", "family": "Cement",
     "pack": "Bag 50kg", "price_ngn_t": 176000, "share": 0.22},
    {"code": "MEC325", "name": "Martina Eco 32.5R", "family": "Cement",
     "pack": "Bag 50kg", "price_ngn_t": 164000, "share": 0.24},
    {"code": "MBK425", "name": "Martina Bulk 42.5R", "family": "Cement",
     "pack": "Bulk", "price_ngn_t": 171000, "share": 0.12},
    {"code": "MTB020", "name": "Martina TileBond 20kg", "family": "Mortar",
     "pack": "Bag 20kg", "price_ngn_t": 265000, "share": 0.05},
    {"code": "MRN025", "name": "Martina Render 25kg", "family": "Mortar",
     "pack": "Bag 25kg", "price_ngn_t": 248000, "share": 0.03},
]
PRODUCT_NAMES = [p["name"] for p in PRODUCTS]
MORTAR = {p["name"] for p in PRODUCTS if p["family"] == "Mortar"}

# Works (plants) and depots. Coordinates place them near real cities so the
# map reads naturally; the facilities themselves are invented.
POINTS = [
    {"code": "W-WST", "name": "West Works", "type": "Works", "state": "Ogun",
     "lat": 7.10, "lon": 3.35, "bays": 8, "cap_tpd": 9000,
     "products": PRODUCT_NAMES},
    {"code": "W-EST", "name": "East Works", "type": "Works", "state": "Enugu",
     "lat": 6.55, "lon": 7.60, "bays": 6, "cap_tpd": 6500,
     "products": PRODUCT_NAMES},
    {"code": "W-NTH", "name": "North Works", "type": "Works", "state": "Kaduna",
     "lat": 10.42, "lon": 7.55, "bays": 6, "cap_tpd": 6000,
     "products": [n for n in PRODUCT_NAMES if n != "Martina Render 25kg"]},
    {"code": "D-LOS", "name": "Lagos Depot", "type": "Depot", "state": "Lagos",
     "lat": 6.55, "lon": 3.33, "bays": 4, "cap_tpd": 2500,
     "products": PRODUCT_NAMES[:3] + ["Martina TileBond 20kg"]},
    {"code": "D-IBD", "name": "Ibadan Depot", "type": "Depot", "state": "Oyo",
     "lat": 7.40, "lon": 3.92, "bays": 3, "cap_tpd": 1800,
     "products": PRODUCT_NAMES[:3]},
    {"code": "D-ABJ", "name": "Abuja Depot", "type": "Depot", "state": "FCT",
     "lat": 8.98, "lon": 7.42, "bays": 4, "cap_tpd": 2200,
     "products": PRODUCT_NAMES[:3] + ["Martina TileBond 20kg"]},
    {"code": "D-KAN", "name": "Kano Depot", "type": "Depot", "state": "Kano",
     "lat": 11.98, "lon": 8.55, "bays": 3, "cap_tpd": 1800,
     "products": PRODUCT_NAMES[:3]},
    {"code": "D-ONT", "name": "Onitsha Depot", "type": "Depot", "state": "Anambra",
     "lat": 6.15, "lon": 6.80, "bays": 3, "cap_tpd": 1700,
     "products": PRODUCT_NAMES[:3]},
    {"code": "D-PHC", "name": "Port Harcourt Depot", "type": "Depot", "state": "Rivers",
     "lat": 4.83, "lon": 7.02, "bays": 3, "cap_tpd": 1700,
     "products": PRODUCT_NAMES[:3] + ["Martina TileBond 20kg"]},
    {"code": "D-BEN", "name": "Benin Depot", "type": "Depot", "state": "Edo",
     "lat": 6.34, "lon": 5.63, "bays": 2, "cap_tpd": 1200,
     "products": PRODUCT_NAMES[:3]},
    {"code": "D-JOS", "name": "Jos Depot", "type": "Depot", "state": "Plateau",
     "lat": 9.90, "lon": 8.88, "bays": 2, "cap_tpd": 1000,
     "products": PRODUCT_NAMES[:3]},
    {"code": "D-MAI", "name": "Maiduguri Depot", "type": "Depot", "state": "Borno",
     "lat": 11.84, "lon": 13.15, "bays": 2, "cap_tpd": 900,
     "products": PRODUCT_NAMES[:3]},
    {"code": "D-SOK", "name": "Sokoto Depot", "type": "Depot", "state": "Sokoto",
     "lat": 13.05, "lon": 5.24, "bays": 2, "cap_tpd": 900,
     "products": PRODUCT_NAMES[:3]},
]

# Haulage partners (invented). share = fraction of the fleet.
TRANSPORTERS = [
    {"code": "KES", "name": "Kestrel Haulage", "share": 0.26, "reliability": 0.93},
    {"code": "BAO", "name": "Baobab Freight", "share": 0.22, "reliability": 0.88},
    {"code": "HMT", "name": "Harmattan Logistics", "share": 0.20, "reliability": 0.82},
    {"code": "LGL", "name": "Lagoon Line Transport", "share": 0.18, "reliability": 0.90},
    {"code": "SAV", "name": "Savanna Movers", "share": 0.14, "reliability": 0.76},
]

# Teams that own each kind of exception in the control tower.
TEAMS = {
    "dispatch": "Dispatch Desk",
    "customer": "Customer Service",
    "fleet": "Fleet Compliance",
    "sales": "Area Sales",
    "credit": "Credit Control",
}
