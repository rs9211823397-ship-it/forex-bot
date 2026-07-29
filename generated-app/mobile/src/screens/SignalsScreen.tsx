import React, { useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api/client";
import { colors } from "../theme";

type Signals = Awaited<ReturnType<typeof api.signals>>["signals"];

const QUALITY: Record<string, string> = {
  "A+": colors.green, A: colors.cyan, B: colors.amber, C: colors.text1, reject: colors.red,
};

export default function SignalsScreen() {
  const [signals, setSignals] = useState<Signals>([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try {
      const r = await api.signals();
      setSignals(r.signals);
    } catch {}
  };

  useFocusEffect(React.useCallback(() => { load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, []));

  return (
    <ScrollView
      style={s.screen}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={colors.accent} />}
    >
      <View style={s.header}>
        <Text style={s.title}>AI Signals</Text>
        <Text style={s.sub}>Quality-filtered, regime-aware</Text>
      </View>
      {signals.map((sig) => (
        <View key={sig.id} style={s.card}>
          <View style={s.rowBetween}>
            <View style={s.row}>
              <View style={[s.dir, sig.action === "buy" ? s.buy : sig.action === "sell" ? s.sell : s.hold]}>
                <Text style={s.dirText}>{sig.action.toUpperCase()}</Text>
              </View>
              <View>
                <Text style={s.symbol}>{sig.symbol} <Text style={s.tf}>{sig.timeframe}</Text></Text>
                <Text style={s.meta}>{sig.regime || "—"} · score {sig.score}</Text>
              </View>
            </View>
            <View style={{ flexDirection: "row", alignItems: "center" }}>
              <View style={[s.pill, { borderColor: (QUALITY[sig.quality] || colors.text2) + "80" }]}>
                <Text style={[s.pillText, { color: QUALITY[sig.quality] || colors.text2 }]}>{sig.quality}</Text>
              </View>
              <Text style={s.conf}>{Number(sig.confidence).toFixed(0)}%</Text>
            </View>
          </View>
          {(sig.reasons || []).slice(0, 4).map((r, i) => (
            <Text key={i} style={s.reason}>· {r}</Text>
          ))}
        </View>
      ))}
      {signals.length === 0 && <Text style={s.empty}>No signals yet.</Text>}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg0 },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: 14, paddingBottom: 6 },
  title: { color: colors.text0, fontSize: 15, fontWeight: "700" },
  sub: { color: colors.text2, fontSize: 11 },
  card: { backgroundColor: colors.bg1, borderColor: colors.border, borderWidth: 1, borderRadius: 14, padding: 14, margin: 10, marginBottom: 4 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  dir: { borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4 },
  buy: { backgroundColor: "#10b98130" },
  sell: { backgroundColor: "#ef444430" },
  hold: { backgroundColor: "#64748b30" },
  dirText: { color: colors.text0, fontSize: 10, fontWeight: "800" },
  symbol: { color: colors.text0, fontSize: 14, fontWeight: "700" },
  tf: { color: colors.text2, fontSize: 11 },
  meta: { color: colors.text2, fontSize: 10, textTransform: "capitalize" },
  pill: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2 },
  pillText: { fontSize: 10, fontWeight: "800" },
  conf: { color: colors.accent, fontWeight: "800", fontSize: 13, marginLeft: 6 },
  reason: { color: colors.text1, fontSize: 11, marginTop: 4 },
  empty: { color: colors.text2, textAlign: "center", marginTop: 80 },
});
