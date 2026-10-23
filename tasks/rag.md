# Задание: rag — база знаний, RAG, LLM-клиент

**Ветка:** `team/rag` · **Файл:** `tasks/rag.md` · **Владелец задания:** лид (правит лид, история правок внизу)

> Документ читают и человек, и ИИ-ассистент. Ассистенту: сначала прочитай `AGENTS.md`, затем этот файл целиком.
> Статус задач отмечай галочками `[x]` прямо здесь.

## Цель

Дать агенту знания, которых нет в таблицах: почему стоит ехать именно туда, что делать с детьми, правила для животных. Плюс клиент к LLM, которым пользуется вся команда. В MVP поиск идёт только полнотекстовый, без эмбеддингов. Гибрид с векторами — следующий этап.

Главное правило RAG в проекте: **база знаний — это знания, а не факты.** Цены, расписания и наличие берутся из таблиц data, а не из текстов.

## Как начать

```bash
git clone https://github.com/ostrovok-hackathon-2026/gradient-descent.git
cd gradient-descent
git switch team/rag
docker compose up --build
```

Откройте http://localhost:8080. Структура таблиц `kb_document` / `kb_chunk` описана в `migrations/versions/0001_initial.py`.

## Твоя зона

**Можно менять:** `rag/`, `data/knowledge/`, `adapters/llm/`, `adapters/db/knowledge.py` (появится после шага 0 лида), `services/memory.py`, `evals/`, тесты к ним.

**Нельзя без лида:** `domain/`, `ports.py`, `agent/events.py`, `api/`, `pyproject.toml` / `uv.lock`, чужие зоны.

## Контракты, на которые опираешься

Лид сегодня кладёт их в `main` (шаг 0). Ниже — черновик. Если он разойдётся с кодом в `main`, прав код.

```python
# ports.py — ты реализуешь эти два порта
class KnowledgeBase(Protocol):
    async def search(self, query: str, *, destination: str | None = None,
                     doc_type: str | None = None, limit: int = 5) -> list[KnowledgeHit]: ...

class LLM(Protocol):
    enabled: bool                                     # False, если ключа нет
    async def complete(self, messages: list[dict[str, str]]) -> str: ...
    async def structured(self, messages: list[dict[str, str]], schema: type[T]) -> T: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

# KnowledgeHit: text, title, heading_path, source, score
```

Зависимости `openai`, `pyyaml`, `tenacity` лид добавляет в шаге 0. Сам `uv.lock` не трогай.

---

## Задачи MVP

### 1. Тексты базы знаний — можно начинать сразу
Для каждого из 12 направлений в `data/reference/destinations.json` создай файл `data/knowledge/<slug>.md`:

```markdown
---
title: Анталья
doc_type: guide
destination: antalya
months: [5, 6, 7, 8, 9, 10]
tags: [sea, kids, all_inclusive]
source: synthetic
---
## Почему ехать
## Когда лучше
## С детьми
## С животными
## Минусы и риски
```

- 150–300 слов на направление, на русском.
- Тексты можно генерировать ИИ, но **без конкретных цен, расписаний, номеров рейсов и названий отелей**: только качественные описания. Всё сгенерированное помечается `source: synthetic`.

Готово, когда:
- [ ] 12 файлов, у всех валидный frontmatter (проверяется тестом)

### 2. LLM-адаптер (`adapters/llm/openai_compat.py`) — можно начинать сразу
- Реализуй порт `LLM` на пакете `openai` (`AsyncOpenAI`, `base_url=LLM_BASE_URL`).
- Настройки бери из `trip_pilot.config.Settings`: `llm_base_url`, `llm_api_key`, `llm_model`, `embeddings_model`, `llm_max_concurrency`.
- Общий `asyncio.Semaphore(llm_max_concurrency)`, таймаут 30 с, 2 повтора с экспоненциальной паузой (`tenacity`) только на сетевых ошибках и 429/5xx.
- `structured()` просит у модели JSON и валидирует его Pydantic-схемой; при невалидном ответе делает 1 повтор.
- Нет ключа → `NullLLM` с `enabled=False`, его методы бросают `LLMUnavailable`. Остальные проверяют `enabled` и уходят в режим без LLM.
- Фабрика `make_llm(settings) -> LLM`.

Готово, когда:
- [ ] юнит-тесты без сети: `NullLLM`; повторы на подменённом клиенте; валидация `structured`
- [ ] ключ ни в каком виде не попадает в логи

### 3. Индексация (`rag/index.py`, `rag/chunking.py`)
- `build_index(session, knowledge_dir)` уже вызывается из bootstrap. Сделай в нём настоящую загрузку.
- Читай frontmatter через `yaml.safe_load`. Делай фрагменты по заголовкам `##`, `heading_path` вида «Анталья › С детьми».
- `kb_document.content_hash` — sha256 содержимого. Документ не изменился → пропусти; изменился → замени его фрагменты.
- `meta` фрагмента = `{"months": [...], "tags": [...]}`, `destination_id` — по slug.
- Эмбеддинги в MVP **не считаем**, поле `embedding` остаётся `NULL`.

Готово, когда:
- [ ] после `docker compose up` в логе bootstrap видно «документов: 12, фрагментов: N»
- [ ] повторный `docker compose run --rm bootstrap` ничего не дублирует (проверь в pgAdmin)
- [ ] юнит-тесты на разбиение по заголовкам и разбор frontmatter

### 4. Полнотекстовый поиск (`rag/retriever.py`)
- Реализуй `KnowledgeBase.search` на Postgres: `websearch_to_tsquery('russian', :q)`, `ts_rank_cd`, фильтры по `destination` и `doc_type` (через `kb_document`), `limit`.
- Пустой или бессмысленный запрос → пустой список, не исключение.
- Собери класс-адаптер, который лид подключит в `api/main.py`.

Готово, когда:
- [ ] `search("с детьми", destination="antalya")` возвращает фрагмент из раздела «С детьми»
- [ ] интеграционная проверка описана в PR: команды и ожидаемый вывод

---

## После MVP (детализируется позже)
- эмбеддинги при bootstrap (если есть ключ) + гибридный поиск: вектор + полнотекст + RRF; MMR; цитаты `[S1]`;
- правила и политики: животные, документы на ребёнка, багаж, ранний заезд;
- синтетические отзывы и аспектные оценки отелей (дети, шум, пляж, еда) для скоринга data;
- память между сессиями (`services/memory.py`);
- eval-набор (`evals/cases.yaml`) и метрики: доля доведённых сценариев, число уточнений, время до первой рекомендации, Recall@5.

## Как сдавать работу
- Коммиты делает человек после просмотра diff. Формат: Conventional Commits на русском, только суть, например `feat(rag): добавить полнотекстовый поиск по базе знаний`.
- Перед PR выполни проверку из `AGENTS.md`. PR `team/rag` → `main` открывай, как только задача готова, не копи. Слияние обычным merge commit.
- Не реже раза в день: `git pull origin main`.

## Правки лида

| Дата | Что изменено |
|---|---|
| 2026-10-23 | первая версия |
