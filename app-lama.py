from flask import Flask, render_template, request, session, redirect, url_for
import os
import requests
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from datetime import datetime, timedelta
from dotenv import load_dotenv
import sys
import logging

# Настройка логирования (отладочная информация будет записываться в файл debug.log)
logging.basicConfig(
    filename='debug.log',
    filemode='a',
    level=logging.INFO,
    encoding='utf-8',
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Настройка вывода для корректного отображения символов Unicode
sys.stdout.reconfigure(encoding='utf-8')

# Загружаем переменные окружения
load_dotenv()

app = Flask(__name__)
# Устанавливаем секретный ключ для сессий
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))

# Константы
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Идентификатор календаря можно задать через переменную окружения или по умолчанию "primary".
CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")

# Загружаем системный промпт из файла
with open("prompt-doctor.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


def clean_doctor_response(response_text):
    """
    Удаляет обрамление Markdown (например, тройные обратные кавычки) из ответа, если они имеются.
    """
    response_text = response_text.strip()
    if response_text.startswith("```"):
        lines = response_text.splitlines()
        # Если первая строка содержит "```json" или "```", убираем её
        if lines[0].startswith("```"):
            lines = lines[1:]
        # Если последняя строка — тройные обратные кавычки, убираем её
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        response_text = "\n".join(lines).strip()
    return response_text


# Авторизация Google Calendar с использованием token.json
def get_calendar_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


# Запрос к DeepSeek API
def ask_doctor(prompt):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 1024,
        "temperature": 0.7
    }
    response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        return f"Ошибка: {response.status_code}"


# Создание события в Google Calendar
def create_calendar_event(summary, description, date_time):
    service = get_calendar_service()
    event = {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": date_time.isoformat(),
            "timeZone": "Europe/Moscow"
        },
        "end": {
            "dateTime": (date_time + timedelta(hours=1)).isoformat(),
            "timeZone": "Europe/Moscow"
        },
    }
    event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
    return event.get("htmlLink")


# Маршруты Flask
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start_chat():
    session["patient_name"] = request.form["patient_name"]
    session["symptoms"] = request.form["symptoms"]

    prompt = f"Пациент {session['patient_name']} жалуется на {session['symptoms']}. Определи, к какому врачу направить."
    doctor_response = ask_doctor(prompt)
    session["doctor_response"] = doctor_response  # Сохраняем ответ Доктора
    return render_template("chat.html",
                           patient_name=session["patient_name"],
                           symptoms=session["symptoms"],
                           doctor_response=doctor_response)


@app.route("/confirm", methods=["POST"])
def confirm_appointment():
    confirmation = request.form["confirmation"]
    if confirmation == "yes":
        doctor_text = session.get("doctor_response", "")
        # Запись исходного ответа в лог для отладки
        logging.info("Original Doctor response: %s", doctor_text)

        # Очистка Markdown-обрамления, если оно присутствует
        doctor_text_cleaned = clean_doctor_response(doctor_text)
        logging.info("Cleaned Doctor response: %s", doctor_text_cleaned)

        try:
            # Пробуем распарсить очищенную строку как JSON
            doctor_data = json.loads(doctor_text_cleaned)
            doc_type = doctor_data.get("doc_type")
            date_str = doctor_data.get("date")
            time_str = doctor_data.get("time")

            # Проверяем наличие всех необходимых полей
            if not (doc_type and date_str and time_str):
                raise ValueError("Отсутствуют необходимые данные в ответе.")

            # Преобразуем строку с датой и временем в объект datetime
            date_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")

            summary = f"Прием: {session['patient_name']}, {doc_type}"
            description = f"Пациент: {session['patient_name']}. Симптомы: {session['symptoms']}. Требует подтверждения."
            calendar_link = create_calendar_event(summary, description, date_time)

            message = (f"Запись к {doc_type} на {date_str} в {time_str} оформлена. "
                       f"<a href='{calendar_link}' target='_blank'>Ссылка на событие в Google Calendar</a>")
        except (json.JSONDecodeError, ValueError) as e:
            logging.error("Parsing error: %s", e)
            message = "Ошибка парсинга ответа Доктора. Попробуйте ещё раз."
    else:
        message = "Запись отменена. Если нужна повторная консультация, перезагрузите страницу."

    return render_template("result.html", message=message)


if __name__ == "__main__":
    app.run(debug=True)