"use client";

export function Sparkline({ data, color = "#6366f1", height = 40, width = 120 }: { data: number[]; color?: string; height?: number; width?: number }) {
  if (!data || data.length < 2) return <div style={{ width, height }} className="text-slate-600 text-xs flex items-center justify-center">—</div>;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const step = width / (data.length - 1);
  const path = data
    .map((v, i) => {
      const x = i * step;
      const y = height - ((v - min) / range) * (height - 4) - 2;
      return `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const area = `${path} L ${width} ${height} L 0 ${height} Z`;
  const last = data[data.length - 1];
  const isUp = data[data.length - 1] >= data[0];
  const stroke = isUp ? "#10b981" : "#ef4444";
  return (
    <svg width={width} height={height} className="block">
      <defs>
        <linearGradient id={`grad-${color}-${stroke}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.35" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#grad-${color}-${stroke})`} />
      <path d={path} fill="none" stroke={stroke} strokeWidth="1.5" />
      <circle cx={(data.length - 1) * step} cy={height - ((last - min) / range) * (height - 4) - 2} r="2.5" fill={stroke} />
    </svg>
  );
}

export function BarChart({ data, color = "#6366f1", height = 60, width = 200 }: { data: number[]; color?: string; height?: number; width?: number }) {
  if (!data || data.length === 0) return null;
  const max = Math.max(...data.map(Math.abs));
  const bw = width / data.length;
  return (
    <svg width={width} height={height} className="block">
      {data.map((v, i) => {
        const h = max > 0 ? (Math.abs(v) / max) * (height - 6) : 0;
        const y = v >= 0 ? height / 2 - h : height / 2;
        return <rect key={i} x={i * bw + 1} y={y} width={bw - 2} height={h} fill={v >= 0 ? "#10b981" : "#ef4444"} rx="1" />;
      })}
      <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="#2a3454" strokeWidth="0.5" />
    </svg>
  );
}
