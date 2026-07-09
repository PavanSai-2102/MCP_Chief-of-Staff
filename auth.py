import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.settings.basic'
]

def main():
    client_secrets_file = "Gmail-MCP-Server/gcp-oauth.keys.json"
    print("Initializing OAuth flow...")
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
    
    # run_local_server will print a link and wait for the redirect
    creds = flow.run_local_server(port=8080, open_browser=False)
    
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
    print("\nAuthentication successful! token.json has been created.")

if __name__ == '__main__':
    main()
