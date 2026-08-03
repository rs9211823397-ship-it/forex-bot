PYTHON ?= python3

.PHONY: compile security preflight test backtest historical-backtest release-check

compile:
	$(PYTHON) -m compileall -q .

security:
	$(PYTHON) scripts/security_check.py

preflight:
	$(PYTHON) scripts/preflight.py

test:
	$(PYTHON) -m pytest -q

backtest:
	$(PYTHON) -m backtesting.run_fast_backtest

historical-backtest:
	$(PYTHON) -m backtesting.run_backtest

release-check: compile security preflight test backtest
