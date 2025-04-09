import os
import json
import datetime
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Загрузка переменных окружения из .env
load_dotenv()

app = Flask(__name__)

# Константы для Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']
TOKEN_PATH = 'token.json'  # Используем JSON-файл для хранения токена
CREDENTIALS_PATH = 'service-account.json'
CALENDAR_ID = os.getenv("CALENDAR_ID")  # CALENDAR_ID берётся из .env, например: 'asc8er@gmail.com'

# Константы для DeepSeek API
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# Загрузка системного промпта
with open('prompt-doctor.txt', 'r', encoding='utf-8') as file:
    SYSTEM_PROMPT = file.read()

# История сообщений для каждой сессии
chat_histories = {}


def get_google_calendar_service():
    """Получение сервиса Google Calendar API с использованием token.json."""
    creds = None
    # Попытка загрузить учетные данные из файла token.json
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # Проверка валидности учетных данных
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        # Сохранение обновлённых учетных данных в token.json
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)


def create_calendar_event(patient_name, specialist, appointment_time):
    """Создание события в Google Calendar с использованием CALENDAR_ID из .env."""
    service = get_google_calendar_service()
    event = {
        'summary': f'Прием: {patient_name}, {specialist}',
        'description': 'Требует подтверждения',
        'start': {
            'dateTime': appointment_time.isoformat(),
            'timeZone': 'Europe/Moscow',
        },
        'end': {
            'dateTime': (appointment_time + datetime.timedelta(minutes=30)).isoformat(),
            'timeZone': 'Europe/Moscow',
        },
    }
    # Вставляем событие в календарь с CALENDAR_ID, полученным из .env
    event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
    return event.get('htmlLink')


def get_deepseek_response(messages):
    """Получение ответа от DeepSeek API."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": messages
    }
    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        return f"Ошибка при обращении к DeepSeek API: {response.status_code}"


@app.route('/')
def index():
    """Главная страница приложения."""
    return render_template('index.html')


@app.route('/chat', methods=['POST'])
def chat():
    """Обработка сообщений чата."""
    data = request.json
    user_message = data.get('message', '')
    session_id = data.get('session_id', 'default')

    # Инициализация истории сообщений для новой сессии
    if session_id not in chat_histories:
        chat_histories[session_id] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]

    # Добавление сообщения пользователя в историю
    chat_histories[session_id].append({"role": "user", "content": user_message})

    # Получение ответа от модели
    ai_response = get_deepseek_response(chat_histories[session_id])

    # Добавление ответа в историю
    chat_histories[session_id].append({"role": "assistant", "content": ai_response})

    # Проверка на согласие с записью к врачу
    if "Да" in user_message and any(
            "Подтвердите согласие" in msg.get("content", "") for msg in chat_histories[session_id] if
            msg.get("role") == "assistant"):
        # Извлечение информации о пациенте и специалисте из истории чата
        patient_name = None
        specialist = None
        for msg in chat_histories[session_id]:
            content = msg.get("content", "")
            if msg.get("role") == "user" and not patient_name:
                # Простая эвристика для извлечения имени
                words = content.split()
                if len(words) > 0 and words[0][0].isupper():
                    patient_name = words[0]
            if msg.get("role") == "assistant" and "обратиться к" in content:
                # Извлечение специалиста
                start_idx = content.find("обратиться к") + len("обратиться к")
                end_idx = content.find(".", start_idx)
                if end_idx != -1:
                    specialist = content[start_idx:end_idx].strip()
        # Если найдены имя и специалист, создаем событие в календаре
        if patient_name and specialist:
            appointment_time = datetime.datetime.now() + datetime.timedelta(hours=3)
            event_link = create_calendar_event(patient_name, specialist, appointment_time)
            ai_response += f"\nСоздано событие в календаре: {event_link}"

    return jsonify({"response": ai_response})


if __name__ == '__main__':
    app.run(debug=True)