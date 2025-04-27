# Alumni Data Updater (Cloud Version)

This system:
- Reads incoming emails from Gmail
- Uses GPT to extract alumni updates
- Applies changes to a live Google Sheet

## Setup
- Upload this repo to GitHub
- Create client_secret.json from Google Cloud
- Configure Render environment variables

## Environment Variables
- GMAIL_EMAIL
- GMAIL_APP_PASSWORD
- OPENAI_API_KEY
- SPREADSHEET_ID