import os
from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
import requests
from datetime import datetime, timedelta
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import pickle

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Для хранения сессии

# Загрузка переменных окружения из .env
load_dotenv()

# Настройки DeepSeek API
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# Настройки Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = 'credentials.json'  # Укажите путь к вашему файлу credentials.json
TOKEN_FILE = 'token.pickle'

# Загрузка системного промпта
with open('prompt-doctor.txt', 'r', encoding='utf-8') as file:
    SYSTEM_PROMPT = file.read()


# Функция для аутентификации в Google Calendar API
def get_calendar_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
    return build('calendar', 'v3', credentials=creds)


# Функция для отправки запроса к DeepSeek API
def query_deepseek(user_input, conversation_history):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = [
                   {"role": "system", "content": SYSTEM_PROMPT},
               ] + conversation_history + [{"role": "user", "content": user_input}]

    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.7
    }

    response = requests.post(DEEPSEEK_API_URL, json=payload, headers=headers)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        return f"Ошибка API: {response.status_code} - {response.text}"


# Функция для добавления события в Google Calendar
def add_event_to_calendar(patient_name, doctor_specialty, appointment_datetime):
    service = get_calendar_service()
    event = {
        'summary': f'Прием у врача: {doctor_specialty}',
        'description': f'Пациент: {patient_name}',
        'start': {
            'dateTime': appointment_datetime.isoformat(),
            'timeZone': 'Europe/Moscow',  # Укажите ваш часовой пояс
        },
        'end': {
            'dateTime': (appointment_datetime + timedelta(minutes=30)).isoformat(),  # Прием длится 30 минут
            'timeZone': 'Europe/Moscow',
        },
    }
    event = service.events().insert(calendarId='primary', body=event).execute()
    return event.get('htmlLink')


# Главная страница
@app.route('/')
def index():
    session.clear()  # Очищаем сессию при новом старте
    session['conversation'] = []
    return render_template('index.html')


# Обработка сообщений в чате
@app.route('/chat', methods=['POST'])
def chat():
    user_input = request.json.get('message')
    if not user_input:
        return jsonify({"response": "Пожалуйста, введите сообщение."})

    # Получаем историю разговора из сессии
    conversation_history = session.get('conversation', [])

    # Запрос к DeepSeek API
    ai_response = query_deepseek(user_input, conversation_history)

    # Обновляем историю разговора
    conversation_history.append({"role": "user", "content": user_input})
    conversation_history.append({"role": "assistant", "content": ai_response})
    session['conversation'] = conversation_history

    # Проверяем, нужно ли записать пациента на прием
    if "назначаю прием" in ai_response.lower() or "записать на прием" in ai_response.lower():
        # Здесь предполагается, что ИИ возвращает информацию о специальности врача, дате и времени
        # Например: "Назначаю прием к терапевту на 2023-10-01 в 10:00."
        try:
            # Парсим ответ ИИ (это пример, нужно адаптировать под реальный формат ответа)
            parts = ai_response.split("на ")[1].split(" в ")
            date_str = parts[0]
            time_str = parts[1].strip(".")
            doctor_specialty = ai_response.split(" к ")[1].split(" на ")[0]
            appointment_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")

            # Предполагаем, что имя пациента было получено ранее в разговоре
            patient_name = session.get('patient_name', 'Неизвестный пациент')

            # Добавляем событие в Google Calendar
            event_link = add_event_to_calendar(patient_name, doctor_specialty, appointment_datetime)
            ai_response += f"\nЗапись успешно создана. Ссылка на событие: {event_link}"
        except Exception as e:
            ai_response += f"\nОшибка при создании записи: {str(e)}"

    # Сохраняем имя пациента, если оно указано в начале разговора
    if not session.get('patient_name') and "меня зовут" in user_input.lower():
        session['patient_name'] = user_input.split("зовут ")[1].split()[0]

    return jsonify({"response": ai_response})


if __name__ == '__main__':
    app.run(debug=True)