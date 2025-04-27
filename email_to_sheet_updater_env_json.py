import openai
import pandas as pd
import json
import os
import time
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

# Google Sheets connection (using credentials from environment variable)
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

# Read unread emails, only process if subject contains "Alumni Update"
def read_latest_email(mail):
    typ, data = mail.search(None, '(UNSEEN)')
    mail_ids = data[0].split()
    if not mail_ids:
        print("No unread emails found.")
        return None

    latest_email_id = mail_ids[-1]
    typ, msg_data = mail.fetch(latest_email_id, '(RFC822)')
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

# Extract structured alumni update using GPT
def extract_update(text):
    prompt = f"""Extract the following fields from the alumni update text:
- first name
- last name
- full name
- current company
- current job title
- current location
- linkedin profile
- personal website
- email address
- note (if any additional info)

Respond only with JSON like:
{{
  "first name": "",
  "last name": "",
  "full name": "",
  "current company": "",
  "current job title": "",
  "current location": "",
  "linkedin profile": "",
  "personal website": "",
  "email address": "",
  "note": ""
}}

If something is not mentioned, leave it blank.

Text: "{text}"
"""
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    text = response.choices[0].message.content
    return json.loads(text)

# Update Google Sheet
def update_sheet(data):
    sheets = connect_google_sheets()
    result = sheets.values().get(spreadsheetId=SPREADSHEET_ID, range=SHEET_NAME).execute()
    values = result.get('values', [])
    df = pd.DataFrame(values[1:], columns=values[0])

    if "First Name" not in df.columns or "Last Name" not in df.columns:
        print("❌ Error: Sheet must have 'First Name' and 'Last Name' columns for matching.")
        return

    df["Full Name Lower"] = (df["First Name"].str.lower() + " " + df["Last Name"].str.lower())

    # Determine name to match
    full_name = data.get("full name", "")
    first_name = data.get("first name", "")
    last_name = data.get("last name", "")
    if full_name:
        match_name = full_name.lower()
    else:
        match_name = (first_name + " " + last_name).lower()

    match = get_close_matches(match_name, df["Full Name Lower"].tolist(), n=1, cutoff=0.8)

    if match:
        idx = df[df["Full Name Lower"] == match[0]].index[0] + 2  # +2 for header + 1-index
        field_mapping = {
            "first name": "First Name",
            "last name": "Last Name",
            "current company": "Current Company",
            "current job title": "Current Job Title",
            "current location": "Current Location",
            "linkedin profile": "LinkedIn Profile",
            "personal website": "Personal Website",
            "email address": "Email"
        }

        # Update fields
        for key, column_name in field_mapping.items():
            if data.get(key):
                try:
                    col_idx = df.columns.get_loc(column_name) + 1
                except KeyError:
                    print(f"Adding missing column {column_name}")
                    values[0].append(column_name)
                    for row in values[1:]:
                        row.append("")
                    col_idx = len(values[0])
                    sheets.values().update(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A1", body={"values": values}).execute()

                sheets.values().update(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!{chr(64+col_idx)}{idx}", body={"values": [[data[key]]]}, valueInputOption="RAW").execute()
                print(f"✅ Updated {key} for {match_name}")

        # Handle notes separately
        if data.get("note"):
            note_col_name = "Notes"
            if note_col_name not in df.columns:
                print("Adding missing 'Notes' column")
                values[0].append(note_col_name)
                for row in values[1:]:
                    row.append("")
                sheets.values().update(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A1", body={"values": values}).execute()

            col_idx = df.columns.get_loc(note_col_name) + 1 if note_col_name in df.columns else len(values[0])
            sheets.values().update(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!{chr(64+col_idx)}{idx}", body={"values": [[data["note"]]]}, valueInputOption="RAW").execute()
            print(f"✅ Added note for {match_name}")

    else:
        print(f"❌ No matching alumni found for {match_name}")

# Main loop
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
        time.sleep(60)

if __name__ == "__main__":
    main()
