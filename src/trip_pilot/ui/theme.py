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
        "primary": "#285e9b",
        "primary_hover": "#3475bd",
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
        "primary": "#1765b0",
        "primary_hover": "#0e528f",
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
    --trip-primary: $primary;
    --trip-primary-hover: $primary_hover;
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

/* Цвет рамок не зависит от базовой светлой темы Streamlit. */
.stApp .st-key-chat_history {
    border: 1px solid var(--trip-border) !important;
    border-radius: 0.85rem !important;
}
:is(.stApp, [data-testid="stDialog"]) hr,
[data-testid="stDialog"] [role="dialog"] {
    border-color: var(--trip-border) !important;
}

/* Списки Markdown получают цвет напрямую: Streamlit задаёт li свой textColor. */
:is(.stApp, [data-testid="stDialog"]) :is(ul, ol, li),
:is(.stApp, [data-testid="stDialog"]) li::marker {
    color: var(--trip-text) !important;
}

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

/* Отключаем анимации только у пояснения допущений, сохраняя вращение статуса. */
.stApp .st-key-assumptions_explanation [data-testid="stExpander"],
.stApp .st-key-assumptions_explanation [data-testid="stExpander"] * {
    transition: none !important;
    animation: none !important;
}
/* Фрагмент опрашивает очередь часто; его статус и ответ не должны тускнеть. */
.stApp .st-key-agent_progress [data-stale="true"],
.stApp .st-key-agent_progress [data-testid="stExpander"] summary {
    opacity: 1 !important;
    transition: none !important;
}
.stApp .st-key-agent_progress [data-testid="stExpander"] details {
    border-color: var(--trip-border) !important;
    transition: none !important;
}
/* Индикатор нарисован рамкой span: цвет текста на него не влияет. */
.stApp .st-key-agent_progress [data-testid="stExpanderIconSpinner"] {
    border-color: var(--trip-border) !important;
    border-top-color: var(--trip-text) !important;
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

/* Корзина — отдельный ограниченный по ширине bordered-container Streamlit. */
.stApp .st-key-trip_basket {
    width: 100%;
    max-width: 70rem;
    margin-inline: auto;
    background: var(--trip-surface) !important;
    border: 1.5px solid var(--trip-border) !important;
    border-radius: 1rem !important;
    box-shadow: 0 10px 30px var(--trip-shadow);
}
:is(.stApp, [data-testid="stDialog"]) .trip-basket-marker {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin-bottom: 1.25rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--trip-border);
    color: var(--trip-text) !important;
}
:is(.stApp, [data-testid="stDialog"]) .trip-basket-marker h3 {
    color: var(--trip-text) !important;
    font-size: clamp(1.3rem, 2.2vw, 1.7rem);
    margin: 0.15rem 0 0.15rem;
    line-height: 1.35;
}
:is(.stApp, [data-testid="stDialog"]) .trip-basket-kicker,
:is(.stApp, [data-testid="stDialog"]) .trip-basket-section-label {
    color: var(--trip-muted) !important;
    font-size: 0.75rem;
    font-weight: 750;
    letter-spacing: 0.055em;
    text-transform: uppercase;
}
:is(.stApp, [data-testid="stDialog"]) .trip-basket-subtitle {
    font-size: 0.95rem;
    color: var(--trip-muted) !important;
}
:is(.stApp, [data-testid="stDialog"]) .trip-basket-selected {
    display: inline-flex;
    background: var(--trip-chip-bg);
    color: var(--trip-chip-text);
    border: 1px solid var(--trip-border);
    border-radius: 999px;
    padding: 0.3rem 0.8rem;
    font-size: 0.78rem;
    font-weight: 700;
}
:is(.stApp, [data-testid="stDialog"]) .trip-detail-stack {
    display: grid;
    gap: 1.05rem;
    margin-top: 0.9rem;
    margin-bottom: 1.3rem;
}
:is(.stApp, [data-testid="stDialog"]) .trip-detail-item {
    display: flex;
    gap: 0.75rem;
    align-items: flex-start;
    min-width: 0;
}
:is(.stApp, [data-testid="stDialog"]) .trip-detail-icon {
    flex: 0 0 1.4rem;
    font-size: 1.05rem;
    line-height: 1.5;
}
:is(.stApp, [data-testid="stDialog"]) .trip-detail-body { min-width: 0; }
:is(.stApp, [data-testid="stDialog"]) .trip-detail-label {
    color: var(--trip-muted);
    font-size: 0.82rem;
    line-height: 1.45;
    margin-bottom: 0.1rem;
}
:is(.stApp, [data-testid="stDialog"]) .trip-detail-value {
    color: var(--trip-text);
    font-size: 0.95rem;
    font-weight: 540;
    line-height: 1.5;
    overflow-wrap: anywhere;
}
:is(.stApp, [data-testid="stDialog"]) .trip-detail-meta {
    color: var(--trip-muted);
    font-size: 0.83rem;
    margin-top: 0.18rem;
}
:is(.stApp, [data-testid="stDialog"]) .trip-hotel-stars { color: var(--trip-muted); }
:is(.stApp, [data-testid="stDialog"]) .trip-prices-panel {
    background: var(--trip-overlay) !important;
    border: 1px solid var(--trip-border) !important;
    border-radius: 0.85rem;
    padding: 1.15rem;
    margin-bottom: 1rem;
}
:is(.stApp, [data-testid="stDialog"]) .trip-price-row {
    display: flex;
    justify-content: space-between;
    gap: 0.8rem;
    padding-top: 0.85rem;
    color: var(--trip-text) !important;
    font-size: 0.92rem;
}
:is(.stApp, [data-testid="stDialog"]) .trip-price-row span:last-child {
    font-weight: 650;
    white-space: nowrap;
}
:is(.stApp, [data-testid="stDialog"]) .trip-price-total {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-top: 1rem;
    padding-top: 1rem;
    border-top: 1px solid var(--trip-border);
    color: var(--trip-text) !important;
    font-weight: 650;
}
:is(.stApp, [data-testid="stDialog"]) .trip-price-total strong {
    font-size: clamp(1.25rem, 2vw, 1.6rem);
    color: var(--trip-text) !important;
    white-space: nowrap;
}
:is(.stApp, [data-testid="stDialog"]) .trip-price-caption,
:is(.stApp, [data-testid="stDialog"]) .trip-price-muted {
    color: var(--trip-muted) !important;
    font-size: 0.8rem;
    margin-top: 0.4rem;
}

