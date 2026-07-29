import React, { useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ScrollView, RefreshControl, Alert, TextInput, Modal } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api/client";
import { colors } from "../theme";

type Accounts = Awaited<ReturnType<typeof api.accounts>>["accounts"];

const CONN: Record<string, { c: string; label: string }> = {
  connected: { c: colors.green, label: "Connected" },
  disconnected: { c: colors.text2, label: "Disconnected" },
  auth_failed: { c: colors.red, label: "Auth failed" },
  not_configured: { c: colors.amber, label: "Not configured" },
};

export default function AccountsScreen() {
  const [accounts, setAccounts] = useState<Accounts>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [pwTarget, setPwTarget] = useState<Accounts[number] | null>(null);
  const [newPw, setNewPw] = useState("");

  const load = async () => {
    try {
      const r = await api.accounts();
      setAccounts(r.accounts);
    } catch {}
  };

  useFocusEffect(React.useCallback(() => { load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, []));

  const connect = async (a: Accounts[number]) => {
    try {
      if (a.connectionStatus === "connected") {
        await api.disconnectAccount(a.id);
      } else {
        const r = await api.connectAccount(a.id);
        if (!r.connected) {
          Alert.alert("Connection failed", r.message ?? "Unable to connect");
        }
      }
    } catch (e) {
      Alert.alert("Connection failed", e instanceof Error ? e.message : "Unknown error");
    }
    await load();
  };

  const toggle = async (a: Accounts[number]) => { await api.enableAccount(a.id, !a.tradingEnabled); await load(); };

  const savePw = async () => {
    if (!pwTarget || newPw.length < 6) {
      Alert.alert("Too short", "Password must be ≥ 6 characters");
      return;
    }
    await api.changePassword(pwTarget.id, newPw);
    setPwTarget(null);
    setNewPw("");
    Alert.alert("Saved", "Password re-encrypted & session invalidated.");
    await load();
  };

  return (
    <ScrollView
      style={s.screen}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} tintColor={colors.accent} />}
    >
      {accounts.map((a) => (
        <View key={a.id} style={s.card}>
          <View style={s.rowBetween}>
            <View style={s.row}>
              <View style={[s.dot, { backgroundColor: a.tradingEnabled ? colors.green : colors.red }]} />
              <View>
                <Text style={s.name}>{a.name}</Text>
                <Text style={s.meta}>{a.broker.replace("_", " ")} • {a.accountType} • {a.accountNumber}</Text>
              </View>
            </View>
            <View style={[s.pill, { borderColor: CONN[a.connectionStatus].c + "60", backgroundColor: CONN[a.connectionStatus].c + "15" }]}>
              <Text style={[s.pillText, { color: CONN[a.connectionStatus].c }]}>{CONN[a.connectionStatus].label}</Text>
            </View>
          </View>
          <View style={[s.row, { marginTop: 10 }]}>
            <View style={s.flex}><Text style={s.small}>Balance</Text><Text style={s.value}>${Number(a.balance).toLocaleString()}</Text></View>
            <View style={s.flex}><Text style={s.small}>Equity</Text><Text style={s.value}>${Number(a.equity).toLocaleString()}</Text></View>
            <View style={s.flex}><Text style={s.small}>Risk</Text><Text style={s.value}>{a.riskPercent}%</Text></View>
          </View>
          <View style={[s.row, { marginTop: 12 }]}>
            <View style={s.flex}>
              <TouchableOpacity onPress={() => toggle(a)} style={[s.btn, a.tradingEnabled ? s.btnGreen : s.btnSlat]}>
                <Text style={s.btnText}>{a.tradingEnabled ? "Trading: ON" : "Trading: OFF"}</Text>
              </TouchableOpacity>
            </View>
            <View style={s.flex}>
              <TouchableOpacity onPress={() => connect(a)} style={[s.btn, a.connectionStatus === "connected" ? s.btnSlat : s.btnIndigo]}>
                <Text style={s.btnText}>{a.connectionStatus === "connected" ? "Disconnect" : "Connect"}</Text>
              </TouchableOpacity>
            </View>
          </View>
          <TouchableOpacity onPress={() => setPwTarget(a)} style={[s.btn, s.btnCyan, { marginTop: 8 }]}>
            <Text style={[s.btnText, { color: colors.cyan }]}>Change password</Text>
          </TouchableOpacity>
        </View>
      ))}
      {accounts.length === 0 && <Text style={s.empty}>No accounts — add via the web dashboard.</Text>}

      <Modal visible={!!pwTarget} transparent animationType="slide">
        <View style={s.modalWrap}>
          <View style={s.modal}>
            <Text style={s.name}>New password · {pwTarget?.name}</Text>
            <TextInput
              value={newPw} onChangeText={setNewPw} secureTextEntry placeholder="New MT5 password"
              placeholderTextColor={colors.text2} style={s.input}
            />
            <View style={[s.row, { marginTop: 12 }]}>
              <View style={s.flex}><TouchableOpacity style={[s.btn, s.btnSlat]} onPress={() => setPwTarget(null)}><Text style={s.btnText}>Cancel</Text></TouchableOpacity></View>
              <View style={s.flex}><TouchableOpacity style={[s.btn, s.btnGreen]} onPress={savePw}><Text style={s.btnText}>Save (encrypted)</Text></TouchableOpacity></View>
            </View>
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg0 },
  card: { backgroundColor: colors.bg1, borderColor: colors.border, borderWidth: 1, borderRadius: 14, padding: 14, margin: 10, marginBottom: 4 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  dot: { width: 9, height: 9, borderRadius: 5 },
  name: { color: colors.text0, fontSize: 14, fontWeight: "700" },
  meta: { color: colors.text2, fontSize: 10, marginTop: 2, textTransform: "capitalize" },
  pill: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 3 },
  pillText: { fontSize: 10, fontWeight: "700" },
  flex: { flex: 1 },
  small: { color: colors.text2, fontSize: 9, textTransform: "uppercase", letterSpacing: 0.6 },
  value: { color: colors.text0, fontSize: 13, fontWeight: "600", marginTop: 2, fontVariant: ["tabular-nums"] },
  btn: { borderWidth: 1, borderRadius: 10, paddingVertical: 9, alignItems: "center", marginHorizontal: 2 },
  btnText: { fontWeight: "700", fontSize: 11, color: colors.text0 },
  btnGreen: { backgroundColor: "#10b98122", borderColor: "#10b98160" },
  btnSlat: { backgroundColor: "#64748b22", borderColor: "#64748b50" },
  btnIndigo: { backgroundColor: "#6366f122", borderColor: "#6366f160" },
  btnCyan: { backgroundColor: "#06b6d422", borderColor: "#06b6d460" },
  empty: { color: colors.text2, textAlign: "center", marginTop: 80 },
  modalWrap: { flex: 1, backgroundColor: "#000a", justifyContent: "flex-end", padding: 20 },
  modal: { backgroundColor: colors.bg1, borderColor: colors.border, borderWidth: 1, borderRadius: 16, padding: 20, marginBottom: 24 },
  input: { backgroundColor: colors.bg0, borderColor: colors.border, borderWidth: 1, borderRadius: 10, padding: 12, color: colors.text0, marginTop: 12 },
});
