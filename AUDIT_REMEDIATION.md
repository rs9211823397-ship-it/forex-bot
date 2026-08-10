# AAQTS End-to-End Audit Remediation

Audit baseline: `63400c653f98a3fd9a93a27a003404ebb570b91c` on
`agent/single-account-telegram`.

## Measured decision selectivity

A deterministic 700-decision, mixed-regime M15 replay was run with the VPS
policy (`ADX=12`, score `35`, one confirmation, quality `35`, regime `35`).
The report freezes those values internally, so ambient shell or `.env`
settings cannot silently change the audit result.
It covers one synthetic `ETH-USD` stream from `2025-01-04 03:15 UTC` through
`2025-01-11 10:00 UTC` (7 days 6 hours 45 minutes). It measures policy
selectivity only; it is not nine-symbol market data or an order-frequency
forecast.

| Result | Audit baseline | Final calibrated policy |
| --- | ---: | ---: |
| Actionable BUY/SELL | 9.57% | 38.57% |
| HOLD | 90.43% | 61.43% |
| Candidate acceptance | not recorded | 49.09% |

The repaired policy produced 270 actionable decisions out of 700. The replay
therefore no longer exhibits the reported 80–90% strategy HOLD problem. This
is a deterministic selectivity test, not a profitability claim or a target
trade frequency. Genuine risk/execution gates are intentionally excluded from
this strategy-only rate.

Exclusive remaining HOLD causes after repair:

| Gate | Share of HOLDs | Policy |
| --- | ---: | --- |
| Unsafe/unclear regime | 23.95% | Keep: volatility/data context safety |
| H1 direction conflict | 20.23% | Keep: one binary opposite-direction check |
| No primary direction | 15.81% | Keep: 2-of-3 vote did not form |
| Structure conflict | 15.58% | Keep: opposite structure, not extra confirmation |
| Contextual gate | 15.58% | Keep for weak candidates; aligned/neutral high-conviction context is advisory |
| Breakout not confirmed | 8.37% | Keep: prevents false range breaks |
| Quality threshold | 0.23% | Keep |
| Other | 0.23% | Keep and expose through telemetry |

RSI no longer appears as an exclusive primary HOLD cause. A standalone RSI
reading is advisory; it blocks only when Bollinger position and an opposing
reversal candle independently confirm exhaustion. In the strong-trend
ablation it changed 1 of 390 decisions (0.2564%).

## Defects fixed

1. **Stale equity peak blocked every entry.** Runtime risk state is now bound
   to execution mode, MT5 login, server, and risk-baseline epoch. A stale
   `1000` peak cannot poison a different `96.69` account/session, while a real
   later drawdown for the same identity is still preserved.
2. **Contextual softening was unreachable.** The contextual engine now returns
   explicit HTF and structure alignment codes. Invalid location or a missing
   micro-trigger is advisory for an aligned majority setup. A neutral H1 can
   proceed only with both high quality and strong directional score; an
   opposite H1 remains a hard veto.
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
10. **RSI was an oversized standalone veto.** RSI is no longer counted as a
    positive confirmation or an independent rejection. Only RSI + Bollinger
    extreme + an opposing reversal candle can veto an otherwise qualified
    entry.
11. **ADX gates disagreed.** `AAQTS_MIN_ADX` is now the single boundary used by
    signal validation, the production regime detector, and the causal research
    classifier. A VPS value of `12` cannot pass validation and then encounter
    a hidden `20`, `22.5`, or `25` ADX gate.
12. **Validation promotion was under-specified.** Promotion now requires full
    and chronological holdout samples, PF >= 1.2, positive expectancy,
    drawdown <= 10%, TradingView parity/coverage, and 100 closed demo trades.
    Missing percent-drawdown or holdout evidence fails closed.

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
