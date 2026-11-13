"""Interface pieces reused by the tabs."""


def test_format_size(ui):
    assert ui.widgets.format_size(500) == "500 B"
    assert ui.widgets.format_size(1536) == "1,5 KB"
    assert ui.widgets.format_size(5 * 1024 ** 3) == "5,0 GB"
