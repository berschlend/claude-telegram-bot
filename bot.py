import os
import json
import telebot
import anthropic
import base64
import re
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
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/spreadsheets'
]
SHEET_ID = "1LkF80j1AEZLzTDFvzepTmOPdtHTSUrSPvpB7LBbRPNc"
CALENDAR_ID = "berend.jakob.mainz@gmail.com"

# === INIT ===
bot = telebot.TeleBot(TELEGRAM_TOKEN)
claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# State tracking for conversations
user_state = {}
conversations = {}

# === GOOGLE AUTH ===
def get_google_creds():
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    if creds_json:
        creds_dict = json.loads(creds_json)
        return service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return None

def get_sheets_service():
    creds = get_google_creds()
    if creds:
        return build('sheets', 'v4', credentials=creds)
    return None

def get_calendar_service():
    creds = get_google_creds()
    if creds:
        return build('calendar', 'v3', credentials=creds)
    return None

# === SHEET LOGGING FUNCTIONS ===

def log_to_sheet(sheet_name, row_data):
    """Generic function to log data to any sheet"""
    try:
        service = get_sheets_service()
        if not service:
            return False, "Google Sheets nicht verfügbar"
        
        service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=f'{sheet_name}!A:Z',
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body={'values': [row_data]}
        ).execute()
        
        return True, "Geloggt"
    except Exception as e:
        return False, str(e)

def log_subjective_sleep(erholt, aufstehen, traume, body, klarheit, notes=""):
    """Log to Subjective Sleep sheet"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    bedtime = ""  # Can be filled later
    waketime = ""
    sleep_hours = ""
    avg_score = round((erholt + aufstehen + traume + body + klarheit) / 5, 1)
    
    row = [today, bedtime, waketime, sleep_hours, erholt, aufstehen, traume, body, klarheit, avg_score, "", "", "", "", "", "", "", "", notes]
    return log_to_sheet("Subjective Sleep", row)

def log_health_ringconn(sleep_score, sleep_hours, rhr, hrv, spo2, deep, rem, light, awake, steps, calories, notes=""):
    """Log to Health sheet (Ringconn data)"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    sleep_min = int(float(sleep_hours) * 60) if sleep_hours else ""
    
    row = [today, sleep_score, sleep_hours, sleep_min, rhr, hrv, spo2, deep, rem, light, awake, steps, calories, notes]
    return log_to_sheet("Health", row)

