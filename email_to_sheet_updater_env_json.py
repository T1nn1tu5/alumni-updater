import os
import time
import json
import openai
import gspread

from googleapiclient.discovery import build
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow

# ====== SETUP ======
openai.api_key = os.getenv("OPENAI_API_KEY")

GMAIL_QUERY = "subject:Alumni Update"
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SERVICE_ACCOUNT_INFO = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))

processed_emails_memory = set()

# ====== LOGIN FUNCTIONS ======

def login_to_gmail_oauth():
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    creds = flow.run_local_server(port=0)
    gmail_service = build('gmail', 'v1', credentials=creds)
    return gmail_service

def login_to_sheet_service_account():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = service_account.Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    return sheet

# ====== EMAIL FUNCTIONS ======

def get_latest_alumni_email(gmail_service):
    try:
        results = gmail_service.users().messages().list(userId='me', q=GMAIL_QUERY, maxResults=1).execute()
        messages = results.get('messages', [])

        if not messages:
            print("No Alumni Update emails found.")
            return None

        msg = gmail_service.users().messages().get(userId='me', id=messages[0]['id']).execute()

        if messages[0]['id'] in processed_emails_memory:
            print("Skipping already processed email.")
            return None

        processed_emails_memory.add(messages[0]['id'])

        payload = msg['payload']
        parts = payload.get('parts', [])

        for part in parts:
            if part['mimeType'] == 'text/plain':
                body = part['body']['data']
                body_decoded = base64.urlsafe_b64decode(body).decode('utf-8')
                return body_decoded

        print("No plain text body found.")
        return None

    except Exception as e:
        print(f"[Error reading email] {e}")
        return None

# ====== SHEET FUNCTIONS ======

def append_note_to_sheet(sheet, parsed_data):
    full_name = parsed_data['full name'].strip()
    note = parsed_data['note'].strip()

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

# ====== PARSING WITH GPT ======

def parse_email_with_gpt(email_body):
    prompt = f"""
Extract the full name and note from the following email. Return only JSON format like {{"full name": "Name", "note": "note content"}}. No extra text.

Email:
{email_body}
"""
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    raw_text = response.choices[0].message.content.strip()
    data = json.loads(raw_text)
    return data

# ====== MAIN LOOP ======

def main():
    gmail_service = login_to_gmail_oauth()
    sheet = login_to_sheet_service_account()

    while True:
        print("Checking for new emails...")
        email_body = get_latest_alumni_email(gmail_service)

        if email_body:
            print("Parsing alumni update email...")
            parsed_data = parse_email_with_gpt(email_body)
            print(f"GPT extracted: {parsed_data}")

            print("Appending to sheet...")
            append_note_to_sheet(sheet, parsed_data)
            print(f"✅ Added note for {parsed_data['full name'].lower()}")

        time.sleep(15)

if __name__ == "__main__":
    main()
