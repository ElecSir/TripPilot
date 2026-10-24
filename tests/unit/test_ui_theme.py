"""Проверки цветовых палитр, границ и адаптивных селекторов UI."""

from trip_pilot.ui.theme import PALETTES, theme_css


def test_themes_have_distinct_surface_and_background() -> None:
    for mode in ("dark", "light"):
        palette = PALETTES[mode]
        assert palette["bg"] != palette["surface"]
        assert palette["border"] != palette["surface"]
        assert palette["chip_bg"] != "#ffffff" or mode == "light"


def test_css_targets_native_bordered_columns_and_button_alignment() -> None:
    css = theme_css(True)
    assert '[data-testid="stColumn"]:has(.trip-card-marker)' in css
    assert 'border: 2px solid var(--trip-border) !important' in css
    assert 'margin-top: auto !important' in css
    assert '[data-testid="stVerticalBlockBorderWrapper"]' not in css


def test_dark_expander_and_chips_share_theme_variables() -> None:
    css = theme_css(True)
    assert 'data-testid="stExpanderDetails"' in css
    assert 'background: var(--trip-overlay) !important' in css
    assert '.trip-chip {' in css
    assert 'background: var(--trip-chip-bg) !important' in css
    assert PALETTES["dark"]["chip_bg"] in css


def test_light_and_dark_theme_have_different_colors() -> None:
    light = theme_css(False)
    dark = theme_css(True)
    assert light != dark
    assert PALETTES["light"]["bg"] in light
    assert PALETTES["dark"]["bg"] in dark
    assert "$bg" not in light and "$bg" not in dark
