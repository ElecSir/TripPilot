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
    assert '[data-testid="stColumn"]:has(.trip-card-marker)' in css


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


def test_basket_border_and_buttons_use_theme_colors() -> None:
    for dark in (True, False):
        css = theme_css(dark)
        assert '.stApp .st-key-trip_basket {' in css
        assert 'max-width: 70rem' in css
        assert 'background: var(--trip-surface) !important' in css
        assert 'button[kind="secondary"]' in css
        assert 'background: var(--trip-overlay) !important' in css
        assert 'button[kind="primary"]' in css
        assert 'background: var(--trip-primary) !important' in css
        assert '.trip-prices-panel' in css
        assert '.trip-price-total' in css
        assert ':is(.stApp, [data-testid="stDialog"])' in css


def test_theme_buttons_have_distinct_primary_and_secondary_backgrounds() -> None:
    for palette in PALETTES.values():
        assert palette["primary"] != palette["overlay"]
        assert palette["primary_hover"] != palette["primary"]
        assert palette["primary"] != palette["bg"]


def test_lists_and_markers_use_theme_text_color() -> None:
    for dark in (True, False):
        css = theme_css(dark)
        assert ':is(.stApp, [data-testid="stDialog"]) :is(ul, ol, li),' in css
        assert 'li::marker {\n    color: var(--trip-text) !important;' in css


def test_expander_theme_changes_have_no_animation() -> None:
    for dark in (True, False):
        css = theme_css(dark)
        assert (
            '.st-key-assumptions_explanation [data-testid="stExpander"] * {\n'
            '    transition: none !important;\n    animation: none !important;'
        ) in css
        assert '\n.stApp [data-testid="stExpander"] * {' not in css


def test_progress_does_not_dim_during_fragment_polls_or_disable_spinner() -> None:
    for dark in (True, False):
        css = theme_css(dark)
        assert '.st-key-agent_progress [data-stale="true"]' in css
        assert 'summary {\n    opacity: 1 !important;\n    transition: none !important;' in css
        assert (
            '[data-testid="stExpanderIconSpinner"] {\n'
            '    border-color: var(--trip-border) !important;\n'
            '    border-top-color: var(--trip-text) !important;'
        ) in css
        for rule in css.split("}"):
            if "st-key-agent_progress" in rule:
                assert "animation:" not in rule


def test_answer_buttons_use_theme_for_all_states() -> None:
    for dark in (True, False):
        css = theme_css(dark)
        assert '[data-testid="stButtonGroup"] button {' in css
        assert 'background: var(--trip-chip-bg) !important;' in css
        assert '[data-testid="stButtonGroup"] button :is(p, span)' in css
        assert '[data-testid="stButtonGroup"] button:hover' in css
        assert '[aria-pressed="true"], [aria-checked="true"], [data-selected]' in css
        assert '[data-testid="stButtonGroup"] button:focus-visible' in css
        assert 'button:is(:disabled, [aria-disabled="true"], [data-disabled])' in css


def test_placeholder_keeps_its_color_when_chat_input_is_disabled() -> None:
    for dark in (True, False):
        css = theme_css(dark)
        assert 'textarea:disabled::placeholder {' in css
        assert '-webkit-text-fill-color: var(--trip-text) !important;' in css
        assert (
            'color: var(--trip-muted) !important;\n'
            '    -webkit-text-fill-color: var(--trip-muted) !important;\n'
            '    opacity: 1 !important;'
        ) in css


def test_native_container_borders_follow_theme_and_focus() -> None:
    for dark in (True, False):
        css = theme_css(dark)
        assert '.stApp .st-key-chat_history {\n    border: 1px solid var(--trip-border)' in css
        assert '.stApp .st-key-trip_basket {' in css
        assert 'stVerticalBlockBorderWrapper' not in css
        assert (
            '[data-testid="stChatInput"] > div {\n    border: 1px solid var(--trip-border)'
        ) in css
        assert (
            '> div:focus-within {\n    border-color: var(--trip-accent) !important;'
        ) in css
        assert ':is(.stApp, [data-testid="stDialog"]) hr,' in css