/* Стандартные кнопки Streamlit получают цвета темы, включая светлую вторичную. */
.stApp button[kind="secondary"],
[data-testid="stDialog"] button[kind="secondary"] {
    background: var(--trip-overlay) !important;
    color: var(--trip-text) !important;
    border: 1px solid var(--trip-border) !important;
    box-shadow: none !important;
    border-radius: 0.65rem !important;
}
.stApp button[kind="secondary"]:hover,
[data-testid="stDialog"] button[kind="secondary"]:hover {
    background: var(--trip-hover) !important;
    color: var(--trip-text) !important;
    border-color: var(--trip-accent) !important;
}
.stApp button[kind="primary"],
[data-testid="stDialog"] button[kind="primary"] {
    background: var(--trip-primary) !important;
    color: #ffffff !important;
    border: 1px solid var(--trip-primary) !important;
    border-radius: 0.65rem !important;
    box-shadow: none !important;
}
.stApp button[kind="primary"]:hover,
[data-testid="stDialog"] button[kind="primary"]:hover {
    background: var(--trip-primary-hover) !important;
    border-color: var(--trip-primary-hover) !important;
}
.stApp button[kind="primary"] p,
[data-testid="stDialog"] button[kind="primary"] p { color: #ffffff !important; }
.stApp button[kind="secondary"] p,
[data-testid="stDialog"] button[kind="secondary"] p { color: var(--trip-text) !important; }
[data-testid="stDialog"] [role="dialog"],
[data-testid="stDialog"] [data-testid="stVerticalBlock"],
[data-testid="stDialog"] [data-testid="stDialogContent"],
div[role="dialog"] {
    background: var(--trip-surface) !important;
    color: var(--trip-text) !important;
}
[data-testid="stDialog"] h1,
[data-testid="stDialog"] h2,
[data-testid="stDialog"] h3,
[data-testid="stDialog"] p,
[data-testid="stDialog"] label {
    color: var(--trip-text) !important;
}
[data-testid="stDialog"] button[kind="secondary"] {
    background: var(--trip-overlay) !important;
    color: var(--trip-text) !important;
    border: 1px solid var(--trip-border) !important;
}

/* Ответы pills — отдельный вид кнопок, у него нет kind="secondary". */
.stApp [data-testid="stButtonGroup"] button {
    background: var(--trip-chip-bg) !important;
    color: var(--trip-chip-text) !important;
    border: 1px solid var(--trip-border) !important;
}
.stApp [data-testid="stButtonGroup"] button :is(p, span) {
    color: inherit !important;
}
.stApp [data-testid="stButtonGroup"] button:hover {
    background: var(--trip-hover) !important;
}
.stApp [data-testid="stButtonGroup"] button:is(
    [aria-pressed="true"], [aria-checked="true"], [data-selected]
) {
    background: var(--trip-primary) !important;
    color: #ffffff !important;
    border-color: var(--trip-accent) !important;
}
.stApp [data-testid="stButtonGroup"] button:focus-visible {
    outline: 2px solid var(--trip-accent) !important;
    outline-offset: 2px;
}
.stApp [data-testid="stButtonGroup"] button:is(:disabled, [aria-disabled="true"], [data-disabled]) {
    background: var(--trip-overlay) !important;
    color: var(--trip-muted) !important;
    opacity: 1 !important;
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
.stApp [data-testid="stChatInput"] > div {
    border: 1px solid var(--trip-border) !important;
}
.stApp [data-testid="stChatInput"] > div:focus-within {
    border-color: var(--trip-accent) !important;
}
.stApp [data-testid="stChatInput"] textarea {
    background-color: transparent !important;
    color: var(--trip-text) !important;
    -webkit-text-fill-color: var(--trip-text) !important;
    caret-color: var(--trip-text);
    opacity: 1 !important;
}
.stApp [data-testid="stChatInput"] textarea::placeholder,
.stApp [data-testid="stChatInput"] textarea:disabled::placeholder {
    color: var(--trip-muted) !important;
    -webkit-text-fill-color: var(--trip-muted) !important;
    opacity: 1 !important;
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
@media (max-width: 760px) {
    .stApp [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .trip-card-marker),
    .stApp [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .trip-prices-panel) {
        flex-wrap: wrap !important;
    }
    .stApp [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .trip-card-marker)
      > [data-testid="stColumn"],
    .stApp [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .trip-prices-panel)
      > [data-testid="stColumn"] {
        flex: 1 1 100% !important;
        width: 100% !important;
    }
}
@media (max-width: 640px) {
    .stMainBlockContainer { padding-left: 1rem; padding-right: 1rem; }
    .stApp .trip-basket-marker { align-items: flex-start; }
    .stApp .trip-prices-panel { padding: 0.85rem; }
    .stApp .st-key-trip_basket
      [data-testid="stHorizontalBlock"]:has(.trip-prices-panel) {
        flex-wrap: wrap !important;
    }
    .stApp .st-key-trip_basket
      [data-testid="stHorizontalBlock"]:has(.trip-prices-panel) > [data-testid="stColumn"] {
        flex: 1 1 100% !important;
        width: 100% !important;
    }
}
</style>
"""
)


def theme_css(dark: bool) -> str:
    """Возвращает CSS для выбранной темы с одинаковыми цветами внутренних слоёв."""
    return STYLES.substitute(PALETTES["dark" if dark else "light"])
