# Learnings

## [2026-04-19] Session start
- Project: auto-image-pipeline (Python/Flask)
- venv: `source .venv/bin/activate`
- aip cmd: `PYTHONPATH=. python -m pipeline.__main__`
- Tests: `PYTHONPATH=. .venv/bin/pytest tests/ -q` (baseline: 211 passed)
- DB: SQLite, create_all(), no Alembic
- CSS: external style.css only, NO <style> inline
- Frontend: pure Jinja2 + vanilla JS, NO frameworks
- LLM: Gemini API (see brief_generator.py for pattern)
- All models in pipeline/models/, all layers in pipeline/layers/
- Web app: pipeline/web/app.py (Flask), templates in pipeline/web/templates/
