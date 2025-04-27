import os
import json
import time
import openai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ====== SETUP ======
openai.api_key = os.getenv("OPENAI_API_KEY")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_CREDENTIALS = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
GMAIL_QUERY = "subject:Alumni Update"
processed_emails_memory = set()

# ====== FUNCTIONS ======

def gmail_service():
    creds = Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=[
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/spreadsheets"
    ])
    service = build('gmail', 'v1', credentials=creds)
    return service

def sheets_service():
    creds = Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    client = gspread.authorize(creds)
    return client

def get_latest_alumni_email(gmail):
    results = gmail.users().messages().list(userId='me', q=GMAIL_QUERY, maxResults=1).execute()
    messages = results.get('messages', [])

    if not messages:
        print("No new Alumni Update emails.")
        return None

    msg_id = messages[0]['id']
    if msg_id in processed_emails_memory:
        return None

    msg = gmail.users().messages().get(userId='me', id=msg_id, format='full').execute()
    for part in msg['payload'].get('parts', []):
        if part['mimeType'] == 'text/plain':
            email_body = part['body']['data']
            import base64
            decoded_body = base64.urlsafe_b64decode(email_body).decode('utf-8')
            processed_emails_memory.add(msg_id)
            return decoded_body

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

def append_to_sheet(data, sheet_client):
    sheet = sheet_client.open_by_key(SPREADSHEET_ID).sheet1

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
    gmail = gmail_service()
    sheet_client = sheets_service()

    while True:
        print("Checking for new emails...")
        email_body = get_latest_alumni_email(gmail)

        if email_body:
            print("Parsing alumni update email...")
            parsed_data = parse_email_with_gpt(email_body)
            print(f"GPT extracted: {parsed_data}")

            print("Appending data to sheet...")
            append_to_sheet(parsed_data, sheet_client)
            print(f"✅ Added note for {parsed_data['full name'].lower()}")

        time.sleep(15)

if __name__ == "__main__":
    main()

