import os
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timezone, timedelta

load_dotenv()
def create_calendar_event(summary, start_datetime, end_datetime):
    try:
        sa_path = os.getenv('SERVICE_ACCOUNT_JSON')
        calendar_id = os.getenv('CALENDAR_ID')

        credentials = service_account.Credentials.from_service_account_file(
            sa_path,
            scopes=['https://www.googleapis.com/auth/calendar']
        )

        service = build('calendar', 'v3', credentials=credentials)

        event = {
            'summary': summary,
            'start': {'dateTime': start_datetime.isoformat(), 'timeZone': 'UTC'},
            'end': {'dateTime': end_datetime.isoformat(), 'timeZone': 'UTC'},
        }

        service.events().insert(
            calendarId=calendar_id,
            body=event
        ).execute()

        print("✅ Событие успешно создано!")
        return True

    except Exception as e:
        print(f"❌ Ошибка: {str(e)}")
        return False


if __name__ == '__main__':
    now = datetime.now(timezone.utc)
    test_event = {
        'summary': 'Test Event',
        'start_datetime': now + timedelta(hours=1),
        'end_datetime': now + timedelta(hours=2)
    }

    create_calendar_event(**test_event)