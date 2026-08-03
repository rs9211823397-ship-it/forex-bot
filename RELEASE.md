# Release Notes

## Platform Foundation v1.0

### Validation commands
- Backtest: `python -m backtesting.run_backtest`
- Research generation: `python -m backtesting.run_backtest`
- Tests: `python -m pytest -q`
- Preflight: `python scripts/preflight.py`

### Release checklist
1. Run `python scripts/preflight.py`
2. Run `python -m pytest -q`
3. Run `python -m compileall .`
4. Run `git diff --check`
5. Run `python -m backtesting.run_backtest`
