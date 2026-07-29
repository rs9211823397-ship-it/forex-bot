# AI Trading Manager — Mobile App (iOS + Android)

React Native (Expo) applications for the AAQTS master trading engine.
One codebase ships **identical** iOS and Android builds with the **same
application ID**, sharing the **same backend API and authentication** as the
web dashboard.

- iOS bundle identifier: `com.aaqts.tradingmanager`
- Android package name: `com.aaqts.tradingmanager`
- Backend: AAQTS `Next.js` API (`/api/*`) — Bearer-token auth (same token format as web session cookies)

## Screens

| Screen     | Contents |
|------------|----------|
| Login      | Username + password → `POST /api/auth/login`; token in `SecureStore` |
| Dashboard  | Total accounts, balance, equity, daily P/L, open trades, bot status + START / STOP / PAUSE / EMERGENCY STOP |
| Accounts   | Exness MT5 account list, connection state, balance, trading ON/OFF, enable/disable, connect, change password |
| Trades     | Live positions: symbol, side, lots, entry, current, P/L, SL/TP, close / partial |
| Signals    | AI signals: symbol, BUY/SELL, confidence %, regime, score, reasons |

## Setup

```bash
cd mobile
npm install            # requires Node 20+
npx expo start         # QR code → open in Expo Go for quick device testing
```

Set the backend URL in `app.json → expo.extra.apiBaseUrl` (e.g.
`https://your-aaqts-server`). Both apps hit this same API.

## Build — Android

```bash
npm install -g eas-cli
eas login
cd mobile
eas build --platform android --profile preview      # installable APK (internal)
eas build --platform android --profile production   # AAB for Play Console
```

## Build — iOS

Requires an Apple Developer account. Then:

```bash
cd mobile
eas build --platform ios --profile preview          # internal/simulator
eas build --platform ios --profile production       # App Store archive
eas submit --platform ios                           # upload to App Store Connect
```

> Local builds (no EAS): `npx expo run:ios` (macOS + Xcode) / `npx expo run:android` (Android Studio).

## Security notes

- Login token is stored with `expo-secure-store` (Keychain / EncryptedSharedPreferences).
- MT5 account passwords are never sent to / shown by the app — changing them
  goes through `POST /api/accounts/credentials` and encrypts at rest
  (AES-256-GCM) server-side only.
