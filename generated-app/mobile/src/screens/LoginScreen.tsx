import React, { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, KeyboardAvoidingView, Platform, Image } from "react-native";
import { useAuth } from "../store/auth";
import { colors } from "../theme";

export default function LoginScreen() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!username || !password) return setError("Enter username and password");
    setBusy(true);
    const r = await login(username.trim(), password);
    setBusy(false);
    if (!r.ok) setError(r.error || "Login failed");
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={s.screen}>
      <View style={s.hero}>
        <View style={s.logo}><Text style={s.logoText}>A</Text></View>
        <Text style={s.title}>AI Trading Manager</Text>
        <Text style={s.subtitle}>AAQTS — multi-account MT5 control</Text>
      </View>
      <View style={s.card}>
        <Text style={s.label}>USERNAME</Text>
        <TextInput
          value={username} onChangeText={setUsername} placeholder="admin"
          placeholderTextColor={colors.text2} autoCapitalize="none" style={s.input}
        />
        <Text style={[s.label, { marginTop: 12 }]}>PASSWORD</Text>
        <TextInput
          value={password} onChangeText={setPassword} placeholder="••••••••"
          placeholderTextColor={colors.text2} secureTextEntry style={s.input}
        />
        {!!error && <View style={s.error}><Text style={s.errorText}>{error}</Text></View>}
        <TouchableOpacity onPress={submit} disabled={busy} style={[s.button, busy && { opacity: 0.6 }]}>
          <Text style={s.buttonText}>{busy ? "Authenticating…" : "Login"}</Text>
        </TouchableOpacity>
        <Text style={s.hint}>Same credentials as the web dashboard.{'\n'}Sessions are encrypted & stored on-device only.</Text>
      </View>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg0, justifyContent: "center", padding: 24 },
  hero: { alignItems: "center", marginBottom: 28 },
  logo: { width: 64, height: 64, borderRadius: 18, backgroundColor: colors.accent, alignItems: "center", justifyContent: "center", marginBottom: 12 },
  logoText: { color: "#fff", fontSize: 30, fontWeight: "800" },
  title: { color: colors.text0, fontSize: 22, fontWeight: "700" },
  subtitle: { color: colors.text2, fontSize: 12, marginTop: 4 },
  card: { backgroundColor: colors.bg1, borderColor: colors.border, borderWidth: 1, borderRadius: 14, padding: 20 },
  label: { color: colors.text2, fontSize: 10, letterSpacing: 1 },
  input: { backgroundColor: colors.bg0, borderColor: colors.border, borderWidth: 1, borderRadius: 10, padding: 12, color: colors.text0, marginTop: 6 },
  error: { backgroundColor: "#ef444420", borderColor: "#ef444460", borderWidth: 1, borderRadius: 8, padding: 10, marginTop: 12 },
  errorText: { color: colors.red, fontSize: 12 },
  button: { backgroundColor: colors.accent, borderRadius: 10, padding: 14, alignItems: "center", marginTop: 16 },
  buttonText: { color: "#fff", fontWeight: "700" },
  hint: { color: colors.text2, fontSize: 10, textAlign: "center", marginTop: 14, lineHeight: 15 },
});
