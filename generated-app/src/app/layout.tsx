import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "AAQTS — AI Adaptive Quant Trading System",
  description: "Institutional-grade multi-asset AI trading platform",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-[#0a0e1a] text-slate-100 antialiased">{children}</body>
    </html>
  );
}
