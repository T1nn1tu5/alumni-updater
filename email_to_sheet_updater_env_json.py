import os
import imaplib
import email
from email.header import decode_header
import json
import openai
import time
import gspread
from google.oauth2.service_account import Credentials

# ====== SETUP ======
openai.api_key = os.getenv("OPENAI_API_KEY")

IMAP_SERVER = os.getenv("IMAP_SERVER")
EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_CREDENTIALS = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))

processed_emails_memory = set()

# ====== FUNCTIONS ======

def login_to_gmail():
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_ACCOUNT, EMAIL_PASSWORD)
    mail.select("inbox")
    return mail

def read_latest_email(mail):
    try:
        status, messages = mail.search(None, 'ALL')
        if status != "OK":
            print("No messages found!")
            return None

        email_ids = messages[0].split()
        latest_email_id = email_ids[-1]

        # Fetch the email by ID
        res, msg = mail.fetch(latest_email_id, "(RFC822)")
        if res != "OK":
            print("Failed to fetch email")
            return None

        for response in msg:
            if isinstance(response, tuple):
                msg = email.message_from_bytes(response[1])
                subject, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding if encoding else "utf-8")
                from_ = msg.get("From")
                if subject.strip() == "Alumni Update" and latest_email_id not in processed_emails_memory:
                    print(f"\n✅ Found alumni update email: {subject}")
                    processed_emails_memory.add(latest_email_id)
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            content_disposition = str(part.get("Content-Disposition"))
                            if content_type == "text/plain" and "attachment" not in content_disposition:
                                body = part.get_payload(decode=True).decode()
                                return body
                    else:
                        body = msg.get_payload(decode=True).decode()
                        return body
                else:
                    print(f"Skipping already processed or irrelevant email: {subject}")
                    return None
    except imaplib.IMAP4.abort as e:
        print(f"[Reconnect] IMAP connection lost during read: {e}")
        raise e

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
    creds = Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=["https://www.googleapis.com/auth/spreadsheets"])
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
    mail = login_to_gmail()

    while True:
        try:
            print("Checking for new emails...")
            email_body = read_latest_email(mail)

            if email_body:
                print("Parsing alumni update email...")
                parsed_data = parse_email_with_gpt(email_body)
                print(f"GPT extracted: {parsed_data}")

                print("Appending data to sheet...")
                append_to_sheet(parsed_data)
                print(f"✅ Added note for {parsed_data['full name'].lower()}")

        except imaplib.IMAP4.abort:
            mail = login_to_gmail()
            print("🔄 Reconnected to Gmail.")

        time.sleep(15)  # Wait before checking again

if __name__ == "__main__":
    main()
