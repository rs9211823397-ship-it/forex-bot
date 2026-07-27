# forex-bot
AI-powered modular Forex trading bot with risk management, backtesting, MT5 integration, and future AI signal generation.

## Release validation

Run the repository from the repository root.

- Backtest: `python -m backtesting.run_backtest`
- Research generation: `python -m backtesting.run_backtest`
- Tests: `python -m pytest -q`
- Preflight: `python scripts/preflight.py`

## Quick commands

```bash
python scripts/preflight.py
python -m pytest -q
python -m compileall .
git diff --check
python -m backtesting.run_backtest
```
