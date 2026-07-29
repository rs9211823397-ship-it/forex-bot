import React, { useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ScrollView, RefreshControl } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api/client";
import { colors } from "../theme";

type Positions = Awaited<ReturnType<typeof api.positions>>["positions"];

export default function TradesScreen() {
  const [positions, setPositions] = useState<Positions>([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try {
      const r = await api.positions();
      setPositions(r.positions);
    } catch {}
  };

  useFocusEffect(React.useCallback(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []));

  const close = async (p: Positions[number], percent = 100) => {
    await api.closeTrade(p.accountId, p.tradeId, percent);
    await load();
  };

  const totalPnL = positions.reduce((s, p) => s + p.unrealizedPnL, 0);

  return (
    <ScrollView
      style={s.screen}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={colors.accent} />}
    >
      <View style={s.header}>
        <Text style={s.title}>Active Trades ({positions.length})</Text>
        <Text style={[s.title, { color: totalPnL >= 0 ? colors.green : colors.red }]}>
          {totalPnL >= 0 ? "+" : ""}${totalPnL.toFixed(2)}
        </Text>
      </View>
      {positions.map((p) => (
        <View key={p.tradeId} style={s.card}>
          <View style={s.rowBetween}>
            <View style={s.row}>
              <View style={[s.dir, p.direction === "buy" ? s.buy : s.sell]}>
                <Text style={s.dirText}>{p.direction.toUpperCase()}</Text>
              </View>
              <View>
                <Text style={s.symbol}>{p.symbol}</Text>
                <Text style={s.meta}>{p.accountName || `Account #${p.accountId}`} · {p.lots} lots</Text>
              </View>
            </View>
            <Text style={[s.pnl, { color: p.unrealizedPnL >= 0 ? colors.green : colors.red }]}>
              {p.unrealizedPnL >= 0 ? "+" : ""}${p.unrealizedPnL.toFixed(2)}
            </Text>
          </View>
          <View style={[s.row, { marginTop: 10 }]}>
            <Cell label="Entry" value={p.entryPrice.toFixed(5)} />
            <Cell label="Current" value={p.currentPrice.toFixed(5)} />
            <Cell label="SL" value={p.stopLoss != null ? p.stopLoss.toFixed(5) : "—"} color={colors.red} />
            <Cell label="TP" value={p.takeProfit != null ? p.takeProfit.toFixed(5) : "—"} color={colors.green} />
          </View>
          <View style={[s.row, { marginTop: 10 }]}>
            <View style={s.flex}><TouchableOpacity style={[s.btn, s.btnRose]} onPress={() => close(p, 100)}><Text style={s.btnText}>Close 100%</Text></TouchableOpacity></View>
            <View style={s.flex}><TouchableOpacity style={[s.btn, s.btnSlat]} onPress={() => close(p, 50)}><Text style={s.btnText}>Partial 50%</Text></TouchableOpacity></View>
          </View>
        </View>
      ))}
      {positions.length === 0 && <Text style={s.empty}>No active trades.</Text>}
    </ScrollView>
  );
}

function Cell({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={s.flex}>
      <Text style={s.small}>{label}</Text>
      <Text style={[s.cellVal, color ? { color } : null]}>{value}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg0 },
  header: { flexDirection: "row", justifyContent: "space-between", padding: 14, paddingBottom: 6 },
  title: { color: colors.text0, fontSize: 15, fontWeight: "700" },
  card: { backgroundColor: colors.bg1, borderColor: colors.border, borderWidth: 1, borderRadius: 14, padding: 14, margin: 10, marginBottom: 4 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  dir: { borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4 },
  buy: { backgroundColor: "#10b98130" },
  sell: { backgroundColor: "#ef444430" },
  dirText: { color: colors.text0, fontSize: 10, fontWeight: "800" },
  symbol: { color: colors.text0, fontSize: 14, fontWeight: "700" },
  meta: { color: colors.text2, fontSize: 10 },
  pnl: { fontSize: 15, fontWeight: "800", fontVariant: ["tabular-nums"] },
  flex: { flex: 1 },
  small: { color: colors.text2, fontSize: 9, textTransform: "uppercase" },
  cellVal: { color: colors.text0, fontSize: 11, fontVariant: ["tabular-nums"] },
  btn: { borderWidth: 1, borderRadius: 10, paddingVertical: 8, alignItems: "center", marginHorizontal: 2 },
  btnText: { fontWeight: "700", fontSize: 11, color: colors.text0 },
  btnRose: { backgroundColor: "#ef444422", borderColor: "#ef444460" },
  btnSlat: { backgroundColor: "#64748b22", borderColor: "#64748b50" },
  empty: { color: colors.text2, textAlign: "center", marginTop: 80 },
});
