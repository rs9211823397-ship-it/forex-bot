// Symbol catalog with metadata for the dashboard

export const SYMBOLS = [
  { ticker: "EURUSD", name: "Euro / US Dollar", category: "forex", pip: 0.0001, contractSize: 100000 },
  { ticker: "GBPUSD", name: "British Pound / US Dollar", category: "forex", pip: 0.0001, contractSize: 100000 },
  { ticker: "USDJPY", name: "US Dollar / Japanese Yen", category: "forex", pip: 0.01, contractSize: 100000 },
  { ticker: "AUDUSD", name: "Australian Dollar / US Dollar", category: "forex", pip: 0.0001, contractSize: 100000 },
  { ticker: "USDCAD", name: "US Dollar / Canadian Dollar", category: "forex", pip: 0.0001, contractSize: 100000 },
  { ticker: "USDCHF", name: "US Dollar / Swiss Franc", category: "forex", pip: 0.0001, contractSize: 100000 },
  { ticker: "NZDUSD", name: "New Zealand Dollar / US Dollar", category: "forex", pip: 0.0001, contractSize: 100000 },
  { ticker: "XAUUSD", name: "Gold / US Dollar", category: "commodity", pip: 0.01, contractSize: 100 },
  { ticker: "XAGUSD", name: "Silver / US Dollar", category: "commodity", pip: 0.01, contractSize: 5000 },
  { ticker: "BTCUSD", name: "Bitcoin / US Dollar", category: "crypto", pip: 0.01, contractSize: 1 },
  { ticker: "ETHUSD", name: "Ethereum / US Dollar", category: "crypto", pip: 0.01, contractSize: 1 },
  { ticker: "SOLUSD", name: "Solana / US Dollar", category: "crypto", pip: 0.01, contractSize: 1 },
];

export const TIMEFRAMES = ["M5", "M15", "M30", "H1", "H4", "D1"] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];
