import os
import datetime
from flask import Flask, render_template, request, jsonify
import openai
import google.auth
from googleapiclient.discovery import build
from google.oauth2 import service_account
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройки Flask
app = Flask(__name__)

# Настройки OpenAI-совместимого DeepSeek API
openai.api_base = os.getenv("OPENAI_API_BASE", "https://api.deepseek.com/v1")
openai.api_key = os.getenv("DEEPSEEK_API_KEY")
model_name = "deepseek-chat"  # или другой, если используется

# Загрузка системного промпта
with open("prompt-doctor.txt", "r", encoding="utf-8") as f:
    system_prompt = f.read()

# Google Calendar API
SERVICE_ACCOUNT_FILE = 'service-account.json'   # Путь к файлу с сервисным аккаунтом
SCOPES = ['https://www.googleapis.com/auth/calendar']
calendar_id = os.getenv("GOOGLE_CALENDAR_ID")  # ID календаря администратора

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
calendar_service = build('calendar', 'v3', credentials=credentials)

# Хранилище сообщений чата
chat_history = [
    {"role": "system", "content": system_prompt},
    {"role": "assistant", "content": "Здравствуйте. Вы обратились в систему записи к врачу. Сообщите ваше Имя и опишите симптомы."}
]


@app.route("/")
def index1():
    return render_template("index1.html")


@app.route("/chat", methods=["POST"])
def chat():
    global chat_history

    user_message = request.json.get("message")
    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    chat_history.append({"role": "user", "content": user_message})

    try:
        response = openai.ChatCompletion.create(
            model=model_name,
            messages=chat_history,
            temperature=0.5
        )
        reply = response.choices[0].message['content']
        chat_history.append({"role": "assistant", "content": reply})

        # Проверка на согласие пациента на запись
        if "оформлена" in reply:
            # Извлечение данных из истории сообщений
            patient_name = extract_patient_name(chat_history)
            specialist = extract_specialist(reply)
            appointment_time = extract_time(reply)

            if patient_name and specialist and appointment_time:
                create_calendar_event(patient_name, specialist, appointment_time)

        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def extract_patient_name(history):
    for msg in history:
        if msg["role"] == "user":
            lines = msg["content"].split("\n")
            for line in lines:
                if "меня зовут" in line.lower() or "имя" in line.lower():
                    return line.strip().split()[-1]
    return None


def extract_specialist(text):
    import re
    match = re.search(r"к (\w+)", text)
    if match:
        return match.group(1).capitalize()
    return "Терапевт"


def extract_time(text):
    import re
    from datetime import datetime, timedelta

    match = re.search(r"на сегодня в (\d{2}:\d{2})", text)
    if match:
        time_str = match.group(1)
        now = datetime.now()
        hour, minute = map(int, time_str.split(":"))
        appointment_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if appointment_time < now:
            appointment_time += timedelta(days=1)
        return appointment_time.isoformat()
    return None


def create_calendar_event(name, specialist, start_time_iso):
    event = {
        'summary': f'Прием: {name}, {specialist}',
        'description': 'Требует подтверждения.',
        'start': {
            'dateTime': start_time_iso,
            'timeZone': 'Europe/Moscow',
        },
        'end': {
            'dateTime': (datetime.datetime.fromisoformat(start_time_iso) + datetime.timedelta(minutes=30)).isoformat(),
            'timeZone': 'Europe/Moscow',
        }
    }
    calendar_service.events().insert(calendarId=calendar_id, body=event).execute()


if __name__ == "__main__":
    app.run(debug=True)

