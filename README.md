# EVRZ Hotel — Веб-приложение бронирования номеров (Вариант 10)

Учебное клиент-серверное веб-приложение на Django 4.2+ (Python 3.11+, SQLite3, чистый HTML5/CSS3/Vanilla JS).

## Быстрый старт

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py seed_data
python manage.py runserver --insecure
```

## Тестовые учётные записи (`seed_data`)
- Клиент: `ivonin_ad` / `ClientPass123!`
- Администратор стойки: `reception_anna` / `StaffPass123!`
- Управляющий: `admin_manager` / `ManagerPass123!`

## Запуск автотестов

```bash
python manage.py test -v 2
```
