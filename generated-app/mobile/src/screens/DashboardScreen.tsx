import React, { useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ScrollView, RefreshControl, Alert } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api/client";
import { colors } from "../theme";

type Dashboard = Awaited<ReturnType<typeof api.dashboard>>;
type Bot = "STOPPED" | "RUNNING" | "PAUSED" | "EMERGENCY_STOP";

const STATUS_COLORS: Record<Bot, string> = {
  RUNNING: colors.green, PAUSED: colors.amber, STOPPED: colors.text2, EMERGENCY_STOP: colors.red,
};

export default function DashboardScreen() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [status, setStatus] = useState<Bot>("STOPPED");
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try {
      const [d, b] = await Promise.all([api.dashboard(), api.botStatus()]);
      setData(d);
      setStatus(b.bot.status);
    } catch {}
  };

  useFocusEffect(React.useCallback(() => { load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, []));

  const cmd = async (
    command: "start" | "pause" | "resume" | "stop" | "reset",
    mode?: "paper" | "live",
  ) => {
    try {
      await api.botControl(command, mode);
    } catch (e) {
      Alert.alert("Command rejected", e instanceof Error ? e.message : "Unknown error");
    }
    await load();
  };

  const emergency = () => {
    Alert.alert("EMERGENCY STOP", "All trading activity will be halted immediately.", [
      { text: "Cancel", style: "cancel" },
      { text: "Halt only", style: "destructive", onPress: async () => { await api.botEmergency(false); load(); } },
      { text: "Halt + close all", style: "destructive", onPress: async () => { await api.botEmergency(true); load(); } },
    ]);
  };

  const m = data?.metrics;

  return (
    <ScrollView
      style={s.screen}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={colors.accent} />}
    >
      {/* Bot status */}
      <View style={[s.card, s.botCard, { borderColor: STATUS_COLORS[status] + "80" }]}>
        <View style={s.rowBetween}>
          <View style={s.row}>
            <View style={[s.dot, { backgroundColor: STATUS_COLORS[status] }]} />
            <Text style={[s.botStatus, { color: STATUS_COLORS[status] }]}>{status}</Text>
          </View>
        </View>
        <View style={[s.row, { marginTop: 12 }]}>
          <View style={s.flex}>
            {(status === "STOPPED" || status === "EMERGENCY_STOP") && (
              <TouchableOpacity
                style={[s.ctl, { backgroundColor: "#10b98126", borderColor: "#10b98150" }]}
                onPress={() => (status === "EMERGENCY_STOP" ? cmd("reset").then(() => cmd("start", "paper")) : cmd("start", "paper"))}
              >
                <Text style={[s.ctlText, { color: colors.green }]}>▶ START BOT</Text>
              </TouchableOpacity>
            )}
            {status === "PAUSED" && (
              <TouchableOpacity style={[s.ctl, { backgroundColor: "#10b98126", borderColor: "#10b98150" }]} onPress={() => cmd("resume")}>
                <Text style={[s.ctlText, { color: colors.green }]}>▶ RESUME</Text>
              </TouchableOpacity>
            )}
            {status === "RUNNING" && (
              <TouchableOpacity style={[s.ctl, { backgroundColor: "#f59e0b26", borderColor: "#f59e0b50" }]} onPress={() => cmd("pause")}>
                <Text style={[s.ctlText, { color: colors.amber }]}>❚❚ PAUSE</Text>
              </TouchableOpacity>
            )}
          </View>
          {(status === "RUNNING" || status === "PAUSED") && (
            <View style={s.flex}>
              <TouchableOpacity style={[s.ctl, { backgroundColor: "#64748b20", borderColor: "#64748b40" }]} onPress={() => cmd("stop")}>
                <Text style={[s.ctlText, { color: colors.text1 }]}>■ STOP BOT</Text>
              </TouchableOpacity>
            </View>
          )}
        </View>
        <TouchableOpacity style={[s.emergency]} onPress={emergency}>
          <Text style={[s.ctlText, { color: colors.red }]}>⚠ EMERGENCY STOP</Text>
        </TouchableOpacity>
      </View>

      {/* Metrics */}
      <View style={s.grid}>
        <Kpi label="ACCOUNTS" value={String(m?.totalAccounts ?? 0)} sub={`${m?.activeAccounts ?? 0} active`} />
        <Kpi label="BALANCE" value={`$${(m?.totalBalance ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`} />
        <Kpi label="EQUITY" value={`$${(m?.totalEquity ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`} />
        <Kpi
          label="DAILY P/L"
          value={`${(m?.totalPnL ?? 0) >= 0 ? "+" : ""}$${(m?.totalPnL ?? 0).toFixed(2)}`}
          color={(m?.totalPnL ?? 0) >= 0 ? colors.green : colors.red}
        />
        <Kpi label="OPEN TRADES" value={String(m?.openPositions ?? 0)} color={colors.amber} />
        <Kpi label="WIN RATE" value={`${(m?.winRate ?? 0).toFixed(1)}%`} sub={`PF ${(m?.profitFactor ?? 0).toFixed(2)}`} />
      </View>
    </ScrollView>
  );
}

function Kpi({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <View style={s.kpi}>
      <Text style={s.kpiLabel}>{label}</Text>
      <Text style={[s.kpiValue, color ? { color } : null]}>{value}</Text>
      {sub ? <Text style={s.kpiSub}>{sub}</Text> : null}
    </View>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg0 },
  card: { backgroundColor: colors.bg1, borderColor: colors.border, borderWidth: 1, borderRadius: 14, padding: 16, margin: 12 },
  botCard: { marginBottom: 6 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  dot: { width: 9, height: 9, borderRadius: 5 },
  botStatus: { fontSize: 15, fontWeight: "800", letterSpacing: 0.5 },
  flex: { flex: 1 },
  ctl: { borderWidth: 1, borderRadius: 10, paddingVertical: 12, alignItems: "center", marginHorizontal: 4 },
  ctlText: { fontWeight: "800", fontSize: 13 },
  emergency: { backgroundColor: "#ef444420", borderWidth: 1, borderColor: "#ef444460", borderRadius: 10, paddingVertical: 11, alignItems: "center", marginTop: 10 },
  grid: { flexDirection: "row", flexWrap: "wrap", padding: 6 },
  kpi: { width: "50%", backgroundColor: colors.bg1, borderColor: colors.border, borderWidth: 1, borderRadius: 12, padding: 14, marginBottom: 6, marginHorizontal: 6 },
  kpiLabel: { color: colors.text2, fontSize: 9, letterSpacing: 1 },
  kpiValue: { color: colors.text0, fontSize: 18, fontWeight: "700", marginTop: 4 },
  kpiSub: { color: colors.text2, fontSize: 10, marginTop: 2 },
});
