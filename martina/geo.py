"""Nigerian states, sales regions and towns used to place synthetic customers.

Town coordinates are approximate city centres. State outlines in
assets/ng_states.geojson come from Natural Earth (public domain).
"""
import json
import math
from functools import lru_cache

from .config import ROOT

STATE_REGION = {
    "Lagos": "Lagos",
    **{s: "South West" for s in ("Ogun", "Oyo", "Osun", "Ondo", "Ekiti")},
    **{s: "South South" for s in ("Edo", "Delta", "Rivers", "Bayelsa",
                                  "Akwa Ibom", "Cross River")},
    **{s: "South East" for s in ("Anambra", "Enugu", "Imo", "Abia", "Ebonyi")},
    **{s: "North Central" for s in ("FCT", "Niger", "Kogi", "Kwara", "Benue",
                                    "Nasarawa", "Plateau")},
    **{s: "North West" for s in ("Kano", "Kaduna", "Katsina", "Sokoto",
                                 "Zamfara", "Kebbi", "Jigawa")},
    **{s: "North East" for s in ("Bauchi", "Borno", "Yobe", "Gombe",
                                 "Adamawa", "Taraba")},
}

# (town, state, lat, lon, weight). Weight scales how many customers land there.
TOWNS = [
    ("Ikeja", "Lagos", 6.60, 3.35, 5), ("Lekki", "Lagos", 6.45, 3.55, 5),
    ("Ikorodu", "Lagos", 6.62, 3.51, 4), ("Badagry", "Lagos", 6.42, 2.88, 2),
    ("Epe", "Lagos", 6.58, 3.98, 2), ("Ojo", "Lagos", 6.46, 3.18, 3),
    ("Abeokuta", "Ogun", 7.15, 3.35, 3), ("Ijebu-Ode", "Ogun", 6.82, 3.92, 2),
    ("Ota", "Ogun", 6.68, 3.23, 3), ("Ilaro", "Ogun", 6.89, 3.02, 1),
    ("Ibadan", "Oyo", 7.38, 3.94, 5), ("Ogbomoso", "Oyo", 8.13, 4.24, 2),
    ("Oyo", "Oyo", 7.85, 3.93, 1), ("Iseyin", "Oyo", 7.97, 3.60, 1),
    ("Osogbo", "Osun", 7.77, 4.56, 2), ("Ile-Ife", "Osun", 7.47, 4.56, 2),
    ("Ilesa", "Osun", 7.62, 4.74, 1), ("Akure", "Ondo", 7.25, 5.19, 2),
    ("Ondo", "Ondo", 7.09, 4.84, 1), ("Owo", "Ondo", 7.20, 5.59, 1),
    ("Ado-Ekiti", "Ekiti", 7.62, 5.22, 2), ("Ikere", "Ekiti", 7.50, 5.23, 1),
    ("Benin City", "Edo", 6.34, 5.62, 4), ("Auchi", "Edo", 7.07, 6.27, 1),
    ("Ekpoma", "Edo", 6.75, 6.14, 1), ("Warri", "Delta", 5.52, 5.75, 3),
    ("Asaba", "Delta", 6.20, 6.73, 2), ("Sapele", "Delta", 5.89, 5.68, 1),
    ("Ughelli", "Delta", 5.49, 5.99, 1), ("Port Harcourt", "Rivers", 4.82, 7.03, 4),
    ("Bonny", "Rivers", 4.45, 7.17, 1), ("Omoku", "Rivers", 5.34, 6.66, 1),
    ("Yenagoa", "Bayelsa", 4.92, 6.26, 2), ("Uyo", "Akwa Ibom", 5.04, 7.93, 3),
    ("Eket", "Akwa Ibom", 4.65, 7.93, 1), ("Ikot Ekpene", "Akwa Ibom", 5.18, 7.71, 1),
    ("Calabar", "Cross River", 4.96, 8.33, 2), ("Ogoja", "Cross River", 6.66, 8.80, 1),
    ("Ikom", "Cross River", 5.96, 8.71, 1), ("Onitsha", "Anambra", 6.14, 6.79, 4),
    ("Awka", "Anambra", 6.21, 7.07, 2), ("Nnewi", "Anambra", 6.02, 6.91, 2),
    ("Enugu", "Enugu", 6.45, 7.51, 3), ("Nsukka", "Enugu", 6.86, 7.40, 1),
    ("Owerri", "Imo", 5.48, 7.03, 3), ("Okigwe", "Imo", 5.83, 7.35, 1),
    ("Orlu", "Imo", 5.79, 7.04, 1), ("Aba", "Abia", 5.11, 7.37, 3),
    ("Umuahia", "Abia", 5.53, 7.49, 2), ("Abakaliki", "Ebonyi", 6.32, 8.11, 2),
    ("Afikpo", "Ebonyi", 5.89, 7.94, 1), ("Abuja", "FCT", 9.06, 7.49, 5),
    ("Kubwa", "FCT", 9.15, 7.32, 2), ("Gwagwalada", "FCT", 8.94, 7.08, 2),
    ("Minna", "Niger", 9.61, 6.55, 2), ("Bida", "Niger", 9.08, 6.01, 1),
    ("Suleja", "Niger", 9.18, 7.18, 2), ("Lokoja", "Kogi", 7.80, 6.74, 2),
    ("Anyigba", "Kogi", 7.49, 7.17, 1), ("Kabba", "Kogi", 7.83, 6.07, 1),
    ("Ilorin", "Kwara", 8.50, 4.55, 3), ("Offa", "Kwara", 8.15, 4.72, 1),
    ("Makurdi", "Benue", 7.73, 8.54, 2), ("Otukpo", "Benue", 7.19, 8.13, 1),
    ("Lafia", "Nasarawa", 8.49, 8.52, 1), ("Keffi", "Nasarawa", 8.85, 7.87, 2),
    ("Jos", "Plateau", 9.90, 8.86, 2), ("Bukuru", "Plateau", 9.79, 8.87, 1),
    ("Kano", "Kano", 12.00, 8.52, 5), ("Wudil", "Kano", 11.80, 8.84, 1),
    ("Kaduna", "Kaduna", 10.52, 7.44, 4), ("Zaria", "Kaduna", 11.09, 7.71, 2),
    ("Kafanchan", "Kaduna", 9.58, 8.29, 1), ("Katsina", "Katsina", 12.99, 7.60, 2),
    ("Funtua", "Katsina", 11.52, 7.31, 1), ("Sokoto", "Sokoto", 13.06, 5.24, 2),
    ("Gusau", "Zamfara", 12.16, 6.66, 1), ("Birnin Kebbi", "Kebbi", 12.45, 4.20, 1),
    ("Dutse", "Jigawa", 11.76, 9.34, 1), ("Hadejia", "Jigawa", 12.45, 10.04, 1),
    ("Bauchi", "Bauchi", 10.31, 9.84, 2), ("Azare", "Bauchi", 11.68, 10.19, 1),
    ("Maiduguri", "Borno", 11.83, 13.15, 2), ("Biu", "Borno", 10.61, 12.19, 1),
    ("Damaturu", "Yobe", 11.75, 11.96, 1), ("Potiskum", "Yobe", 11.71, 11.08, 1),
    ("Gombe", "Gombe", 10.29, 11.17, 2), ("Yola", "Adamawa", 9.20, 12.48, 2),
    ("Mubi", "Adamawa", 10.27, 13.27, 1), ("Jalingo", "Taraba", 8.89, 11.36, 1),
    ("Wukari", "Taraba", 7.87, 9.78, 1),
]

NIGERIA_CENTER = {"lat": 9.05, "lon": 8.2}
NIGERIA_BOUNDS = {"west": 2.6, "east": 14.7, "south": 4.2, "north": 13.95}


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km. Works on scalars or numpy arrays."""
    import numpy as np
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def km(a_lat, a_lon, b_lat, b_lon):
    """Scalar distance in km (plain math, no numpy)."""
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


@lru_cache(maxsize=1)
def states_geojson():
    with open(ROOT / "assets" / "ng_states.geojson", encoding="utf-8") as fh:
        return json.load(fh)
