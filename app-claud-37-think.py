import os
import json
import re
import uuid
import datetime
import requests
from flask import Flask, render_template, request, jsonify, session
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from dotenv import load_dotenv

# Загрузка переменных окружения из .env файла
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))

# Настройки DeepSeek API
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Настройки Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']
CALENDAR_ID = os.getenv("CALENDAR_ID")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

# Загрузка системного промпта
with open('prompt-doctor.txt', 'r', encoding='utf-8') as file:
    SYSTEM_PROMPT = file.read()

# Хранилище для чатов
chat_store = {}


def get_credentials():
    """Получение учетных данных для работы с Google Calendar API."""
    creds = None
    token_path = 'token.json'

    # Проверка наличия токена
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_info(json.load(open(token_path)))

    # Если нет действительных учетных данных, пользователь должен войти в систему
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        # Сохранение учетных данных для следующего запуска
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    return creds


def extract_name_from_chat(chat_history):
    """Извлечение имени пациента из истории чата."""
    for message in chat_history:
        if message["role"] == "user":
            # Ищем имя в формате "Меня зовут [Имя]" или просто первое слово
            name_match = re.search(r"[Мм]еня зовут (\w+)", message["content"])
            if name_match:
                return name_match.group(1)

            # Если не нашли по шаблону, берем первое слово
            words = message["content"].strip().split()
            if words:
                return words[0]
    return None


def extract_specialist_from_response(response):
    """Извлечение специальности врача из ответа ИИ."""
    specialist_patterns = [
        r"Рекомендуем обратиться к ([а-яА-Я]+)",
        r"запись к ([а-яА-Я]+) на",
        r"обратиться к ([а-яА-Я]+)"
    ]

    for pattern in specialist_patterns:
        match = re.search(pattern, response)
        if match:
            return match.group(1).lower()

    # Если не найдено по шаблонам, пробуем найти известные специальности
    common_specialists = ["терапевт", "хирург", "невролог", "кардиолог", "офтальмолог",
                          "отоларинголог", "гастроэнтеролог", "эндокринолог", "дерматолог"]

    for specialist in common_specialists:
        if specialist in response.lower():
            return specialist

    return None


def check_appointment_confirmation(message):
    """Проверка, является ли сообщение подтверждением записи."""
    confirmation_phrases = ["да", "конечно", "подтверждаю", "согласен", "согласна",
                            "подходит", "хорошо", "ок", "ok", "запишите"]

    message_lower = message.lower()

    for phrase in confirmation_phrases:
        if phrase in message_lower:
            return True

    return False


def add_to_calendar(patient_name, specialist, appointment_time):
    """Добавление записи в Google Calendar."""
    try:
        creds = get_credentials()
        service = build('calendar', 'v3', credentials=creds)

        event = {
            'summary': f"Прием: {patient_name}, {specialist}",
            'description': "Требует подтверждения",
            'start': {
                'dateTime': appointment_time.isoformat(),
                'timeZone': TIMEZONE,
            },
            'end': {
                'dateTime': (appointment_time + datetime.timedelta(minutes=30)).isoformat(),
                'timeZone': TIMEZONE,
            },
        }

        event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        return True, event.get('htmlLink')
    except Exception as e:
        print(f"Ошибка при добавлении в календарь: {str(e)}")
        return False, str(e)


def call_deepseek_api(messages):
    """Вызов API DeepSeek с обработкой ошибок и различных форматов."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    data = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.1,
    }

    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
        response.raise_for_status()

        response_json = response.json()

        # Обработка различных возможных форматов ответа API
        if "choices" in response_json and len(response_json["choices"]) > 0:
            if "message" in response_json["choices"][0]:
                return response_json["choices"][0]["message"]["content"]
            elif "text" in response_json["choices"][0]:
                return response_json["choices"][0]["text"]

        # Если структура ответа не распознана
        if "content" in response_json:
            return response_json["content"]
        elif "text" in response_json:
            return response_json["text"]
        elif "response" in response_json:
            return response_json["response"]

        # Если ни один из известных форматов не подошел
        print(f"Неизвестный формат ответа API: {response_json}")
        return "Извините, произошла ошибка при обработке ответа. Пожалуйста, попробуйте еще раз."

    except Exception as e:
        print(f"Ошибка при вызове DeepSeek API: {str(e)}")
        return "Извините, произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте еще раз позже."


def get_ai_response(message, session_id):
    """Получение ответа от DeepSeek API и обработка информации о записи."""
    # Получаем данные чата по идентификатору сессии
    if session_id not in chat_store:
        chat_store[session_id] = {
            "chat_history": [],
            "patient_name": None,
            "specialist": None,
            "specialist_suggested": False,
            "appointment_confirmed": False,
            "calendar_added": False
        }

    chat_data = chat_store[session_id]

    # Добавляем сообщение пользователя в историю чата
    chat_data["chat_history"].append({"role": "user", "content": message})

    # Формируем полный контекст беседы
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + chat_data["chat_history"]

    # Получаем ответ от API
    ai_message = call_deepseek_api(messages)

    # Добавляем ответ ИИ в историю чата
    chat_data["chat_history"].append({"role": "assistant", "content": ai_message})

    # Проверяем, нужно ли извлечь специалиста из ответа
    if not chat_data["specialist"]:
        specialist = extract_specialist_from_response(ai_message)
        if specialist:
            chat_data["specialist"] = specialist
            chat_data["specialist_suggested"] = True

    # Если специалист был предложен и пациент подтверждает запись
    if chat_data["specialist_suggested"] and check_appointment_confirmation(message):
        chat_data["appointment_confirmed"] = True

        # Получаем имя пациента из истории чата, если оно еще не сохранено
        if not chat_data["patient_name"]:
            patient_name = extract_name_from_chat(chat_data["chat_history"])
            if patient_name:
                chat_data["patient_name"] = patient_name

        # Если у нас есть все необходимые данные, добавляем запись в календарь
        if chat_data["patient_name"] and chat_data["specialist"] and not chat_data["calendar_added"]:
            appointment_time = datetime.datetime.now() + datetime.timedelta(hours=3)
            success, calendar_link = add_to_calendar(
                chat_data["patient_name"],
                chat_data["specialist"],
                appointment_time
            )

            chat_data["calendar_added"] = success

            if not success:
                print(f"Ошибка добавления в календарь: {calendar_link}")

    return ai_message


@app.route('/')
def index():
    """Рендеринг главной страницы."""
    # Генерация уникального идентификатора сессии при первом посещении
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())

    return render_template('index.html')


@app.route('/send_message', methods=['POST'])
def send_message():
    """Обработка сообщений от пользователя."""
    message = request.json.get('message', '')

    if not message:
        return jsonify({"error": "Empty message"}), 400

    # Получаем идентификатор сессии
    session_id = session.get('session_id')
    if not session_id:
        session_id = str(uuid.uuid4())
        session['session_id'] = session_id

    # Получаем ответ от ИИ
    ai_response = get_ai_response(message, session_id)

    return jsonify({"response": ai_response})


@app.route('/reset_chat', methods=['POST'])
def reset_chat():
    """Сброс чата."""
    session_id = session.get('session_id')
    if session_id and session_id in chat_store:
        del chat_store[session_id]

    # Генерация нового идентификатора сессии
    session['session_id'] = str(uuid.uuid4())

    return jsonify({"status": "success"})


if __name__ == '__main__':
    app.run(debug=True)