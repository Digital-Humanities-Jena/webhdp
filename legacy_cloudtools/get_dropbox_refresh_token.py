import os
import sys
from dotenv import load_dotenv
from dropbox import DropboxOAuth2FlowNoRedirect

# 1. Lade Variablen aus der .env Datei
load_dotenv()

APP_KEY = os.getenv("DROPBOX_APP_KEY")
APP_SECRET = os.getenv("DROPBOX_APP_SECRET")

def get_token():
    print("--- Dropbox Refresh Token Setup (aus .env) ---")

    # 2. Prüfen, ob die Variablen geladen wurden
    if not APP_KEY or not APP_SECRET:
        print("❌ FEHLER: Konnte 'DROPBOX_APP_KEY' oder 'DROPBOX_APP_SECRET' nicht in der .env finden.")
        print("   Bitte prüfen Sie, ob die Datei .env im gleichen Ordner liegt.")
        print(f"   Gefundener Key: {APP_KEY}")
        return

    # 3. OAuth Flow starten
    try:
        auth_flow = DropboxOAuth2FlowNoRedirect(
            APP_KEY,
            consumer_secret=APP_SECRET,
            token_access_type='offline'
        )

        authorize_url = auth_flow.start()

        print("\n✅ Konfiguration geladen.")
        print("1. Öffnen Sie diesen Link im Browser:")
        print(f"\n{authorize_url}\n")
        print("2. Klicken Sie auf 'Allow'/'Zulassen'.")
        print("3. Kopieren Sie den Code, der angezeigt wird.")

        auth_code = input("\nFügen Sie den Authorization Code hier ein: ").strip()

        print("\n⏳ Tausche Code gegen Token...")
        oauth_result = auth_flow.finish(auth_code)

        print("\n✅ ERFOLG! Ihr Refresh Token wurde generiert.")
        print("-" * 60)
        print(f"DROPBOX_REFRESH_TOKEN={oauth_result.refresh_token}")
        print("-" * 60)
        print("➡️  Kopieren Sie die Zeile oben (DROPBOX_REFRESH_TOKEN=...) in Ihre .env Datei!")

    except Exception as e:
        print(f"\n❌ FEHLER: {e}")
        print("Tipp: Prüfen Sie, ob Key und Secret in der .env Datei korrekt sind (keine Leerzeichen!).")

if __name__ == "__main__":
    get_token()