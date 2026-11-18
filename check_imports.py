"""Checks the project in two steps and stops at the first problem.

1. Every file is in the right folder and complete (its line count matches).
2. Every module imports, in the order they depend on each other.

Run from the project root:  python check_imports.py
"""
import importlib
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

EXPECTED_LINES = {
    ".github/workflows/tests.yml": 15,
    "assets/app.js": 9,
    "assets/favicon.svg": 8,
    "assets/logo-mark.svg": 8,
    "assets/logo.svg": 11,
    "assets/ng_states.geojson": 1,
    "assets/style.css": 257,
    "martina/__init__.py": 0,
    "martina/ai/__init__.py": 0,
    "martina/ai/assistant.py": 563,
    "martina/ai/llm.py": 39,
    "martina/alerts/__init__.py": 0,
    "martina/alerts/notify.py": 113,
    "martina/app_server.py": 21,
    "martina/brand.py": 130,
    "martina/cache.py": 60,
    "martina/config.py": 81,
    "martina/data/__init__.py": 0,
    "martina/data/schema.py": 101,
    "martina/data/store.py": 113,
    "martina/data/synthetic.py": 351,
    "martina/export.py": 85,
    "martina/geo.py": 103,
    "martina/logistics/__init__.py": 0,
    "martina/logistics/clock.py": 81,
    "martina/logistics/feed.py": 332,
    "martina/logistics/learn.py": 298,
    "martina/logistics/reports.py": 96,
    "martina/logistics/rules.py": 313,
    "martina/logistics/sim.py": 402,
    "martina/logistics/world.py": 87,
    "martina/orderbook/__init__.py": 0,
    "martina/orderbook/analytics.py": 210,
    "martina/orderbook/forecast.py": 181,
    "martina/orderbook/operations.py": 162,
    "martina/orderbook/pipeline.py": 115,
    "martina/ui/__init__.py": 0,
    "martina/ui/app.py": 266,
    "martina/ui/charts.py": 74,
    "martina/ui/components.py": 149,
    "martina/ui/maps.py": 79,
    "martina/ui/pages/__init__.py": 0,
    "martina/ui/pages/analytics.py": 177,
    "martina/ui/pages/assistant.py": 150,
    "martina/ui/pages/executive.py": 111,
    "martina/ui/pages/lg_views.py": 443,
    "martina/ui/pages/logistics.py": 671,
    "martina/ui/pages/operations.py": 236,
    "martina/ui/theme.py": 89,
    "pytest.ini": 6,
    "requirements.txt": 17,
    "run.py": 26,
    "scripts/generate_data.py": 22,
    "tests/conftest.py": 30,
    "tests/test_app.py": 18,
    "tests/test_assistant.py": 29,
    "tests/test_clean.py": 33,
    "tests/test_data.py": 33,
    "tests/test_forecast.py": 10,
    "tests/test_logistics.py": 64,
    "tests/test_orderbook.py": 48,
    "wsgi.py": 5,
}

ORDER = [
    "martina.brand", "martina.config", "martina.geo", "martina.cache",
    "martina.data.schema", "martina.data.synthetic", "martina.data.store",
    "martina.orderbook.pipeline", "martina.orderbook.analytics",
    "martina.orderbook.operations", "martina.orderbook.forecast",
    "martina.alerts.notify", "martina.ai.llm",
    "martina.logistics.clock", "martina.logistics.world", "martina.logistics.sim",
    "martina.logistics.learn", "martina.logistics.reports", "martina.logistics.feed",
    "martina.logistics.rules",
    "martina.ai.assistant", "martina.export",
    "martina.ui.theme", "martina.ui.components", "martina.ui.charts", "martina.ui.maps",
    "martina.ui.pages.analytics", "martina.ui.pages.executive", "martina.ui.pages.operations",
    "martina.ui.pages.lg_views", "martina.ui.pages.logistics", "martina.ui.pages.assistant",
    "martina.ui.app", "martina.app_server",
]

print("Step 1: files present and complete\n")
problems = []
for rel, want in EXPECTED_LINES.items():
    p = ROOT / rel
    if not p.exists():
        problems.append(f"MISSING     {rel}")
        continue
    have = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
    if abs(have - want) > 2:
        problems.append(f"INCOMPLETE  {rel}: {have} lines, should be {want}. Copy it again in full.")
if problems:
    print("\n".join(problems))
    print(f"\nFix the {len(problems)} file(s) above, then run this again.")
    raise SystemExit(1)
print(f"All {len(EXPECTED_LINES)} files are present and complete.\n")

print("Step 2: imports\n")
for i, name in enumerate(ORDER, 1):
    try:
        importlib.import_module(name)
        print(f"{i:2d}. ok      {name}")
    except Exception as e:
        print(f"{i:2d}. FAILED  {name}")
        print(f"\n    {type(e).__name__}: {e}\n")
        traceback.print_exc(limit=2)
        raise SystemExit(1)
print("\nEvery file is in place. Now run run.py.")
