import os  
from google_auth_oauthlib.flow import InstalledAppFlow  
  
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  
CLIENT_SECRET_FILE = os.path.join(BASE_DIR, "client_secret.json")  
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")  
  
SCOPES = [  
    "https://www.googleapis.com/auth/drive",  
    "https://www.googleapis.com/auth/documents",  
]  
  
def main():  
    if not os.path.exists(CLIENT_SECRET_FILE):  
        raise SystemExit(f"Missing {CLIENT_SECRET_FILE}")  
  
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)  
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")  
  
    print("\nOPEN THIS URL IN YOUR BROWSER:\n")  
    print(auth_url)  
    code = input("\nPASTE THE AUTHORIZATION CODE HERE: ").strip()  
  
    flow.fetch_token(code=code)  
    creds = flow.credentials  
  
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:  
        f.write(creds.to_json())  
  
    print(f"\nWrote {TOKEN_FILE}\n")  
  
if __name__ == "__main__":  
    main()  

