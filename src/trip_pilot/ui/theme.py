"""Палитра и стили интерфейса TripPilot без зависимости от Streamlit."""

from string import Template


PALETTES = {
    "dark": {
        "bg": "#101827",
        "surface": "#172337",
        "overlay": "#1b2d46",
        "hover": "#263b59",
        "text": "#f1f5fb",
        "muted": "#bac8dc",
        "border": "#6682ac",
        "accent": "#79bdff",
        "chip_bg": "#223853",
        "chip_text": "#e1efff",
        "shadow": "rgba(0, 0, 0, 0.28)",
    },
    "light": {
        "bg": "#f5f8fc",
        "surface": "#ffffff",
        "overlay": "#f0f5fb",
        "hover": "#e4edf8",
        "text": "#17243a",
        "muted": "#52647c",
        "border": "#b9c9dc",
        "accent": "#1765b0",
        "chip_bg": "#e7f0fb",
        "chip_text": "#204771",
        "shadow": "rgba(24, 49, 81, 0.10)",
    },
}


STYLES = Template(
    """
<style>
:root {
    --trip-bg: $bg;
    --trip-surface: $surface;
    --trip-overlay: $overlay;
    --trip-hover: $hover;
    --trip-text: $text;
    --trip-muted: $muted;
    --trip-border: $border;
    --trip-accent: $accent;
    --trip-chip-bg: $chip_bg;
    --trip-chip-text: $chip_text;
    --trip-shadow: $shadow;
}
/* Ограничиваем максимальную ширину, не задавая фиксированную ширину карточек. */
.stMainBlockContainer {
    width: 100%;
    max-width: 78rem;
}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
    background: var(--trip-bg) !important;
    color: var(--trip-text);
}
.stApp h1, .stApp h2, .stApp h3,
.stApp p, .stApp label,
.stApp [data-testid="stMetricValue"],
.stApp [data-testid="stMetricLabel"] {
    color: var(--trip-text);
}
.stApp [data-testid="stCaptionContainer"], .stApp small {
    color: var(--trip-muted) !important;
}
.stApp a { color: var(--trip-accent); }

/* Рамка располагается на самой колонке с border=True.
   Никаких вложенных border-wrapper и селекторов их внутренней структуры. */
.stApp [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .trip-card-marker) {
    align-items: stretch !important;
}
.stApp [data-testid="stColumn"]:has(.trip-card-marker) {
    display: flex !important;
    flex-direction: column !important;
    align-self: stretch !important;
    box-sizing: border-box !important;
    min-width: 0;
    border: 2px solid var(--trip-border) !important;
    border-radius: 0.9rem !important;
    background: var(--trip-surface) !important;
    box-shadow: 0 0 0 1px var(--trip-shadow), 0 6px 20px var(--trip-shadow) !important;
    overflow: hidden;
}
.stApp [data-testid="stColumn"]:has(.trip-card-marker)
  > [data-testid="stVerticalBlock"] {
    flex: 1 1 auto !important;
    display: flex !important;
    flex-direction: column !important;
    min-height: 100%;
    width: 100%;
}
/* Кнопка у нижней кромки независимо от длины преимуществ и рисков. */
.stApp [data-testid="stColumn"]:has(.trip-card-marker)
  [data-testid="stElementContainer"]:has(> [data-testid="stButton"]) {
    margin-top: auto !important;
}
.stApp .trip-card-marker {
    color: var(--trip-text) !important;
    font-size: 1.55rem;
    font-weight: 700;
    line-height: 1.35;
    margin: 0;
}
.stApp [data-testid="stColumn"]:has(.trip-card-marker) button[kind="secondary"] {
    background: var(--trip-overlay) !important;
    color: var(--trip-text) !important;
    border: 1px solid var(--trip-border) !important;
}
.stApp [data-testid="stColumn"]:has(.trip-card-marker) button[kind="secondary"]:hover {
    background: var(--trip-hover) !important;
}
.stApp [data-testid="stColumn"]:has(.trip-card-marker) button[kind="primary"]:disabled {
    background: var(--trip-overlay) !important;
    color: var(--trip-text) !important;
    border: 1px solid var(--trip-border) !important;
    opacity: 1 !important;
}

/* Настоящие чипы, а не Markdown code с белой подложкой. */
.stApp .trip-chip-list {
    display: flex;
    flex-wrap: wrap;
    gap: 0.55rem;
    margin: 0.55rem 0 1rem;
}
.stApp .trip-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.25rem 0.65rem;
    border: 1px solid var(--trip-border) !important;
    border-radius: 999px;
    background: var(--trip-chip-bg) !important;
    color: var(--trip-chip-text) !important;
    font-size: 0.88rem;
    font-weight: 500;
}

/* Expander и раскрытая панель, включая summary и все вложенные подложки. */
.stApp [data-testid="stExpander"] {
    background: var(--trip-overlay) !important;
    color: var(--trip-text) !important;
    border: 1.5px solid var(--trip-border) !important;
    border-radius: 0.85rem !important;
    overflow: hidden;
}
.stApp [data-testid="stExpander"] details,
.stApp [data-testid="stExpander"] details > summary,
.stApp [data-testid="stExpander"] [data-testid="stExpanderDetails"],
.stApp [data-testid="stExpander"] [data-testid="stExpanderDetails"] > div {
    background: var(--trip-overlay) !important;
    color: var(--trip-text) !important;
}
.stApp [data-testid="stExpander"] details > summary:hover {
    background: var(--trip-hover) !important;
}
.stApp [data-testid="stExpander"] summary,
.stApp [data-testid="stExpander"] summary p,
.stApp [data-testid="stExpander"] summary svg {
    color: var(--trip-text) !important;
    fill: currentColor;
}
/* Toast/всплывающие подсказки могут рендериться вне .stApp (в portal). */
[data-testid="stToast"], [data-baseweb="popover"], [role="tooltip"] {
    background-color: var(--trip-overlay) !important;
    color: var(--trip-text) !important;
    border-color: var(--trip-border) !important;
}

/* Поле ввода чата: все вложенные BaseWeb-слои одного цвета. */
.stApp [data-testid="stChatMessage"],
.stApp [data-testid="stChatInput"],
.stApp [data-testid="stChatInput"] > div,
.stApp [data-testid="stChatInput"] [data-baseweb="textarea"],
.stApp [data-testid="stChatInput"] [data-baseweb="base-input"] {
    background-color: var(--trip-surface) !important;
    color: var(--trip-text) !important;
    border-color: var(--trip-border) !important;
}
.stApp [data-testid="stChatInput"],
.stApp [data-testid="stChatInput"] > div,
.stApp [data-testid="stChatInput"] [data-baseweb="textarea"],
.stApp [data-testid="stChatInput"] [data-baseweb="base-input"] {
    border-radius: 0.85rem !important;
    box-shadow: none !important;
}
.stApp [data-testid="stChatInput"] textarea {
    background-color: transparent !important;
    color: var(--trip-text) !important;
    caret-color: var(--trip-text);
}
.stApp [data-testid="stChatInput"] textarea::placeholder {
    color: var(--trip-muted) !important;
    opacity: 1;
}
.stApp [data-testid="stChatInput"] button {
    background: transparent !important;
    color: var(--trip-accent) !important;
}
.stApp [data-testid="stBottom"],
.stApp [data-testid="stBottomBlockContainer"],
.stApp [data-testid="stChatInputContainer"] {
    background: var(--trip-bg) !important;
}
@media (max-width: 640px) {
    .stMainBlockContainer { padding-left: 1rem; padding-right: 1rem; }
}
</style>
"""
)


def theme_css(dark: bool) -> str:
    """Возвращает CSS для выбранной темы с одинаковыми цветами внутренних слоёв."""
    return STYLES.substitute(PALETTES["dark" if dark else "light"])
