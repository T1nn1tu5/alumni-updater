import openai
import pandas as pd
import json
import os
import time
from datetime import datetime
from difflib import get_close_matches
from googleapiclient.discovery import build
from google.oauth2 import service_account
import imaplib
import email

# Settings
GMAIL_EMAIL = os.environ.get("GMAIL_EMAIL")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
SHEET_NAME = "Sheet1"

# Initialize OpenAI
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Google Sheets connection
def connect_google_sheets():
    credentials_info = json.loads(os.environ.get("GOOGLE_CLIENT_SECRET_JSON"))
    creds = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()

# Gmail IMAP connection
def connect_gmail():
    mail = imaplib.IMAP4_SSL('imap.gmail.com')
    mail.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
    mail.select('inbox')
    return mail

# Read latest unread email with "Alumni Update" in subject
def read_latest_email(mail):
    # Search for ALL emails (not just UNSEEN)
    typ, data = mail.search(None, 'ALL')
    print("Raw search output:", data)

    mail_ids = data[0].split()
    if not mail_ids:
        print("No emails found.")
        return None

    # Loop through the latest emails (start from newest)
    for num in reversed(mail_ids[-10:]):  # Only check the last 10 emails to be fast
        typ, msg_data = mail.fetch(num, '(BODY.PEEK[])')
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = msg["subject"]
        if subject:
            print(f"Checking email subject: {subject}")

            if "alumni update" in subject.lower():
                print(f"✅ Found alumni update email: {subject}")
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == 'text/plain':
                            return part.get_payload(decode=True).decode()
                else:
                    return msg.get_payload(decode=True).decode()

    print("No matching alumni update email found.")
    return None


    latest_email_id = mail_ids[-1]
    typ, msg_data = mail.fetch(latest_email_id, '(BODY.PEEK[])')
    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email)

    subject = msg["subject"]
    print(f"New email found: {subject}")

    if subject and "alumni update" in subject.lower():
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    return part.get_payload(decode=True).decode()
        else:
            return msg.get_payload(decode=True).decode()
    else:
        print(f"Ignored email (wrong subject): {subject}")
        return None

# Extract name and note using GPT
def extract_update(text):
    prompt = f"""Extract the alumni's full name and their note from the following text.

Return ONLY JSON like:
{{
  "full name": "",
  "note": ""
}}

If no note, leave it blank.

Text: "{text}"
"""
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    text = response.choices[0].message.content
    return json.loads(text)

# Update Google Sheet with note
def update_sheet(data):
    sheets = connect_google_sheets()
    result = sheets.values().get(spreadsheetId=SPREADSHEET_ID, range=SHEET_NAME).execute()
    values = result.get('values', [])
    df = pd.DataFrame(values[1:], columns=values[0])

    if "First Name" not in df.columns or "Last Name" not in df.columns:
        print("❌ Error: Sheet must have 'First Name' and 'Last Name' columns for matching.")
        return

    df["Full Name Lower"] = (df["First Name"].str.lower() + " " + df["Last Name"].str.lower())

    match_name = data.get("full name", "").lower()

    match = get_close_matches(match_name, df["Full Name Lower"].tolist(), n=1, cutoff=0.8)

    if match:
        idx = df[df["Full Name Lower"] == match[0]].index[0] + 2
        note_text = data.get("note", "")
        if note_text:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            note_column = f"Note - {today}"

            if note_column not in df.columns:
                print(f"Adding missing column {note_column}")
                values[0].append(note_column)
                for row in values[1:]:
                    row.append("")
                sheets.values().update(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A1", body={"values": values}).execute()

            col_idx = df.columns.get_loc(note_column) + 1 if note_column in df.columns else len(values[0])
            sheets.values().update(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!{chr(64+col_idx)}{idx}", body={"values": [[note_text]]}, valueInputOption="RAW").execute()
            print(f"✅ Added note for {match_name}")

    else:
        print(f"❌ No matching alumni found for {match_name}")

# Main function loop
def main():
    mail = connect_gmail()
    while True:
        print("Checking for new emails...")
        text = read_latest_email(mail)
        if text:
            print("Parsing alumni update email...")
            try:
                data = extract_update(text)
                print("GPT extracted:", data)
                update_sheet(data)
            except Exception as e:
                print(f"❌ Error during GPT parsing or updating: {e}")
        else:
            print("No relevant new email found.")
        time.sleep(120)

if __name__ == "__main__":
    main()
