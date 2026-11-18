def test_every_page_renders(feed):
    from martina.ui.app import _page_modules, create_app
    app = create_app()
    assert app.layout is not None
    for path, mod in _page_modules().items():
        assert mod.layout() is not None, path


def test_logistics_tabs_render(feed):
    from martina.ui.pages import logistics as L
    for tab, _, _ in L.TABS:
        assert L._tab(tab) is not None


def test_excel_report(store):
    from martina.export import workbook
    data = workbook()
    assert data[:2] == b"PK" and len(data) > 10_000
