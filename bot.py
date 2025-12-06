import os
import json
import telebot
import anthropic
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
CHAT_ID = 8347221861
TIMEZONE = pytz.timezone("Atlantic/Canary")

# Google Setup
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/spreadsheets'
]
SHEET_ID = "1LkF80j1AEZLzTDFvzepTmOPdtHTSUrSPvpB7LBbRPNc"
CALENDAR_ID = "berend.jakob.mainz@gmail.com"

# === INIT ===
bot = telebot.TeleBot(TELEGRAM_TOKEN)
claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
conversations = {}

# Google Auth
def get_google_creds():
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    if creds_json:
        creds_dict = json.loads(creds_json)
        return service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return None

def get_calendar_service():
    creds = get_google_creds()
    if creds:
        return build('calendar', 'v3', credentials=creds)
    return None

def get_sheets_service():
    creds = get_google_creds()
    if creds:
        return build('sheets', 'v4', credentials=creds)
    return None

# === HELPER FUNCTIONS ===

def get_weather():
    """Get weather for Las Palmas"""
    try:
        # Using wttr.in for simple weather (no API key needed)
        response = requests.get("https://wttr.in/Las+Palmas?format=%t+%C", timeout=10)
        if response.status_code == 200:
            return response.text.strip()
    except:
        pass
    return "Wetter nicht verfügbar"

def get_todays_events():
    """Get today's calendar events"""
    try:
        service = get_calendar_service()
        if not service:
            return []
        
        now = datetime.now(TIMEZONE)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
        
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        formatted = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            if 'T' in start:
                time = datetime.fromisoformat(start.replace('Z', '+00:00'))
                time_str = time.strftime('%H:%M')
            else:
                time_str = "Ganztägig"
            formatted.append(f"• {time_str} {event.get('summary', 'Kein Titel')}")
        return formatted
    except Exception as e:
        print(f"Calendar error: {e}")
        return []

def get_tomorrows_events():
    """Get tomorrow's calendar events"""
    try:
        service = get_calendar_service()
        if not service:
            return []
        
        now = datetime.now(TIMEZONE)
        tomorrow = now + timedelta(days=1)
        start_of_day = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = tomorrow.replace(hour=23, minute=59, second=59, microsecond=0)
        
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        if events:
            first_event = events[0]
            start = first_event['start'].get('dateTime', first_event['start'].get('date'))
            if 'T' in start:
                time = datetime.fromisoformat(start.replace('Z', '+00:00'))
                return time.strftime('%H:%M')
        return None
    except:
        return None

def get_sauna_count_this_week():
    """Count sauna sessions this week from Sheet"""
    try:
        service = get_sheets_service()
        if not service:
            return 0
        
        # Get Exercise sheet data
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='Exercise!A:B'
        ).execute()
        
        values = result.get('values', [])
        
        # Calculate start of week (Monday)
        now = datetime.now(TIMEZONE)
        start_of_week = now - timedelta(days=now.weekday())
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        
        count = 0
        for row in values[1:]:  # Skip header
            if len(row) >= 2:
                try:
                    date = datetime.strptime(row[0], '%Y-%m-%d')
                    date = TIMEZONE.localize(date)
                    if date >= start_of_week and 'Sauna' in row[1]:
                        count += 1
                except:
                    continue
        return count
    except Exception as e:
        print(f"Sheets error: {e}")
        return 0

def get_last_sauna_date():
    """Get the last sauna date from Sheet"""
    try:
        service = get_sheets_service()
        if not service:
            return None
        
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='Exercise!A:B'
        ).execute()
        
        values = result.get('values', [])
        
        last_date = None
        for row in values[1:]:
            if len(row) >= 2 and 'Sauna' in row[1]:
                try:
                    date = datetime.strptime(row[0], '%Y-%m-%d')
                    if last_date is None or date > last_date:
                        last_date = date
                except:
                    continue
        return last_date
    except:
        return None

# === PROACTIVE MESSAGES ===

def send_morning_briefing():
    """Send morning briefing at 07:00"""
    try:
        weather = get_weather()
        events = get_todays_events()
        sauna_count = get_sauna_count_this_week()
        
        events_text = "\n".join(events) if events else "• Keine Termine heute"
        
        sauna_status = f"{sauna_count}/4 diese Woche"
        if sauna_count < 2:
            sauna_status += " ⚠️"
        elif sauna_count >= 4:
            sauna_status += " ✅"
        
        message = f"""☀️ Guten Morgen Berend!

🌡️ Las Palmas: {weather}

📅 Heute:
{events_text}

📊 Sauna: {sauna_status}

💪 Mach den Tag zu deinem!"""
        
        bot.send_message(CHAT_ID, message)
        print(f"Morning briefing sent at {datetime.now(TIMEZONE)}")
    except Exception as e:
        print(f"Morning briefing error: {e}")

def send_evening_cutoff():
    """Send evening cutoff reminder at 22:00"""
    try:
        tomorrow_first = get_tomorrows_events()
        
        sleep_hint = ""
        if tomorrow_first:
            sleep_hint = f"\n\nMorgen früh: Erster Termin {tomorrow_first}\n→ Plane deine Schlafzeit entsprechend!"
        
        message = f"""🌙 Cutoff Zeit!

📵 Bildschirme aus in 30 min
📖 Reading Time oder Journaling{sleep_hint}

Gute Nacht! 🌟"""
        
        bot.send_message(CHAT_ID, message)
        print(f"Evening cutoff sent at {datetime.now(TIMEZONE)}")
    except Exception as e:
        print(f"Evening cutoff error: {e}")

