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
openai.api_key = OPENAI_API_KEY

# Google Sheets connection (load from ENV variable)
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

# Read unread emails
def read_latest_email(mail):
    typ, data = mail.search(None, '(UNSEEN)')
    mail_ids = data[0].split()
    if not mail_ids:
        return None
    latest_email_id = mail_ids[-1]
    typ, msg_data = mail.fetch(latest_email_id, '(RFC822)')
    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email)
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                return part.get_payload(decode=True).decode()
    else:
        return msg.get_payload(decode=True).decode()
    return None

# Extract structured update using GPT
def extract_update(text):
    prompt = f"""Extract name, job title, and company from the following update:

Text: "{text}"

Return JSON like:
{{
  "name": "...",
  "job title": "...",
  "company": "..."
}}
"""
    client = openai.OpenAI()

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
    df["Full Name Lower"] = (df["First Name"].str.lower() + " " + df["Last Name"].str.lower())

    name = data.get("name", "").lower()
    job_title = data.get("job title", "")
    company = data.get("company", "")

    match = get_close_matches(name, df["Full Name Lower"].tolist(), n=1, cutoff=0.8)
    if match:
        idx = df[df["Full Name Lower"] == match[0]].index[0] + 2  # +2 for header and 1-based index
        if job_title:
            title_col = df.columns.get_loc(next(c for c in df.columns if "job title" in c.lower())) + 1
            sheets.values().update(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!{chr(64+title_col)}{idx}", body={"values": [[job_title]]}, valueInputOption="RAW").execute()
        if company:
            company_col = df.columns.get_loc(next(c for c in df.columns if "company" in c.lower())) + 1
            sheets.values().update(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!{chr(64+company_col)}{idx}", body={"values": [[company]]}, valueInputOption="RAW").execute()
        print(f"✅ Updated {data['name']}")

def main():
    mail = connect_gmail()
    while True:
        print("Checking for new emails...")
        text = read_latest_email(mail)
        if text:
            print("New email received. Parsing...")
            data = extract_update(text)
            update_sheet(data)
        else:
            print("No new email.")
        time.sleep(120)  # Check every 2 minutes

if __name__ == "__main__":
    main()
