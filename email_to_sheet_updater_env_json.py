import os
import json
import time
import openai
import gspread
import base64
import email
from email.header import decode_header
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

# ====== SETUP ======
openai.api_key = os.getenv("OPENAI_API_KEY")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_CREDENTIALS = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
GMAIL_OAUTH_CLIENT_SECRET = json.loads(os.getenv("GMAIL_OAUTH_CLIENT_SECRET"))
GMAIL_QUERY = 'subject:"Alumni Update"'
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
processed_emails_memory = set()

# ====== FUNCTIONS ======

def login_to_gmail_oauth():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(GMAIL_OAUTH_CLIENT_SECRET, SCOPES)
            creds = flow.run_local_server(port=0)
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
    service = build('gmail', 'v1', credentials=creds)
    return service

def get_latest_alumni_email(gmail):
    results = gmail.users().messages().list(userId='me', q=GMAIL_QUERY, maxResults=1).execute()
    messages = results.get('messages', [])
    if not messages:
        print("No matching alumni emails found.")
        return None

    msg = gmail.users().messages().get(userId='me', id=messages[0]['id']).execute()
    email_data = msg['payload']

    headers = email_data.get("headers", [])
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "(No Subject)")
    email_id = messages[0]['id']

    if subject.strip() == "Alumni Update" and email_id not in processed_emails_memory:
        print(f"\n✅ Found alumni update email: {subject}")
        processed_emails_memory.add(email_id)
        body = ''
        parts = email_data.get("parts", [])
        for part in parts:
            if part['mimeType'] == 'text/plain':
                body = base64.urlsafe_b64decode(part['body']['data']).decode()
                break
        return body
    else:
        print(f"Skipping already processed or irrelevant email: {subject}")
        return None

def parse_email_with_gpt(email_body):
    prompt = f"""
Extract the full name and note from the following email. Return only JSON format like { '{"full name": "Name", "note": "note content"}' }. No extra text.

Email:
""" + email_body

    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    raw_text = response.choices[0].message.content.strip()
    data = json.loads(raw_text)
    return data

def append_to_sheet(data):
    creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    full_name = data["full name"].strip()
    note = data["note"].strip()

    records = sheet.get_all_records()
    names = [r['Name'].strip().lower() for r in records]

    if full_name.lower() in names:
        row_num = names.index(full_name.lower()) + 2
    else:
        row_num = len(records) + 2
        sheet.update(f'A{row_num}', full_name)

    header = sheet.row_values(1)
    if 'Notes' not in header:
        sheet.update_cell(1, len(header)+1, 'Notes')

    notes_col_num = sheet.row_values(1).index('Notes') + 1
    sheet.update_cell(row_num, notes_col_num, note)

# ====== MAIN LOOP ======

def main():
    gmail_service = login_to_gmail_oauth()

    while True:
        print("Checking for new emails...")
        try:
            email_body = get_latest_alumni_email(gmail_service)

            if email_body:
                print("Parsing alumni update email...")
                parsed_data = parse_email_with_gpt(email_body)
                print(f"GPT extracted: {parsed_data}")

                print("Appending data to sheet...")
                append_to_sheet(parsed_data)
                print(f"✅ Added note for {parsed_data['full name'].lower()}")

        except Exception as e:
            print(f"Error occurred: {e}")

        time.sleep(15)  # Wait before checking again

if __name__ == "__main__":
    main()

