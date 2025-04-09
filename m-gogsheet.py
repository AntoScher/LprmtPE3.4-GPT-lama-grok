import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()
SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")  # Убедитесь, что в .env есть этот ключ!

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

def main():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    # Инициализация service ВНЕ условий
    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()

    # Чтение данных из таблицы (теперь выполняется всегда)
    try:
        range_name = 'Tasks!A1:D4'  # Проверьте название листа и диапазон!
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=range_name).execute()
        values = result.get('values', [])
        print("Данные из таблицы:", values)
    except Exception as e:
        print(f"Ошибка при чтении данных: {e}")

if __name__ == '__main__':
    main()