import unittest

from accounts.credentials import EnvironmentCredentialProvider
from accounts.registry import AccountEnvironment, AccountPlatform, TradingAccount


def account():
    return TradingAccount(
        account_id="exness_demo",
        label="Exness Demo",
        broker="Exness",
        platform=AccountPlatform.MT5,
        environment=AccountEnvironment.DEMO,
        login="416083595",
        server="Exness-MT5Trial14",
        terminal_path="",
    )


class SingleAccountCredentialFallbackTests(unittest.TestCase):
    def test_primary_account_uses_global_terminal_and_preauthenticated_session(self):
        provider = EnvironmentCredentialProvider(
            {
                "AAQTS_ACCOUNT_ID": "exness_demo",
                "AAQTS_MT5_TERMINAL_PATH": r"C:\Exness\terminal64.exe",
            }
        )

        credentials = provider.credentials(account())
        readiness = provider.readiness(account())

        self.assertEqual(credentials.terminal_path, r"C:\Exness\terminal64.exe")
        self.assertEqual(credentials.password, "")
        self.assertTrue(credentials.use_preauthenticated_session)
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.missing, ())

    def test_primary_account_can_reuse_global_password(self):
        provider = EnvironmentCredentialProvider(
            {
                "AAQTS_ACCOUNT_ID": "exness_demo",
                "AAQTS_MT5_TERMINAL_PATH": r"C:\Exness\terminal64.exe",
                "AAQTS_MT5_PASSWORD": "secret",
            }
        )

        credentials = provider.credentials(account())

        self.assertEqual(credentials.password, "secret")
        self.assertFalse(credentials.use_preauthenticated_session)

    def test_non_primary_account_does_not_inherit_global_credentials(self):
        provider = EnvironmentCredentialProvider(
            {
                "AAQTS_ACCOUNT_ID": "other_demo",
                "AAQTS_MT5_TERMINAL_PATH": r"C:\Exness\terminal64.exe",
                "AAQTS_MT5_PASSWORD": "secret",
            }
        )

        credentials = provider.credentials(account())
        readiness = provider.readiness(account())

        self.assertEqual(credentials.password, "")
        self.assertEqual(credentials.terminal_path, "")
        self.assertFalse(credentials.use_preauthenticated_session)
        self.assertFalse(readiness.ready)
        self.assertIn("AAQTS_ACCOUNT_EXNESS_DEMO_TERMINAL_PATH", readiness.missing)
        self.assertIn("AAQTS_ACCOUNT_EXNESS_DEMO_PASSWORD", readiness.missing)

    def test_explicit_account_settings_override_global_fallback(self):
        provider = EnvironmentCredentialProvider(
            {
                "AAQTS_ACCOUNT_ID": "exness_demo",
                "AAQTS_MT5_TERMINAL_PATH": r"C:\Global\terminal64.exe",
                "AAQTS_MT5_PASSWORD": "global-secret",
                "AAQTS_ACCOUNT_EXNESS_DEMO_TERMINAL_PATH": r"C:\Account\terminal64.exe",
                "AAQTS_ACCOUNT_EXNESS_DEMO_PASSWORD": "account-secret",
                "AAQTS_ACCOUNT_EXNESS_DEMO_USE_PREAUTHENTICATED_SESSION": "true",
            }
        )

        credentials = provider.credentials(account())

        self.assertEqual(credentials.terminal_path, r"C:\Account\terminal64.exe")
        self.assertEqual(credentials.password, "account-secret")
        self.assertTrue(credentials.use_preauthenticated_session)


if __name__ == "__main__":
    unittest.main()
