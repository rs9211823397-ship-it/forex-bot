import "react-native-gesture-handler";
import React from "react";
import { StatusBar } from "expo-status-bar";
import { NavigationContainer, DarkTheme } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { Text } from "react-native";
import { AuthProvider, useAuth } from "./src/store/auth";
import LoginScreen from "./src/screens/LoginScreen";
import DashboardScreen from "./src/screens/DashboardScreen";
import AccountsScreen from "./src/screens/AccountsScreen";
import TradesScreen from "./src/screens/TradesScreen";
import SignalsScreen from "./src/screens/SignalsScreen";
import { colors } from "./src/theme";

const Stack = createNativeStackNavigator();
const Tabs = createBottomTabNavigator();

const navTheme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: colors.bg0,
    card: colors.bg0,
    text: colors.text0,
    border: colors.border,
    primary: colors.accent,
  },
};

const TAB_ICONS: Record<string, string> = {
  Dashboard: "◈",
  Accounts: "◉",
  Trades: "◧",
  Signals: "▲",
};

function MainTabs() {
  return (
    <Tabs.Navigator
      screenOptions={({ route }) => ({
        headerStyle: { backgroundColor: colors.bg0 },
        headerTintColor: colors.text0,
        tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 18 }}>{TAB_ICONS[route.name]}</Text>,
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.text2,
        tabBarStyle: { backgroundColor: colors.bg0, borderTopColor: colors.border },
      })}
    >
      <Tabs.Screen name="Dashboard" component={DashboardScreen} />
      <Tabs.Screen name="Accounts" component={AccountsScreen} />
      <Tabs.Screen name="Trades" component={TradesScreen} />
      <Tabs.Screen name="Signals" component={SignalsScreen} />
    </Tabs.Navigator>
  );
}

function Root() {
  const { token, loading } = useAuth();
  if (loading) return null;
  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      {!token ? (
        <Stack.Screen name="Login" component={LoginScreen} />
      ) : (
        <Stack.Screen name="Main" component={MainTabs} />
      )}
    </Stack.Navigator>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <NavigationContainer theme={navTheme}>
        <StatusBar style="light" />
        <Root />
      </NavigationContainer>
    </AuthProvider>
  );
}