def send_weekly_review():
    """Send weekly review on Sunday at 18:00"""
    try:
        sauna_count = get_sauna_count_this_week()
        sauna_pct = int((sauna_count / 4) * 100)
        
        sauna_emoji = "✅" if sauna_count >= 4 else "⚠️"
        
        message = f"""📊 Wochenreview

🧖 Sauna: {sauna_count}/4 ({sauna_pct}%) {sauna_emoji}

🎯 Nächste Woche: 
• Sauna 4x erreichen
• Morning Protocol beibehalten

Wie war deine Woche?"""
        
        bot.send_message(CHAT_ID, message)
        print(f"Weekly review sent at {datetime.now(TIMEZONE)}")
    except Exception as e:
        print(f"Weekly review error: {e}")

def check_sauna_warning():
    """Check if sauna warning needed (daily at 18:00)"""
    try:
        last_sauna = get_last_sauna_date()
        if last_sauna:
            days_since = (datetime.now() - last_sauna).days
            if days_since >= 3:
                sauna_count = get_sauna_count_this_week()
                message = f"""⚠️ Sauna Alert!

Letzte Sauna: vor {days_since} Tagen
Diese Woche: {sauna_count}/4

Die Finnen würden weinen. 🇫🇮
Heute noch Zeit?"""
                bot.send_message(CHAT_ID, message)
                print(f"Sauna warning sent at {datetime.now(TIMEZONE)}")
    except Exception as e:
        print(f"Sauna warning error: {e}")

# === TELEGRAM MESSAGE HANDLERS ===

SYSTEM_PROMPT = """Du bist der Zeroism Coach Bot für Berend.

KONTEXT:
- Berend ist 22, Psychologiestudent (JLU Gießen), aktuell Auslandssemester in Las Palmas
- Zeroism = sein systematisches Gesundheitsoptimierungs-Framework
- Fokus: Schlaf, Sauna (4x/Woche), Morning Protocol, Longevity

DEIN STIL:
- Kurz und direkt (es ist Telegram, keine Essays)
- Supportiv aber auch mal ein Tritt in den Hintern wenn nötig
- Deutsch, locker aber nicht albern
- Nutze Emojis sparsam aber effektiv

Du kannst auf Calendar-Daten und Zeroism-Tracking zugreifen."""

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Hey Berend! 👋 Dein Zeroism Coach ist online.\n\n/status - Aktueller Stand\n/today - Heutige Termine\n/reset - Chat zurücksetzen")

@bot.message_handler(commands=['reset'])
def reset(message):
    conversations[message.chat.id] = []
    bot.reply_to(message, "Chat zurückgesetzt! 🔄")

@bot.message_handler(commands=['status'])
def status(message):
    try:
        sauna_count = get_sauna_count_this_week()
        weather = get_weather()
        
        sauna_emoji = "✅" if sauna_count >= 4 else "⚠️" if sauna_count < 2 else "📊"
        
        reply = f"""📊 Zeroism Status

🧖 Sauna: {sauna_count}/4 diese Woche {sauna_emoji}
🌡️ Wetter: {weather}
"""
        bot.reply_to(message, reply)
    except Exception as e:
        bot.reply_to(message, f"Fehler: {str(e)}")

@bot.message_handler(commands=['today'])
def today(message):
    try:
        events = get_todays_events()
        weather = get_weather()
        
        if events:
            events_text = "\n".join(events)
        else:
            events_text = "Keine Termine heute! 🎉"
        
        reply = f"""📅 Heute

🌡️ {weather}

{events_text}"""
        bot.reply_to(message, reply)
    except Exception as e:
        bot.reply_to(message, f"Fehler: {str(e)}")

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    """Handle all other messages with Claude"""
    chat_id = message.chat.id
    
    if chat_id not in conversations:
        conversations[chat_id] = []
    
    conversations[chat_id].append({"role": "user", "content": message.text})
    
    # Keep last 30 messages
    if len(conversations[chat_id]) > 30:
        conversations[chat_id] = conversations[chat_id][-30:]
    
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=conversations[chat_id]
        )
        
        reply = response.content[0].text
        conversations[chat_id].append({"role": "assistant", "content": reply})
        
        # Telegram message limit
        if len(reply) > 4000:
            for i in range(0, len(reply), 4000):
                bot.reply_to(message, reply[i:i+4000])
        else:
            bot.reply_to(message, reply)
            
    except Exception as e:
        bot.reply_to(message, f"Fehler: {str(e)}")

# === SCHEDULER ===

def start_scheduler():
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    
    # Morning Briefing: 07:00 täglich
    scheduler.add_job(send_morning_briefing, CronTrigger(hour=7, minute=0))
    
    # Evening Cutoff: 22:00 täglich
    scheduler.add_job(send_evening_cutoff, CronTrigger(hour=22, minute=0))
    
    # Weekly Review: Sonntag 18:00
    scheduler.add_job(send_weekly_review, CronTrigger(day_of_week='sun', hour=18, minute=0))
    
    # Sauna Warning Check: 18:00 täglich
    scheduler.add_job(check_sauna_warning, CronTrigger(hour=18, minute=0))
    
    scheduler.start()
    print("Scheduler started!")
    return scheduler

# === MAIN ===

if __name__ == "__main__":
    print("🚀 Zeroism Coach Bot starting...")
    
    # Start scheduler
    scheduler = start_scheduler()
    
    # Start bot
    print("Bot polling...")
    bot.infinity_polling()
