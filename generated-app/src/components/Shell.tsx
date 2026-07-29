"use client";

import { ReactNode, useEffect, useState } from "react";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import { AppProvider } from "./Provider";

export default function Shell({ children }: { children: ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return (
    <AppProvider>
      <div className="min-h-screen flex bg-[#0a0e1a] text-slate-100">
        {mounted ? <Sidebar /> : <div className="w-60 shrink-0 border-r border-[#2a3454] bg-[#0a0e1a]"></div>}
        <div className="flex-1 flex flex-col min-w-0">
          <TopBar />
          <main className="flex-1 p-6 overflow-x-hidden">{children}</main>
        </div>
      </div>
    </AppProvider>
  );
}
