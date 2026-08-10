# AAQTS End-to-End Audit Remediation

Audit baseline: `63400c653f98a3fd9a93a27a003404ebb570b91c` on
`agent/single-account-telegram`.

## Measured decision selectivity

A deterministic 700-decision, mixed-regime M15 replay was run with the VPS
policy (`ADX=12`, score `35`, one confirmation, quality `35`, regime `35`).

| Result | Before contextual repair | After repair |
| --- | ---: | ---: |
| Actionable BUY/SELL | 9.57% | 20.00% |
| HOLD | 90.43% | 80.00% |
| Candidate acceptance | not recorded | 24.73% |

The repaired policy produced 140 actionable decisions out of 700. An 80% HOLD
rate is therefore not evidence that the engine cannot trade; on nine symbols
it is already permissive enough for demo forward testing. Genuine
risk/execution gates are intentionally excluded from this strategy-only rate.

Exclusive remaining HOLD causes after repair:

| Gate | Share of HOLDs | Policy |
| --- | ---: | --- |
| RSI opposing extreme | 31.61% | Keep: veto only at an extreme against entry |
| H1 direction conflict | 17.86% | Keep: one binary direction check |
| Unsafe/unclear regime | 15.89% | Keep: volatility/data context safety |
| No primary direction | 12.14% | Keep: 2-of-3 vote did not form |
| Structure conflict | 12.14% | Keep: opposite structure, not extra confirmation |
| Breakout not confirmed | 6.43% | Keep: prevents false range breaks |
| Contextual gate | 3.75% | Keep only true HTF/structure conflict; aligned location is advisory |
| Quality threshold | 0.18% | Keep |

## Defects fixed

1. **Stale equity peak blocked every entry.** Runtime risk state is now bound
   to execution mode, MT5 login, server, and risk-baseline epoch. A stale
   `1000` peak cannot poison a different `96.69` account/session, while a real
   later drawdown for the same identity is still preserved.
2. **Contextual softening was unreachable.** The contextual engine now returns
   explicit HTF and structure alignment codes. Only an aligned invalid
   location is advisory; neutral/opposite context still fails closed.
3. **Range routing duplicated RSI/Bollinger confirmation.** RANGE now uses the
   same primary majority vote. The unused legacy range-reversion method and its
   misleading HOLD reason were removed.
4. **All rejected decisions looked alike.** Runtime telemetry now separates
   strategy HOLD, trade-level rejection, sizing rejection, portfolio-risk
   block, broker attempt, broker rejection, and execution success. Telegram
   exposes the latest counts and top gate.
5. **Broker win/loss fields were fake zeros.** Runtime wins, losses and win rate
   are derived from closed AAQTS broker positions.
6. **Position management actually ran every 300 seconds.** It now has an
   independent 10-second loop. If that loop dies repeatedly, engine health
   fails closed instead of reporting a false RUNNING state.
7. **Engine and Telegram raced one MT5 terminal.** MT5 calls now share a
   reentrant cross-process file lock, including market data, execution,
   dashboards, snapshots and alert reads.
8. **Scheduled launch depended on untracked, duplicated PowerShell.** Versioned
   Windows launchers contain one canonical policy, separate stdout/stderr logs,
   task restart settings, and DPAPI credential loading.
9. **Stale `.env` credentials overrode the visible terminal session.** Demo
   preauthenticated mode now explicitly ignores those fields. The recommended
   VPS path saves and verifies a DPAPI-encrypted demo password so restarts do
   not rely on terminal session persistence.

## Deliberately retained blocks

The remediation does **not** remove mandatory stop-loss/take-profit checks,
account identity and demo-mode verification, stale ticks, spread-to-stop,
margin, daily/weekly loss, drawdown, consecutive loss, portfolio/correlation,
news, session, duplicate-position, or broker rejection controls. Those are not
indicator clashes; removing them would turn missing or dangerous inputs into
orders.

## Validation required before deployment

- Full unit/integration suite and compile/security checks must pass.
- The deterministic fast backtest must complete.
- Run the three-stage workflow in `VALIDATION_WORKFLOW.md`.
- Collect at least 100 closed AAQTS-only demo trades before profitability
  review. No result guarantees future profit.
- Repository visibility and the unrelated Vercel status are owner-level GitHub
  actions, not trading-engine code defects.
