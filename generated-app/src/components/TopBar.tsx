"use client";

import { useEffect, useState } from "react";

export default function TopBar() {
  const [time, setTime] = useState<Date | null>(null);
  const [session, setSession] = useState<string>("");
  useEffect(() => {
    const t = setInterval(() => {
      const d = new Date();
      setTime(d);
      const h = d.getUTCHours();
      let s = "Off-hours";
      if (h >= 0 && h < 9) s = "Asian";
      else if (h >= 7 && h < 16) s = "London";
      else if (h >= 12 && h < 21) s = "New York";
      if (h >= 12 && h < 16) s = "London + New York (overlap)";
      setSession(s);
    }, 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="border-b border-[#2a3454] bg-[#0a0e1a]/80 backdrop-blur sticky top-0 z-10">
      <div className="px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-sm">
            <span className="size-2 rounded-full bg-emerald-400 pulse-dot"></span>
            <span className="text-slate-400">System</span>
            <span className="text-emerald-400 font-medium">Online</span>
          </div>
          <div className="h-4 w-px bg-[#2a3454]"></div>
          <div className="text-xs text-slate-500">
            Session: <span className="text-indigo-400">{session}</span>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-400">
          <div className="font-mono">
            {time ? time.toUTCString().replace("GMT", "UTC") : "—"}
          </div>
          <div className="h-4 w-px bg-[#2a3454]"></div>
          <div className="flex items-center gap-1.5">
            <span className="size-1.5 rounded-full bg-emerald-400"></span>
            <span>MT5 Bridge</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="size-1.5 rounded-full bg-emerald-400"></span>
            <span>AI Engine</span>
          </div>
        </div>
      </div>
    </div>
  );
}
