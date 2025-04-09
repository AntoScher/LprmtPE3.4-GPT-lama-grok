from flask import Flask, render_template, request, session, jsonify
from datetime import datetime, timedelta
import os
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv
import re

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')

# DeepSeek API configuration
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# Google Calendar configuration
SERVICE_ACCOUNT_FILE = 'service-account.json'
SCOPES = ['https://www.googleapis.com/auth/calendar']
CALENDAR_ID = os.getenv('CALENDAR_ID')

# Load system prompt
with open('prompt-doctor.txt', 'r', encoding='utf-8') as f:
    SYSTEM_PROMPT = f.read()

# Initialize Google Calendar service
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
calendar_service = build('calendar', 'v3', credentials=credentials)


def get_current_time():
    return datetime.now().astimezone()


def create_calendar_event(name, specialist):
    start_time = get_current_time() + timedelta(hours=3)
    end_time = start_time + timedelta(minutes=30)

    event = {
        'summary': f'Прием: {name}, {specialist}',
        'description': 'Требует подтверждения',
        'start': {
            'dateTime': start_time.isoformat(),
            'timeZone': 'Europe/Moscow',
        },
        'end': {
            'dateTime': end_time.isoformat(),
            'timeZone': 'Europe/Moscow',
        },
    }

    try:
        created_event = calendar_service.events().insert(
            calendarId=CALENDAR_ID,
            body=event
        ).execute()
        return start_time
    except Exception as e:
        print(f"Calendar API error: {e}")
        return None


def ask_deepseek(messages):
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }

    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 1024
    }

    try:
        response = requests.post(DEEPSEEK_URL, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"DeepSeek API error: {e}")
        return None


@app.route('/')
def index():
    session.clear()
    return render_template('index.html')


@app.route('/chat', methods=['POST'])
def chat_handler():
    user_message = request.get_json().get('message', '').strip()

    if 'step' not in session:
        session.update({
            'step': 'get_name',
            'name': '',
            'symptoms': '',
            'clarifications': 0,
            'specialist': ''
        })
        return jsonify(
            {'response': "Здравствуйте. Вы обратились в систему записи к врачу. Сообщите ваше Имя и опишите симптомы."})

    current_step = session['step']

    if current_step == 'get_name':
        if not user_message:
            return jsonify({'response': "Пожалуйста, сообщите ваше имя и опишите симптомы."})

        # Try to extract name and symptoms
        parts = re.split(r'[.,]', user_message, 1)
        if len(parts) < 2 or not parts[1].strip():
            return jsonify({'response': "Пожалуйста, укажите в формате: Имя. Описание симптомов"})

        session['name'] = parts[0].strip()
        session['symptoms'] = parts[1].strip()
        session['step'] = 'analyze_symptoms'
        return analyze_symptoms()

    elif current_step == 'analyze_symptoms':
        session['symptoms'] += ' ' + user_message
        return analyze_symptoms()

    elif current_step == 'confirm_appointment':
        if user_message.lower() in ['да', 'yes', 'ага', 'ок']:
            event_time = create_calendar_event(session['name'], session['specialist'])
            if event_time:
                response = (f"Запись к {session['specialist']} на "
                            f"{event_time.strftime('%H:%M')} оформлена.")
            else:
                response = "Ошибка записи. Пожалуйста, свяжитесь с регистратурой."
            session.clear()
            return jsonify({'response': response})
        else:
            session.clear()
            return jsonify({'response': "В случае ухудшения состояния обратитесь в скорую помощь по телефону 103."})

    return jsonify({'response': "Произошла ошибка. Пожалуйста, начните заново."})


def analyze_symptoms():
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Пациент: {session['name']}\nСимптомы: {session['symptoms']}"}
    ]

    response = ask_deepseek(messages)
    if not response:
        return jsonify({'response': "Ошибка обработки запроса. Попробуйте позже."})

    # Check if clarification needed
    if '?' in response and session['clarifications'] < 1:
        session['step'] = 'analyze_symptoms'
        session['clarifications'] += 1
        return jsonify({'response': response})

    # Extract specialist from response
    match = re.search(r'к\s+([\wа-яА-ЯёЁ]+)', response, re.I)
    if match:
        specialist = match.group(1).lower()
    else:
        specialist = 'терапевту'

    session['specialist'] = specialist
    session['step'] = 'confirm_appointment'

    event_time = get_current_time() + timedelta(hours=3)
    return jsonify({
        'response': f"Рекомендуем обратиться к {specialist}. "
                    f"Предлагаем запись на сегодня в {event_time.strftime('%H:%M')}. "
                    "Подтвердите согласие (Да/Нет)."
    })


if __name__ == '__main__':
    app.run(debug=False)
