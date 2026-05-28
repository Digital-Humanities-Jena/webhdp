# setup_auth.py
import os.path
from google_auth_oauthlib.flow import InstalledAppFlow

# Der gleiche sichere Scope wie zuvor
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def authenticate_user():
    """Generiert token.json für dauerhaften Zugriff."""
    if not os.path.exists('client_secret.json'):
        print("❌ FEHLER: Datei 'client_secret.json' nicht gefunden.")
        print("   Bitte laden Sie diese aus der Google Cloud Console herunter (Typ: Desktop App).")
        return

    print("🔄 Starte Browser-Login...")
    print("   Bitte loggen Sie sich mit dem Account ein, dem der 100GB-Ordner gehört.")

    flow = InstalledAppFlow.from_client_secrets_file(
        'client_secret.json', SCOPES)

    # Startet lokalen Server für den Login
    creds = flow.run_local_server(port=0)

    # Speichert den Token (Access + Refresh Token)
    with open('token.json', 'w') as token:
        token.write(creds.to_json())

    print("\n✅ ERFOLG: 'token.json' wurde erstellt!")
    print("   Diese Datei enthält Ihren digitalen Schlüsselbund.")
    print("   Kopieren Sie 'token.json' (und optional 'client_secret.json') auf Ihren Server.")

if __name__ == '__main__':
    authenticate_user()