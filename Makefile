PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: install test lint pipeline app

install:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest -v

lint:
	$(PY) -m ruff check .

pipeline:
	$(PY) -m cac40val.pipeline

app:
	$(PY) -m streamlit run app/streamlit_app.py
