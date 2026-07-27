PYTHON ?= python3

.PHONY: preflight test backtest release-check

preflight:
	$(PYTHON) scripts/preflight.py

test:
	$(PYTHON) -m pytest -q

backtest:
	$(PYTHON) -m backtesting.run_backtest

release-check: preflight test backtest
