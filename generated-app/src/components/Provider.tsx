"use client";

import { createContext, useContext, useState, useCallback, useEffect, ReactNode } from "react";

export type BotStatus = "STOPPED" | "RUNNING" | "PAUSED" | "EMERGENCY_STOP";

export interface Bot {
  status: BotStatus;
  mode: "paper" | "live";
  openPositions: number;
  updatedAt: string;
  activity: {
    signalGeneration: boolean;
    orderExecution: boolean;
    positionMonitoring: boolean;
  };
}

interface AuthUser {
  id: number;
  username: string;
  role: string;
}

interface AppContextType {
  bot: Bot;
  user: AuthUser | null;
  refreshBot: () => Promise<void>;
  botCommand: (command: "start" | "pause" | "resume" | "stop" | "reset", mode?: "paper" | "live") => Promise<boolean>;
  emergencyStop: (closePositions: boolean) => Promise<unknown>;
  logout: () => Promise<void>;
  toast: { msg: string; type: "success" | "error" | "info" } | null;
  showToast: (msg: string, type?: "success" | "error" | "info") => void;
}

const AppContext = createContext<AppContextType | null>(null);

const defaultBot: Bot = {
  status: "STOPPED",
  mode: "paper",
  openPositions: 0,
  updatedAt: "",
  activity: { signalGeneration: false, orderExecution: false, positionMonitoring: true },
};

const defaultContext: AppContextType = {
  bot: defaultBot,
  user: null,
  refreshBot: async () => {},
  botCommand: async () => false,
  emergencyStop: async () => ({}),
  logout: async () => {},
  toast: null,
  showToast: () => {},
};

export function AppProvider({ children }: { children: ReactNode }) {
  const [bot, setBot] = useState<Bot>(defaultBot);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [toast, setToast] = useState<AppContextType["toast"]>(null);

  const showToast = useCallback((msg: string, type: "success" | "error" | "info" = "info") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  }, []);

  const refreshBot = useCallback(async () => {
    try {
      const r = await fetch("/api/bot/status", { cache: "no-store" });
      if (r.ok) {
        const d = await r.json();
        setBot(d.bot);
      }
    } catch {}
  }, []);

  const botCommand = useCallback(async (command: "start" | "pause" | "resume" | "stop" | "reset", mode?: "paper" | "live") => {
    try {
      const r = await fetch("/api/bot/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command, mode }),
      });
      const d = await r.json();
      if (d.ok) {
        setBot((b) => ({ ...b, status: d.state.next, mode: mode ?? b.mode }));
        showToast(d.state.reason || `Bot ${command}`, "success");
        refreshBot();
        return true;
      }
      showToast(d.error || "Command rejected", "error");
      return false;
    } catch {
      showToast("Connection error", "error");
      return false;
    }
  }, [showToast, refreshBot]);

  const emergencyStop = useCallback(async (closePositions: boolean) => {
    try {
      const r = await fetch("/api/bot/emergency", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true, closePositions }),
      });
      const d = await r.json();
      if (d.ok) {
        showToast(
          closePositions
            ? `EMERGENCY STOP — ${d.closedPositions} positions closed`
            : "EMERGENCY STOP — trading halted",
          "error"
        );
        refreshBot();
      } else {
        showToast(d.error || "Emergency failed", "error");
      }
      return d;
    } catch (e) {
      showToast("Connection error", "error");
      return { ok: false };
    }
  }, [showToast, refreshBot]);

  const logout = useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  }, []);

  useEffect(() => {
    refreshBot();
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setUser(d.user))
      .catch(() => {});
    const t = setInterval(refreshBot, 5000);
    return () => clearInterval(t);
  }, [refreshBot]);

  return (
    <AppContext.Provider value={{ bot, user, refreshBot, botCommand, emergencyStop, logout, toast, showToast }}>
      {children}
      {toast && (
        <div
          className={`fixed bottom-6 right-6 z-50 px-4 py-3 rounded-lg border text-sm font-medium shadow-2xl ${
            toast.type === "success"
              ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-300"
              : toast.type === "error"
              ? "bg-rose-500/10 border-rose-500/40 text-rose-300"
              : "bg-indigo-500/10 border-indigo-500/40 text-indigo-300"
          }`}
        >
          {toast.msg}
        </div>
      )}
    </AppContext.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppContext);
  return ctx || defaultContext;
}
