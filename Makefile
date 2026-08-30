.PHONY: setup setup-paid smoke report estimate preflight benchmark

PYTHON ?= python3

setup:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m unittest discover -s tests

setup-paid:
	.venv/bin/python -m pip install "headroom-ai[proxy]"

smoke:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -v
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.runner.public_cli estimate >/dev/null

report:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/render_published_report.py

estimate:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.runner.public_cli estimate

preflight:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.runner.public_cli preflight

benchmark:
	@echo "Refusing implicit paid execution. Run the explicit command documented in docs/REPRODUCTION.md."
	@exit 2