def log_compliance(thc_cutoff, essen_cutoff, nikotin_cutoff, screens_cutoff, bedtime="", notes=""):
    """Log to Compliance sheet - YESTERDAY's date since we ask about yesterday"""
    yesterday = (datetime.now(TIMEZONE) - timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Convert ja/nein to YES/NO or times
    def parse_cutoff(val):
        if val.lower() in ['ja', 'yes', 'y', 'j']:
            return 'YES'
        elif val.lower() in ['nein', 'no', 'n']:
            return 'NO'
        else:
            return val  # Assume it's a time
    
    row = [yesterday, bedtime, parse_cutoff(thc_cutoff), "", parse_cutoff(essen_cutoff), "", 
           parse_cutoff(nikotin_cutoff), "", parse_cutoff(screens_cutoff), "", "", "", "", "", "", notes]
    return log_to_sheet("Compliance", row)

def log_exercise(exercise_type, duration_min, activity="", location="", notes=""):
    """Log to Exercise sheet"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row = [today, exercise_type, duration_min, activity, location, notes]
    return log_to_sheet("Exercise", row)

def log_meal(time, ingredients, category="", before_cutoff="YES", notes=""):
    """Log to Meals sheet"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    meal_num = ""  # Could auto-increment
    row = [today, time, meal_num, ingredients, category, before_cutoff, notes]
    return log_to_sheet("Meals", row)

def log_craving(craving_type, intensity, before_cutoff="", action="", notes=""):
    """Log to Cravings sheet"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    now = datetime.now(TIMEZONE).strftime('%H:%M')
    row = [today, now, craving_type, intensity, before_cutoff, action, notes]
    return log_to_sheet("Cravings", row)

def log_learning(topic, duration_min, method="", klack_count="", active_recall="", notes=""):
    """Log to Learning sheet"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row = [today, topic, duration_min, klack_count, method, active_recall, notes]
    return log_to_sheet("Learning", row)

def log_finance(amount, category, description="", notes=""):
    """Log to Finance sheet"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row = [today, amount, category, description, "", notes]
    return log_to_sheet("Finance", row)

# === IMAGE PROCESSING ===

def process_image_with_claude(image_data, prompt):
    """Send image to Claude for analysis"""
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )
        return response.content[0].text
    except Exception as e:
        return f"Fehler: {str(e)}"

def parse_ringconn_screen1(image_data):
    """Extract Sleep Score Factors: RHR, HRV, Time Asleep, Efficiency"""
    prompt = """Analysiere diesen Ringconn Sleep Score Factors Screenshot.

Extrahiere diese Werte:
- Sleeping Heart Rate (bpm)
- Sleeping HRV (ms)
- Time Asleep (in Minuten umrechnen, z.B. 8hr3min = 483)
- Sleep Efficiency (%)

Antworte NUR in diesem Format (komma-getrennt):
rhr, hrv, sleep_minutes, efficiency

Beispiel: 44, 111, 483, 91

Wenn ein Wert nicht sichtbar ist, schreibe 0."""
    
    return process_image_with_claude(image_data, prompt)

def parse_ringconn_screen2(image_data):
    """Extract Sleep Duration: Time Asleep, Time in Bed"""
    prompt = """Analysiere diesen Ringconn Sleep Duration Screenshot.

Extrahiere diese Werte:
- Time Asleep (in Minuten, z.B. 8hr3min = 483)
- Time in Bed (in Minuten, z.B. 8hr50min = 530)
- Sleep Efficiency (%)

Antworte NUR in diesem Format (komma-getrennt):
sleep_minutes, bed_minutes, efficiency

Beispiel: 483, 530, 91

Wenn ein Wert nicht sichtbar ist, schreibe 0."""
    
    return process_image_with_claude(image_data, prompt)

def parse_ringconn_screen3(image_data):
    """Extract Sleep Stages: Awake, REM, Light, Deep in minutes"""
    prompt = """Analysiere diesen Ringconn Sleep Stages Screenshot.

Extrahiere diese Werte (alle in Minuten):
- Awake (z.B. 22min = 22)
- REM (z.B. 50min = 50)
- Light Sleep (z.B. 5hr58min = 358)
- Deep Sleep (z.B. 1hr15min = 75)

Antworte NUR in diesem Format (komma-getrennt):
awake, rem, light, deep

Beispiel: 22, 50, 358, 75

Wenn ein Wert nicht sichtbar ist, schreibe 0."""
    
    return process_image_with_claude(image_data, prompt)

def parse_meal_image(image_data):
    """Describe meal from photo"""
    prompt = """Beschreibe kurz was auf diesem Foto zu essen ist.
    
Antworte NUR mit den Zutaten, komma-getrennt.
Beispiel: oatmeal, milk, blueberries, honey

Halte es kurz und einfach."""
    
    return process_image_with_claude(image_data, prompt)

# === HELPER FUNCTIONS ===

def get_weather():
    """Get weather for Las Palmas"""
    try:
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
        start = now.replace(hour=0, minute=0, second=0).isoformat()
        end = now.replace(hour=23, minute=59, second=59).isoformat()
        
        events = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start, timeMax=end,
            singleEvents=True, orderBy='startTime'
        ).execute().get('items', [])
        
        formatted = []
        for e in events:
            start = e['start'].get('dateTime', e['start'].get('date'))
            if 'T' in start:
                t = datetime.fromisoformat(start.replace('Z', '+00:00')).strftime('%H:%M')
            else:
                t = "Ganztägig"
            formatted.append(f"• {t} {e.get('summary', 'Kein Titel')}")
        return formatted
    except:
        return []

def get_sauna_count_this_week():
    """Count sauna sessions this week"""
    try:
        service = get_sheets_service()
        if not service:
            return 0
        
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range='Exercise!A:B'
        ).execute()
        values = result.get('values', [])
        
        now = datetime.now(TIMEZONE)
        start_of_week = now - timedelta(days=now.weekday())
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0)
        
        count = 0
        for row in values[1:]:
            if len(row) >= 2:
                try:
                    date = datetime.strptime(row[0], '%Y-%m-%d')
                    date = TIMEZONE.localize(date)
                    if date >= start_of_week and 'Sauna' in row[1]:
                        count += 1
                except:
                    continue
        return count
    except:
        return 0

# === PROACTIVE MESSAGES ===

def send_morning_check():
    """Morning check at 07:00"""
    weather = get_weather()
    events = get_todays_events()
    events_text = "\n".join(events[:5]) if events else "Keine Termine"
    
    msg = f"""☀️ Guten Morgen!

🌡️ {weather}

📅 Heute:
{events_text}

---

📊 **Ringconn Step 1/3: Sleep Score Factors**
→ Screenshot mit: RHR, HRV, Time Asleep, Sleep Efficiency
→ Oder: `skip`"""
    
    user_state[CHAT_ID] = {"step": "ringconn_1", "ringconn_data": {}}
    bot.send_message(CHAT_ID, msg)

def send_ringconn_2():
    """Ask for sleep duration screen"""
    msg = """📊 **Ringconn Step 2/3: Sleep Duration**
→ Screenshot mit: Time Asleep, Time in Bed, Sleep Efficiency
→ Oder: `skip`"""
    
    user_state[CHAT_ID]["step"] = "ringconn_2"
    bot.send_message(CHAT_ID, msg)

def send_ringconn_3():
    """Ask for sleep stages screen"""
    msg = """📊 **Ringconn Step 3/3: Sleep Stages**
→ Screenshot mit: Awake, REM, Light Sleep, Deep Sleep (Minuten)
→ Oder: `skip`"""
    
    user_state[CHAT_ID]["step"] = "ringconn_3"
    bot.send_message(CHAT_ID, msg)

def finalize_ringconn():
    """Combine all ringconn data and log"""
    data = user_state[CHAT_ID].get("ringconn_data", {})
    
    # Extract values with defaults
    sleep_score = data.get("sleep_score", "")
    sleep_hours = data.get("sleep_hours", "")
    rhr = data.get("rhr", "")
    hrv = data.get("hrv", "")
    spo2 = data.get("spo2", "96")  # Default if not captured
    deep = data.get("deep", "")
    rem = data.get("rem", "")
    light = data.get("light", "")
    awake = data.get("awake", "")
    steps = data.get("steps", "")
    calories = data.get("calories", "")
    efficiency = data.get("efficiency", "")
    
    if any([sleep_hours, hrv, deep]):  # At least some data
        success, msg = log_health_ringconn(sleep_score, sleep_hours, rhr, hrv, spo2, deep, rem, light, awake, steps, calories, f"Efficiency: {efficiency}")
        if success:
            bot.send_message(CHAT_ID, f"""✅ Ringconn komplett geloggt!
Sleep: {sleep_hours}h, HRV: {hrv}ms
Deep: {deep}min, REM: {rem}min""")
        else:
            bot.send_message(CHAT_ID, f"❌ Fehler: {msg}")
    else:
        bot.send_message(CHAT_ID, "⏭️ Ringconn übersprungen")
    
    send_morning_sleep()

def send_morning_sleep():
    """Ask for subjective sleep after Ringconn"""
    msg = """😴 **Subjektiver Schlaf?**
→ Erholt, Aufstehen, Träume, Body, Klarheit (1-10)
→ Beispiel: `7 8 6 7 8`
→ Oder: `skip`"""
    
    user_state[CHAT_ID] = {"step": "morning_sleep"}
    bot.send_message(CHAT_ID, msg)

def send_morning_cutoffs():
    """Ask for yesterday's cutoffs"""
    msg = """🚫 **Cutoffs gestern eingehalten?**
→ THC, Essen, Nikotin, Screens (ja/nein)
→ Beispiel: `ja ja nein ja`
→ Oder mit Zeiten: `ja 21:30 nein 22:15`
→ Oder: `skip`"""
    
    user_state[CHAT_ID] = {"step": "morning_cutoffs"}
    bot.send_message(CHAT_ID, msg)

def send_evening_check():
    """Evening check at 22:30"""
    sauna_count = get_sauna_count_this_week()
    
    msg = f"""🌙 Tagesreview!

🧖 Sauna diese Woche: {sauna_count}/4

---

🏋️ **Exercise heute?**
→ Format: `typ dauer ort`
→ Beispiel: `sauna 20 gofit` oder `gym 60 legs`
→ Oder: `nein`"""
    
    user_state[CHAT_ID] = {"step": "evening_exercise"}
    bot.send_message(CHAT_ID, msg)

def send_evening_meals():
    """Ask for meals"""
    msg = """🍽️ **Meals heute?**
→ Foto schicken ODER
→ Text: `zeit zutaten | zeit zutaten`
→ Beispiel: `09:30 oats milk honey | 18:00 chicken rice veggies`
→ Oder: `nein`"""
    
    user_state[CHAT_ID] = {"step": "evening_meals"}
    bot.send_message(CHAT_ID, msg)

def send_evening_learning():
    """Ask for learning"""
    msg = """🧠 **Learning heute?**
→ Format: `topic dauer methode`
→ Beispiel: `neuro 60 lecture` oder `stats 45 anki`
→ Oder: `nein`"""
    
    user_state[CHAT_ID] = {"step": "evening_learning"}
    bot.send_message(CHAT_ID, msg)

def send_evening_cravings():
    """Ask for cravings"""
    msg = """😤 **Cravings heute?**
→ Format: `typ intensität` (mehrere möglich)
→ Beispiel: `thc 7` oder `thc 8 nikotin 5 sugar 3`
→ Oder: `nein`"""
    
    user_state[CHAT_ID] = {"step": "evening_cravings"}
    bot.send_message(CHAT_ID, msg)

def send_evening_finance():
    """Ask for expenses"""
    msg = """💰 **Ausgaben heute?**
→ Format: `betrag kategorie`
→ Beispiel: `15 food` oder `30 transport, 12 food`
→ Oder: `nein`"""
    
    user_state[CHAT_ID] = {"step": "evening_finance"}
    bot.send_message(CHAT_ID, msg)

def send_evening_done():
    """Complete evening check"""
    msg = """✅ **Tagesreview komplett!**

🚫 CUTOFF JETZT - Screens aus!

Gute Nacht! 🌙"""
    
    user_state[CHAT_ID] = {"step": None}
    bot.send_message(CHAT_ID, msg)

# === MESSAGE HANDLERS ===

@bot.message_handler(commands=['start', 'help'])
def cmd_start(message):
    bot.reply_to(message, """👋 Zeroism Coach Bot!

**Befehle:**
/status - Aktueller Stand
/today - Heutige Termine
/morning - Morning Check starten
/evening - Evening Review starten
/quick - Quick-Log Formate
/reset - State zurücksetzen

**Quick-Log:** Einfach schreiben:
• `sauna 20 gofit`
• `meal oats milk honey`
• `learn neuro 45`""")

@bot.message_handler(commands=['quick', 'logs', 'formats'])
def cmd_quick(message):
    bot.reply_to(message, """📝 **Quick-Log Formate**

**Exercise:**
`sauna 20 gofit`
`gym 45 gofit`
`cardio 30`
`run 25`

**Meals:**
`meal oats milk banana honey`

**Learning:**
`learn neuro 45`
`learn stats 30 anki`

**Cravings:**
`craving thc 7`
`craving sugar 5`

**Finance:**
`spent 15 food`
`spent 30 transport`

**Foto:** Einfach schicken → dann `meal` oder `ringconn` sagen""")

@bot.message_handler(commands=['morning'])
def cmd_morning(message):
    send_morning_check()

@bot.message_handler(commands=['evening'])
def cmd_evening(message):
    send_evening_check()

@bot.message_handler(commands=['testproactive'])
def cmd_test_proactive(message):
    """Test that proactive messaging works"""
    bot.reply_to(message, "🧪 Teste proaktive Nachricht in 10 Sekunden...")
    import threading
    def delayed_test():
        import time
        time.sleep(10)
        bot.send_message(CHAT_ID, "✅ Proaktive Nachricht funktioniert! Du wirst um 07:00 und 22:30 automatisch Nachrichten bekommen.")
    threading.Thread(target=delayed_test).start()

@bot.message_handler(commands=['reset'])
def cmd_reset(message):
    """Reset conversation state"""
    chat_id = message.chat.id
    user_state[chat_id] = {"step": None}
    if chat_id in conversations:
        conversations[chat_id] = []
    bot.reply_to(message, "🔄 State zurückgesetzt!")

@bot.message_handler(commands=['status'])
def cmd_status(message):
    sauna = get_sauna_count_this_week()
    weather = get_weather()
    emoji = "✅" if sauna >= 4 else "⚠️" if sauna < 2 else "📊"
    
    bot.reply_to(message, f"""📊 **Status**

🧖 Sauna: {sauna}/4 {emoji}
🌡️ {weather}""")

@bot.message_handler(commands=['today'])
def cmd_today(message):
    events = get_todays_events()
    weather = get_weather()
    events_text = "\n".join(events) if events else "Keine Termine"
    
    bot.reply_to(message, f"""📅 **Heute**

🌡️ {weather}

{events_text}""")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    """Handle photo messages"""
    chat_id = message.chat.id
    state = user_state.get(chat_id, {}).get("step")
    
    # Download photo
    file_info = bot.get_file(message.photo[-1].file_id)
    file = requests.get(f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}')
    image_data = base64.b64encode(file.content).decode('utf-8')
    
    if state == "ringconn_1":
        bot.reply_to(message, "🔄 Analysiere Sleep Score Factors...")
        result = parse_ringconn_screen1(image_data)
        
        try:
            values = [x.strip() for x in result.split(',')]
            if len(values) >= 4:
                rhr, hrv, sleep_min, efficiency = values[:4]
                user_state[CHAT_ID]["ringconn_data"]["rhr"] = rhr
                user_state[CHAT_ID]["ringconn_data"]["hrv"] = hrv
                user_state[CHAT_ID]["ringconn_data"]["sleep_hours"] = str(round(int(sleep_min) / 60, 1)) if sleep_min.isdigit() else ""
                user_state[CHAT_ID]["ringconn_data"]["efficiency"] = efficiency
                bot.reply_to(message, f"✅ Step 1: RHR {rhr}bpm, HRV {hrv}ms")
            else:
                bot.reply_to(message, f"⚠️ Parsing: {result}")
        except Exception as e:
            bot.reply_to(message, f"⚠️ Fehler: {e}")
        
        send_ringconn_2()
    
    elif state == "ringconn_2":
        bot.reply_to(message, "🔄 Analysiere Sleep Duration...")
        result = parse_ringconn_screen2(image_data)
        
        try:
            values = [x.strip() for x in result.split(',')]
            if len(values) >= 3:
                sleep_min, bed_min, efficiency = values[:3]
                if sleep_min.isdigit():
                    user_state[CHAT_ID]["ringconn_data"]["sleep_hours"] = str(round(int(sleep_min) / 60, 1))
                user_state[CHAT_ID]["ringconn_data"]["efficiency"] = efficiency
                bot.reply_to(message, f"✅ Step 2: Sleep {sleep_min}min, Bed {bed_min}min")
            else:
                bot.reply_to(message, f"⚠️ Parsing: {result}")
        except Exception as e:
            bot.reply_to(message, f"⚠️ Fehler: {e}")
        
        send_ringconn_3()
    
    elif state == "ringconn_3":
        bot.reply_to(message, "🔄 Analysiere Sleep Stages...")
        result = parse_ringconn_screen3(image_data)
        
        try:
            values = [x.strip() for x in result.split(',')]
            if len(values) >= 4:
                awake, rem, light, deep = values[:4]
                user_state[CHAT_ID]["ringconn_data"]["awake"] = awake
                user_state[CHAT_ID]["ringconn_data"]["rem"] = rem
                user_state[CHAT_ID]["ringconn_data"]["light"] = light
                user_state[CHAT_ID]["ringconn_data"]["deep"] = deep
                bot.reply_to(message, f"✅ Step 3: Deep {deep}min, REM {rem}min, Light {light}min")
            else:
                bot.reply_to(message, f"⚠️ Parsing: {result}")
        except Exception as e:
            bot.reply_to(message, f"⚠️ Fehler: {e}")
        
        finalize_ringconn()
    
    elif state == "evening_meals":
        bot.reply_to(message, "🔄 Analysiere Mahlzeit...")
        ingredients = parse_meal_image(image_data)
        
        now = datetime.now(TIMEZONE).strftime('%H:%M')
        success, msg = log_meal(now, ingredients)
        
        if success:
            bot.reply_to(message, f"✅ Meal geloggt: {ingredients}")
        else:
            bot.reply_to(message, f"❌ Fehler: {msg}")
        
        bot.reply_to(message, "📸 Noch ein Foto oder `done` für weiter")
    
    else:
        # Default: try to identify what kind of image
        bot.reply_to(message, "📸 Foto erhalten! Was ist das?\n→ `ringconn` oder `meal`?")
        user_state[chat_id] = {"step": "photo_identify", "image": image_data}

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    """Handle all text messages"""
    chat_id = message.chat.id
    text = message.text.strip().lower()
    state = user_state.get(chat_id, {}).get("step")
    
    # === MORNING FLOW ===
    
    # Photo identification after sending a photo without context
    if state == "photo_identify":
        stored_image = user_state.get(chat_id, {}).get("image")
        if stored_image:
            if text in ["meal", "essen", "food"]:
                bot.reply_to(message, "🔄 Analysiere Mahlzeit...")
                ingredients = parse_meal_image(stored_image)
                now = datetime.now(TIMEZONE).strftime('%H:%M')
                success, msg = log_meal(now, ingredients)
                if success:
                    bot.reply_to(message, f"✅ Meal geloggt: {ingredients}")
                else:
                    bot.reply_to(message, f"❌ Fehler: {msg}")
                user_state[chat_id] = {"step": None}
            elif text in ["ringconn", "ring", "sleep"]:
                bot.reply_to(message, "🔄 Analysiere Ringconn Screenshot...")
                result = parse_ringconn_screen1(stored_image)
                try:
                    values = [x.strip() for x in result.split(',')]
                    if len(values) >= 4:
                        rhr, hrv, sleep_min, efficiency = values[:4]
                        sleep_hours = str(round(int(sleep_min) / 60, 1)) if sleep_min.isdigit() else "0"
                        success, msg = log_health_ringconn("", sleep_hours, rhr, hrv, "96", "", "", "", "", "", "", f"Efficiency: {efficiency}")
                        if success:
                            bot.reply_to(message, f"✅ Ringconn geloggt!\nRHR: {rhr}bpm, HRV: {hrv}ms, Sleep: {sleep_hours}h")
                        else:
                            bot.reply_to(message, f"❌ Fehler: {msg}")
                    else:
                        bot.reply_to(message, f"⚠️ Konnte nicht alle Werte lesen:\n{result}")
                except Exception as e:
                    bot.reply_to(message, f"⚠️ Parsing-Fehler: {e}")
                user_state[chat_id] = {"step": None}
            else:
                bot.reply_to(message, "→ Sag `meal` oder `ringconn`")
        return
    
    elif state == "ringconn_1":
        if text == "skip":
            send_ringconn_2()
        else:
            bot.reply_to(message, "📸 Bitte Screenshot schicken oder `skip`")
    
    elif state == "ringconn_2":
        if text == "skip":
            send_ringconn_3()
        else:
            bot.reply_to(message, "📸 Bitte Screenshot schicken oder `skip`")
    
    elif state == "ringconn_3":
        if text == "skip":
            finalize_ringconn()
        else:
            bot.reply_to(message, "📸 Bitte Screenshot schicken oder `skip`")
    
    elif state == "morning_sleep":
        if text == "skip":
            send_morning_cutoffs()
        else:
            values = text.split()
            if len(values) >= 5:
                success, msg = log_subjective_sleep(*[int(v) for v in values[:5]])
                if success:
                    avg = sum([int(v) for v in values[:5]]) / 5
                    bot.reply_to(message, f"✅ Sleep geloggt! Ø {avg:.1f}")
                else:
                    bot.reply_to(message, f"❌ {msg}")
            else:
                bot.reply_to(message, "⚠️ Brauche 5 Werte: erholt aufstehen träume body klarheit")
                return
            send_morning_cutoffs()
    
    elif state == "morning_cutoffs":
        if text == "skip":
            user_state[chat_id] = {"step": None}
            bot.reply_to(message, "✅ Morning Check komplett! Guten Tag! ☀️")
        else:
            values = text.split()
            if len(values) >= 4:
                success, msg = log_compliance(*values[:4])
                if success:
                    bot.reply_to(message, "✅ Compliance geloggt!")
                else:
                    bot.reply_to(message, f"❌ {msg}")
            else:
                bot.reply_to(message, "⚠️ Brauche 4 Werte: thc essen nikotin screens")
                return
            user_state[chat_id] = {"step": None}
            bot.reply_to(message, "✅ Morning Check komplett! Guten Tag! ☀️")
    
    # === EVENING FLOW ===
    
    elif state == "evening_exercise":
        if text == "nein":
            send_evening_meals()
        else:
            # Parse: typ dauer ort
            parts = text.split()
            if len(parts) >= 2:
                typ = parts[0].capitalize()
                dauer = parts[1]
                ort = parts[2] if len(parts) > 2 else ""
                
                success, msg = log_exercise(typ, dauer, "", ort)
                if success:
                    sauna = get_sauna_count_this_week()
                    extra = f" (Sauna: {sauna}/4)" if "sauna" in text else ""
                    bot.reply_to(message, f"✅ {typ} {dauer}min geloggt!{extra}")
                else:
                    bot.reply_to(message, f"❌ {msg}")
            send_evening_meals()
    
    elif state == "evening_meals":
        if text == "nein" or text == "done":
            send_evening_learning()
        else:
            # Parse: zeit zutaten | zeit zutaten
            meals = text.split('|')
            count = 0
            for meal in meals:
                parts = meal.strip().split(' ', 1)
                if len(parts) >= 2:
                    zeit = parts[0]
                    zutaten = parts[1]
                    success, _ = log_meal(zeit, zutaten)
                    if success:
                        count += 1
            bot.reply_to(message, f"✅ {count} Meal(s) geloggt!")
            send_evening_learning()
    
    elif state == "evening_learning":
        if text == "nein":
            send_evening_cravings()
        else:
            parts = text.split()
            if len(parts) >= 2:
                topic = parts[0]
                dauer = parts[1]
                method = parts[2] if len(parts) > 2 else ""
                
                success, msg = log_learning(topic, dauer, method)
                if success:
                    bot.reply_to(message, f"✅ Learning geloggt: {topic} {dauer}min")
                else:
                    bot.reply_to(message, f"❌ {msg}")
            send_evening_cravings()
    
    elif state == "evening_cravings":
        if text == "nein":
            bot.reply_to(message, "✅ Clean day! 💪")
            send_evening_finance()
        else:
            # Parse multiple cravings: typ1 intensity1 typ2 intensity2 OR typ1 intensity1, typ2 intensity2
            parts = text.replace(',', ' ').split()
            count = 0
            logged = []
            # Process pairs: typ intensity typ intensity
            i = 0
            while i < len(parts) - 1:
                typ = parts[i]
                # Check if next part is a number (intensity)
                try:
                    intensity = int(parts[i + 1])
                    success, _ = log_craving(typ, str(intensity))
                    if success:
                        count += 1
                        logged.append(f"{typ} ({intensity}/10)")
                    i += 2
                except ValueError:
                    i += 1
            
            if count > 0:
                bot.reply_to(message, f"✅ {count} Craving(s) geloggt: {', '.join(logged)}")
            else:
                bot.reply_to(message, "⚠️ Format: typ intensität typ intensität")
            send_evening_finance()
    
    elif state == "evening_finance":
        if text == "nein":
            send_evening_done()
        else:
            # Parse: betrag kategorie, betrag kategorie
            expenses = text.split(',')
            count = 0
            for exp in expenses:
                parts = exp.strip().split()
                if len(parts) >= 2:
                    betrag = parts[0]
                    kategorie = parts[1]
                    success, _ = log_finance(betrag, kategorie)
                    if success:
                        count += 1
            bot.reply_to(message, f"✅ {count} Ausgabe(n) geloggt!")
            send_evening_done()
    
    # === QUICK LOGS (no active state) ===
    
    elif state is None or state == "":
        # Check for quick log patterns
        
        # Sauna/Exercise
        if re.match(r'(sauna|gym|workout|cardio|run)\s+\d+', text):
            parts = text.split()
            typ = parts[0].capitalize()
            dauer = parts[1]
            ort = parts[2] if len(parts) > 2 else ""
            
            success, msg = log_exercise(typ, dauer, "", ort)
            if success:
                sauna = get_sauna_count_this_week()
                extra = f"\n🧖 Sauna: {sauna}/4" if "sauna" in text else ""
                bot.reply_to(message, f"✅ {typ} {dauer}min geloggt!{extra}")
            else:
                bot.reply_to(message, f"❌ {msg}")
        
        # Meal
        elif text.startswith('meal '):
            ingredients = text[5:]
            now = datetime.now(TIMEZONE).strftime('%H:%M')
            success, msg = log_meal(now, ingredients)
            if success:
                bot.reply_to(message, f"✅ Meal geloggt!")
            else:
                bot.reply_to(message, f"❌ {msg}")
        
        # Learning
        elif text.startswith('learn '):
            parts = text.split()
            if len(parts) >= 3:
                topic = parts[1]
                dauer = parts[2]
                method = parts[3] if len(parts) > 3 else ""
                success, msg = log_learning(topic, dauer, method)
                if success:
                    bot.reply_to(message, f"✅ Learning geloggt!")
                else:
                    bot.reply_to(message, f"❌ {msg}")
        
        # Craving
        elif text.startswith('craving '):
            parts = text.split()
            if len(parts) >= 3:
                typ = parts[1]
                intensity = parts[2]
                success, msg = log_craving(typ, intensity)
                if success:
                    bot.reply_to(message, f"✅ Craving geloggt!")
                else:
                    bot.reply_to(message, f"❌ {msg}")
        
        # Expense
        elif text.startswith('spent '):
            parts = text.split()
            if len(parts) >= 3:
                betrag = parts[1]
                kategorie = parts[2]
                success, msg = log_finance(betrag, kategorie)
                if success:
                    bot.reply_to(message, f"✅ Ausgabe geloggt!")
                else:
                    bot.reply_to(message, f"❌ {msg}")
        
        else:
            # Send to Claude for general chat
            if chat_id not in conversations:
                conversations[chat_id] = []
            
            conversations[chat_id].append({"role": "user", "content": message.text})
            if len(conversations[chat_id]) > 20:
                conversations[chat_id] = conversations[chat_id][-20:]
            
            try:
                response = claude.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1024,
                    system="Du bist der Zeroism Coach Bot. Kurz, direkt, supportiv. Deutsch.",
                    messages=conversations[chat_id]
                )
                reply = response.content[0].text
                conversations[chat_id].append({"role": "assistant", "content": reply})
                bot.reply_to(message, reply)
            except Exception as e:
                bot.reply_to(message, f"Fehler: {str(e)}")

# === SCHEDULER ===

def start_scheduler():
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    
    # Morning Check: 07:00
    scheduler.add_job(send_morning_check, CronTrigger(hour=7, minute=0))
    
    # Evening Check: 22:30
    scheduler.add_job(send_evening_check, CronTrigger(hour=22, minute=30))
    
    scheduler.start()
    print("⏰ Scheduler gestartet!")
    return scheduler

# === MAIN ===

if __name__ == "__main__":
    print("🚀 Zeroism Coach Bot v2 starting...")
    scheduler = start_scheduler()
    print("📱 Bot polling...")
    bot.infinity_polling()
