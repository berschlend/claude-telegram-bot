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

# === COLUMN MAPPING FOR HEALTH SHEET ===
# Based on exact column structure provided
HEALTH_COLUMNS = {
    'Date': 'A',
    'Sleep_Score': 'B',
    'Sleep_Quality': 'C',
    'Time_Asleep_Min': 'D',
    'Time_In_Bed_Min': 'E',
    'Sleep_Efficiency': 'F',
    'Sleep_Goal_Gap': 'G',
    'Time_Awake_Ratio': 'H',
    'Sleeping_HR': 'I',
    'Sleeping_HRV': 'J',
    'Skin_Temp': 'K',
    'Skin_Temp_Offset': 'L',
    'SpO2': 'M',
    'Respiratory_Rate': 'N',
    'Awake_Min': 'O',
    'Awake_Pct': 'P',
    'REM_Min': 'Q',
    'REM_Pct': 'R',
    'Light_Min': 'S',
    'Light_Pct': 'T',
    'Deep_Min': 'U',
    'Deep_Pct': 'V',
    'HR_Awake': 'W',
    'HR_REM': 'X',
    'HR_Light': 'Y',
    'HR_Deep': 'Z',
    'REM_Latency': 'AA',
    'Time_Falling_Asleep': 'AB',
    'Time_Final_Wake': 'AC',
    'Sleep_Stability': 'AD',
    'Bedtime': 'AE',
    'Wake_Time': 'AF',
    'Weight_kg': 'AG',
    'Inner_Ear_Temp': 'AH',
    'Body_Fat_Pct': 'AI',
    'Waist_cm': 'AJ',
    'BP_Sys': 'AK',
    'BP_Dia': 'AL',
    'Subjective_Erholt': 'AM',
    'Subjective_Aufstehen': 'AN',
    'Subjective_Traume': 'AO',
    'Subjective_Body': 'AP',
    'Subjective_Klarheit': 'AQ',
    'Subjective_Avg': 'AR',
    'Durchgeschlafen': 'AS',
    'Aufwachen_Count': 'AT',
    'Einschlafen_Speed': 'AU',
    'THC_OK': 'AV',
    'THC_Time': 'AW',
    'Nikotin_OK': 'AX',
    'Nikotin_Time': 'AY',
    'Koffein_OK': 'AZ',
    'Koffein_Time': 'BA',
    'Essen_OK': 'BB',
    'Essen_Time': 'BC',
    'Screens_OK': 'BD',
    'Screens_Time': 'BE',
    'Darkness': 'BF',
    'Noise': 'BG',
    'Partner': 'BH',
    'Device_In_Room': 'BI',
    'Room_Temp': 'BJ',
    'Steps': 'BK',
    'Calories': 'BL',
    'Notes': 'BM',
    'Fluid_Cut_Off': 'BN'
}

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

def log_to_sheet(sheet_name, row_data, range_spec=None):
    """Generic function to log data to any sheet"""
    try:
        service = get_sheets_service()
        if not service:
            return False, "Google Sheets nicht verfügbar"
        
        range_to_use = range_spec if range_spec else f'{sheet_name}!A:ZZ'
        
        service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=range_to_use,
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body={'values': [row_data]}
        ).execute()
        
        return True, "Geloggt"
    except Exception as e:
        return False, str(e)

def update_cell(sheet_name, cell, value):
    """Update a specific cell"""
    try:
        service = get_sheets_service()
        if not service:
            return False
        
        service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=f'{sheet_name}!{cell}',
            valueInputOption='USER_ENTERED',
            body={'values': [[value]]}
        ).execute()
        return True
    except:
        return False

def find_row_by_date(sheet_name, date_str, date_column='A'):
    """Find row number for a specific date"""
    try:
        service = get_sheets_service()
        if not service:
            return None
        
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f'{sheet_name}!{date_column}:{date_column}'
        ).execute()
        values = result.get('values', [])
        
        for i, row in enumerate(values):
            if row and row[0] == date_str:
                return i + 1  # 1-indexed
        return None
    except:
        return None

def update_health_field(date_str, field_name, value):
    """Update a specific field in Health sheet for a date"""
    row_num = find_row_by_date('Health', date_str)
    if row_num:
        col = HEALTH_COLUMNS.get(field_name)
        if col:
            return update_cell('Health', f'{col}{row_num}', value)
    return False

def log_health_complete(data):
    """Log complete health data with proper column mapping"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    
    # Build row in correct column order (A through BN = 66 columns)
    row = [''] * 66
    row[0] = today  # Date
    row[1] = data.get('sleep_score', '')
    row[2] = data.get('sleep_quality', '')
    row[3] = data.get('time_asleep_min', '')
    row[4] = data.get('time_in_bed_min', '')
    row[5] = data.get('sleep_efficiency', '')
    row[6] = data.get('sleep_goal_gap', '')
    row[7] = data.get('time_awake_ratio', '')
    row[8] = data.get('sleeping_hr', '')
    row[9] = data.get('sleeping_hrv', '')
    row[10] = data.get('skin_temp', '')
    row[11] = data.get('skin_temp_offset', '')
    row[12] = data.get('spo2', '')
    row[13] = data.get('respiratory_rate', '')
    row[14] = data.get('awake_min', '')
    row[15] = data.get('awake_pct', '')
    row[16] = data.get('rem_min', '')
    row[17] = data.get('rem_pct', '')
    row[18] = data.get('light_min', '')
    row[19] = data.get('light_pct', '')
    row[20] = data.get('deep_min', '')
    row[21] = data.get('deep_pct', '')
    row[22] = data.get('hr_awake', '')
    row[23] = data.get('hr_rem', '')
    row[24] = data.get('hr_light', '')
    row[25] = data.get('hr_deep', '')
    row[26] = data.get('rem_latency', '')
    row[27] = data.get('time_falling_asleep', '')
    row[28] = data.get('time_final_wake', '')
    row[29] = data.get('sleep_stability', '')
    row[30] = data.get('bedtime', '')
    row[31] = data.get('wake_time', '')
    # 32-37: Weight, Inner_Ear_Temp, Body_Fat_Pct, Waist_cm, BP_Sys, BP_Dia
    row[38] = data.get('subjective_erholt', '')
    row[39] = data.get('subjective_aufstehen', '')
    row[40] = data.get('subjective_traume', '')
    row[41] = data.get('subjective_body', '')
    row[42] = data.get('subjective_klarheit', '')
    row[43] = data.get('subjective_avg', '')
    row[44] = data.get('durchgeschlafen', '')
    row[45] = data.get('aufwachen_count', '')
    row[46] = data.get('einschlafen_speed', '')
    row[47] = data.get('thc_ok', '')
    row[48] = data.get('thc_time', '')
    row[49] = data.get('nikotin_ok', '')
    row[50] = data.get('nikotin_time', '')
    row[51] = data.get('koffein_ok', '')
    row[52] = data.get('koffein_time', '')
    row[53] = data.get('essen_ok', '')
    row[54] = data.get('essen_time', '')
    row[55] = data.get('screens_ok', '')
    row[56] = data.get('screens_time', '')
    # 57-60: Darkness, Noise, Partner, Device_In_Room, Room_Temp
    row[62] = data.get('steps', '')
    row[63] = data.get('calories', '')
    row[64] = data.get('notes', '')
    row[65] = data.get('fluid_cut_off', '')
    
    return log_to_sheet('Health', row)

def log_exercise(entries):
    """Log to Exercise sheet - supports multiple entries
    Format: [[date, time, type, duration, location, workout_type, intensity, rpe, stretching, sauna_temp, sauna_rounds, sauna_time_per_round, vo2max, notes], ...]
    """
    results = []
    for entry in entries:
        today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
        now = datetime.now(TIMEZONE).strftime('%H:%M')
        row = [today, now] + entry
        success, msg = log_to_sheet('Exercise', row)
        results.append(success)
    return all(results), f"{sum(results)}/{len(entries)} geloggt"

def log_meal(entries):
    """Log to Meals sheet - supports multiple entries
    Format: [[time, meal_num, ingredients, calories, protein, carbs, fat, fiber, category, before_cutoff, notes], ...]
    """
    results = []
    for entry in entries:
        today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
        row = [today] + entry
        # Pad to correct length
        while len(row) < 11:
            row.append('')
        success, msg = log_to_sheet('Meals', row)
        results.append(success)
    return all(results), f"{sum(results)}/{len(entries)} geloggt"

def log_craving(entries):
    """Log to Cravings sheet - supports multiple entries
    Format: [[type, intensity, before_cutoff, action, notes], ...]
    """
    results = []
    for entry in entries:
        today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
        now = datetime.now(TIMEZONE).strftime('%H:%M')
        row = [today, now] + entry
        while len(row) < 7:
            row.append('')
        success, msg = log_to_sheet('Cravings', row)
        results.append(success)
    return all(results), f"{sum(results)}/{len(entries)} geloggt"

def log_learning(entries):
    """Log to Learning sheet - supports multiple entries
    Format: [[start_time, end_time, duration_min, task, category, focus_quality, notes], ...]
    """
    results = []
    for entry in entries:
        today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
        row = [today] + entry
        while len(row) < 8:
            row.append('')
        success, msg = log_to_sheet('Learning', row)
        results.append(success)
    return all(results), f"{sum(results)}/{len(entries)} geloggt"

def log_finance(entries):
    """Log to Finance sheet - supports multiple entries
    Format: [[amount, category, description, necessary, impulse, notes], ...]
    """
    results = []
    for entry in entries:
        today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
        row = [today] + entry
        while len(row) < 7:
            row.append('')
        success, msg = log_to_sheet('Finance', row)
        results.append(success)
    return all(results), f"{sum(results)}/{len(entries)} geloggt"

def log_mood(entry):
    """Log to Mood sheet
    Format: [time, mood, energy, focus, anxiety, stress, motivation, social_battery, trigger, notes]
    """
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row = [today] + entry
    return log_to_sheet('Mood', row)

def log_supplements(entry):
    """Log to Supplements sheet
    Columns: Date, Blueprint_Stack, Omega3, ProButyrate, Collagen, NAC, Notes
    Spalte G = Schlaf (Mag, Glyc)
    """
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row = [today] + entry
    while len(row) < 7:
        row.append('')
    return log_to_sheet('Supplements', row)

def log_habits(entry):
    """Log to Habits sheet
    Columns: Date, Sunlight_Morning_Min, Blue_Light_Glasses, Meditation_Min, Breathwork_Min, 
             Reading_Min, Social_Interaction, Grateful_For, Hydration, Notes
    """
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row = [today] + entry
    while len(row) < 10:
        row.append('')
    return log_to_sheet('Habits', row)

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

# === RINGCONN PARSERS (9 Screenshots) ===

def parse_ringconn_sleep_score(image_data):
    """Screenshot 1: Sleep Score overview - Score, Time Asleep, Efficiency"""
    prompt = """Analysiere diesen Ringconn Sleep Score Screenshot.

Extrahiere:
- Sleep Score (Zahl wie 90)
- Time Asleep (in Minuten umrechnen: 8hr3min = 483)
- Sleep Efficiency (% Zahl wie 91)

Antworte NUR so (komma-getrennt):
sleep_score, time_asleep_min, efficiency

Beispiel: 90, 483, 91

Wenn ein Wert fehlt: 0"""
    return process_image_with_claude(image_data, prompt)

def parse_ringconn_summary(image_data):
    """Screenshot 2: Excellent Summary mit allen Metriken"""
    prompt = """Analysiere diesen Ringconn Summary Screenshot (zeigt "Excellent" oder ähnlich).

Extrahiere:
- Sleeping Heart Rate (bpm)
- Sleeping Skin Temperature (°C)
- Skin Temp Offset (z.B. -0.13)
- Time Asleep (in Minuten: 8hr3min = 483)
- Sleep Efficiency (%)
- Sleep Goal Gap (z.B. +3min = 3 oder -5min = -5)
- Time Awake Ratio (% wie 4)
- Sleeping HRV (ms)
- Sleep Stability (Text wie "Moderate awakenings, generally stable sleep")

Antworte NUR so (komma-getrennt):
hr, skin_temp, skin_offset, sleep_min, efficiency, goal_gap, awake_ratio, hrv, stability

Beispiel: 44, 35.47, -0.13, 483, 91, 3, 4, 111, Moderate awakenings

Wenn ein Wert fehlt: 0 oder leer für Text"""
    return process_image_with_claude(image_data, prompt)

def parse_ringconn_duration(image_data):
    """Screenshot 3: Sleep Duration - Time Asleep, Time in Bed, Bedtime, Wake Time"""
    prompt = """Analysiere diesen Ringconn Sleep Duration Screenshot.

Extrahiere:
- Time Asleep (in Minuten: 8hr3min = 483)
- Time in Bed (in Minuten: 8hr50min = 530)
- Sleep Efficiency (%)
- Bedtime (Format HH:MM wie 22:47)
- Wake Time (Format HH:MM wie 07:37)

Antworte NUR so (komma-getrennt):
sleep_min, bed_min, efficiency, bedtime, wake_time

Beispiel: 483, 530, 91, 22:47, 07:37

Wenn ein Wert fehlt: 0 oder leer"""
    return process_image_with_claude(image_data, prompt)

def parse_ringconn_stages_percent(image_data):
    """Screenshot 4: Sleep Stages mit % und Minuten"""
    prompt = """Analysiere diesen Ringconn Sleep Stages Screenshot.

Extrahiere für jede Phase Prozent UND Minuten:
- Awake: Prozent und Minuten (z.B. 4.4% und 22min)
- REM: Prozent und Minuten (z.B. 9.9% und 50min)
- Light Sleep: Prozent und Minuten (z.B. 70.9% und 5hr58min = 358min)
- Deep Sleep: Prozent und Minuten (z.B. 14.8% und 1hr15min = 75min)

Antworte NUR so (komma-getrennt):
awake_pct, awake_min, rem_pct, rem_min, light_pct, light_min, deep_pct, deep_min

Beispiel: 4.4, 22, 9.9, 50, 70.9, 358, 14.8, 75

Wenn ein Wert fehlt: 0"""
    return process_image_with_claude(image_data, prompt)

def parse_ringconn_stages_hr(image_data):
    """Screenshot 5: Sleep Stages mit HR pro Stage"""
    prompt = """Analysiere diesen Ringconn Sleep Stages Screenshot mit Herzfrequenz pro Phase.

Extrahiere die durchschnittliche HR für jede Phase:
- Awake: AVG.HR (bpm)
- REM: AVG.HR (bpm)
- Light Sleep: AVG.HR (bpm)
- Deep Sleep: AVG.HR (bpm)

Antworte NUR so (komma-getrennt):
hr_awake, hr_rem, hr_light, hr_deep

Beispiel: 45, 51, 42, 49

Wenn ein Wert fehlt: 0"""
    return process_image_with_claude(image_data, prompt)

def parse_ringconn_heart_rate(image_data):
    """Screenshot 6: Heart Rate Details"""
    prompt = """Analysiere diesen Ringconn Heart Rate Screenshot.

Extrahiere:
- Average Heart Rate (bpm)
- Recent 7-night Average (bpm)
- Min HR (niedrigster Wert im Graph)
- Max HR (höchster Wert im Graph)

Antworte NUR so (komma-getrennt):
avg_hr, 7night_avg, min_hr, max_hr

Beispiel: 44, 46, 37, 57

Wenn ein Wert fehlt: 0"""
    return process_image_with_claude(image_data, prompt)

def parse_ringconn_hrv(image_data):
    """Screenshot 7: HRV Details"""
    prompt = """Analysiere diesen Ringconn HRV Screenshot.

Extrahiere:
- Average HRV (ms)
- Recent 7-night Average (ms)
- Min HRV (niedrigster Wert im Graph)
- Max HRV (höchster Wert im Graph)

Antworte NUR so (komma-getrennt):
avg_hrv, 7night_avg, min_hrv, max_hrv

Beispiel: 111, 110, 37, 182

Wenn ein Wert fehlt: 0"""
    return process_image_with_claude(image_data, prompt)

def parse_ringconn_spo2_temp(image_data):
    """Screenshot 8: SpO2 und Skin Temperature"""
    prompt = """Analysiere diesen Ringconn Screenshot mit SpO2 und Skin Temperature.

Extrahiere:
- SpO2 Average (%)
- SpO2 7-night Average (%)
- SpO2 Min (niedrigster Wert)
- Skin Temperature Average (°C)
- Skin Temperature Baseline (°C)
- Skin Temperature Offset (z.B. -0.13)

Antworte NUR so (komma-getrennt):
spo2_avg, spo2_7night, spo2_min, skin_temp, skin_baseline, skin_offset

Beispiel: 96, 96, 94, 35.47, 35.6, -0.13

Wenn ein Wert fehlt: 0"""
    return process_image_with_claude(image_data, prompt)

def parse_ringconn_respiratory(image_data):
    """Screenshot 9: Respiratory Rate"""
    prompt = """Analysiere diesen Ringconn Respiratory Rate Screenshot.

Extrahiere:
- Respiratory Rate Average (bpm)
- Respiratory Rate Range (z.B. 13.9~17.5)
- Recent 7-day Average

Antworte NUR so (komma-getrennt):
resp_avg, resp_min, resp_max, resp_7day

Beispiel: 15.5, 13.9, 17.5, 15.4

Wenn ein Wert fehlt: 0"""
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
            start_time = e['start'].get('dateTime', e['start'].get('date'))
            if 'T' in start_time:
                t = datetime.fromisoformat(start_time.replace('Z', '+00:00')).strftime('%H:%M')
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
            range='Exercise!A:C'
        ).execute()
        values = result.get('values', [])
        
        now = datetime.now(TIMEZONE)
        start_of_week = now - timedelta(days=now.weekday())
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0)
        
        count = 0
        for row in values[1:]:
            if len(row) >= 3:
                try:
                    date = datetime.strptime(row[0], '%Y-%m-%d')
                    date = TIMEZONE.localize(date)
                    if date >= start_of_week and 'sauna' in row[2].lower():
                        count += 1
                except:
                    continue
        return count
    except:
        return 0

def parse_yes_no(val):
    """Convert ja/nein to YES/NO"""
    val = val.strip().lower()
    if val in ['ja', 'yes', 'y', 'j', '1', 'true']:
        return 'YES'
    elif val in ['nein', 'no', 'n', '0', 'false']:
        return 'NO'
    return val  # Return as-is if it's a time or other value

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

📊 **Ringconn Step 1/9: Sleep Score**
→ Screenshot mit dem Sleep Score (90 Excellent etc.)
→ Oder: `skip` / `alle` (für alle skip)"""
    
    user_state[CHAT_ID] = {
        "step": "ringconn_1",
        "ringconn_data": {},
        "screenshot_count": 0
    }
    bot.send_message(CHAT_ID, msg)

def send_ringconn_step(step_num):
    """Send appropriate ringconn step request"""
    prompts = {
        2: ("Summary", "Screenshot mit Excellent/Good Summary (RHR, HRV, Efficiency etc.)"),
        3: ("Duration", "Screenshot mit Time Asleep, Time in Bed, Bedtime, Wake Time"),
        4: ("Stages %", "Screenshot mit Sleep Stages % und Minuten (Awake, REM, Light, Deep)"),
        5: ("Stages HR", "Screenshot mit Sleep Stages HR (AVG.HR pro Phase)"),
        6: ("Heart Rate", "Screenshot mit Heart Rate Details"),
        7: ("HRV", "Screenshot mit HRV Details"),
        8: ("SpO2 & Temp", "Screenshot mit SpO2 und Skin Temperature"),
        9: ("Respiratory", "Screenshot mit Respiratory Rate")
    }
    
    title, desc = prompts.get(step_num, ("Unknown", ""))
    msg = f"""📊 **Ringconn Step {step_num}/9: {title}**
→ {desc}
→ Oder: `skip`"""
    
    user_state[CHAT_ID]["step"] = f"ringconn_{step_num}"
    bot.send_message(CHAT_ID, msg)

def finalize_ringconn():
    """Combine all ringconn data and log"""
    data = user_state[CHAT_ID].get("ringconn_data", {})
    
    if any(data.values()):
        success, msg = log_health_complete(data)
        
        summary_parts = []
        if data.get('sleep_score'):
            summary_parts.append(f"Score: {data['sleep_score']}")
        if data.get('time_asleep_min'):
            hours = round(int(data['time_asleep_min']) / 60, 1)
            summary_parts.append(f"Sleep: {hours}h")
        if data.get('sleeping_hrv'):
            summary_parts.append(f"HRV: {data['sleeping_hrv']}ms")
        if data.get('deep_min'):
            summary_parts.append(f"Deep: {data['deep_min']}min")
        
        if success:
            bot.send_message(CHAT_ID, f"✅ Ringconn komplett geloggt!\n{', '.join(summary_parts)}")
        else:
            bot.send_message(CHAT_ID, f"❌ Fehler: {msg}")
    else:
        bot.send_message(CHAT_ID, "⏭️ Ringconn übersprungen")
    
    send_morning_steps()

def send_morning_steps():
    """Ask for steps count"""
    msg = """👟 **Steps gestern?**
→ Zahl eingeben (z.B. `8500`)
→ Oder: `skip`"""
    
    user_state[CHAT_ID]["step"] = "morning_steps"
    bot.send_message(CHAT_ID, msg)

def send_morning_sleep_supplements():
    """Ask for sleep supplements from yesterday"""
    msg = """💊 **Schlaf-Supplements gestern genommen?**
→ Magnesium + Glycin (ja/nein)
→ Beispiel: `ja` oder `nein`"""
    
    user_state[CHAT_ID]["step"] = "morning_sleep_supplements"
    bot.send_message(CHAT_ID, msg)

def send_morning_fluid_cutoff():
    """Ask for fluid cutoff yesterday (20:30)"""
    msg = """💧 **Fluid Cutoff gestern eingehalten?** (20:30)
→ `ja` oder `nein`"""
    
    user_state[CHAT_ID]["step"] = "morning_fluid_cutoff"
    bot.send_message(CHAT_ID, msg)

def send_morning_sleep():
    """Ask for subjective sleep"""
    msg = """😴 **Subjektiver Schlaf?**
→ Erholt, Aufstehen, Träume, Body, Klarheit (1-10)
→ Beispiel: `7 8 6 7 8`
→ Oder: `skip`"""
    
    user_state[CHAT_ID]["step"] = "morning_sleep"
    bot.send_message(CHAT_ID, msg)

def send_morning_cutoffs():
    """Ask for yesterday's cutoffs"""
    msg = """🚫 **Cutoffs gestern eingehalten?**
→ THC, Essen, Nikotin, Koffein, Screens (ja/nein)
→ Beispiel: `ja ja nein ja ja`
→ Mit Zeiten: `ja 21:30 nein 22:15 ja`
→ Oder: `skip`"""
    
    user_state[CHAT_ID]["step"] = "morning_cutoffs"
    bot.send_message(CHAT_ID, msg)

def send_evening_check():
    """Evening check at 22:30"""
    sauna_count = get_sauna_count_this_week()
    
    msg = f"""🌙 Tagesreview!

🧖 Sauna diese Woche: {sauna_count}/4

---

🏋️ **Exercise heute?** (mehrere mit Komma trennen)
→ Format: `typ dauer ort`
→ Beispiel: `sauna 20 gofit` oder `gym 60 legs, cardio 30`
→ Oder: `nein`"""
    
    user_state[CHAT_ID] = {"step": "evening_exercise"}
    bot.send_message(CHAT_ID, msg)

def send_evening_meals():
    """Ask for meals"""
    msg = """🍽️ **Meals heute?** (mehrere mit | trennen)
→ Foto schicken ODER
→ Text: `zeit zutaten | zeit zutaten`
→ Beispiel: `09:30 oats milk honey | 18:00 chicken rice veggies`
→ Oder: `nein`"""
    
    user_state[CHAT_ID]["step"] = "evening_meals"
    bot.send_message(CHAT_ID, msg)

def send_evening_learning():
    """Ask for learning"""
    msg = """🧠 **Learning heute?** (mehrere mit Komma trennen)
→ Format: `topic dauer methode`
→ Beispiel: `neuro 60 lecture` oder `stats 45 anki, spanish 30 app`
→ Oder: `nein`"""
    
    user_state[CHAT_ID]["step"] = "evening_learning"
    bot.send_message(CHAT_ID, msg)

def send_evening_cravings():
    """Ask for cravings"""
    msg = """😤 **Cravings heute?** (mehrere mit Komma trennen)
→ Format: `typ intensität`
→ Beispiel: `thc 7` oder `thc 8, nikotin 5, sugar 3`
→ Oder: `nein`"""
    
    user_state[CHAT_ID]["step"] = "evening_cravings"
    bot.send_message(CHAT_ID, msg)

def send_evening_finance():
    """Ask for expenses"""
    msg = """💰 **Ausgaben heute?** (mehrere mit Komma trennen)
→ Format: `betrag kategorie`
→ Beispiel: `15 food` oder `30 transport, 12 food`
→ Oder: `nein`"""
    
    user_state[CHAT_ID]["step"] = "evening_finance"
    bot.send_message(CHAT_ID, msg)

def send_evening_supplements():
    """Ask for supplements"""
    msg = """💊 **Supplements heute?**
→ Blueprint Stack? (ja/nein)
→ Omega3? (ja/nein)
→ NAC? (ja/nein)
→ Collagen? (ja/nein)

Beispiel: `ja ja ja nein`
→ Oder: `nein` für alle"""
    
    user_state[CHAT_ID]["step"] = "evening_supplements"
    bot.send_message(CHAT_ID, msg)

def send_evening_habits():
    """Ask for habits"""
    msg = """✨ **Habits heute?**
→ Sonnenlicht morgens (Minuten)
→ Blaulichtbrille (ja/nein)
→ Meditation (Minuten)
→ Breathwork (Minuten)
→ Reading (Minuten)
→ Social Interaction (ja/nein)
→ Hydration (1-10)

Beispiel: `15 ja 10 5 30 ja 8`
→ Oder: `skip`"""
    
    user_state[CHAT_ID]["step"] = "evening_habits"
    bot.send_message(CHAT_ID, msg)

def send_evening_gratitude():
    """Ask for gratitude"""
    msg = """🙏 **Wofür bist du heute dankbar?**
→ Einfach Text eingeben
→ Oder: `skip`"""
    
    user_state[CHAT_ID]["step"] = "evening_gratitude"
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
/supplements - Supplements loggen
/habits - Habits loggen
/mood - Mood loggen

**Quick-Log:** Einfach schreiben:
• `sauna 20 gofit`
• `meal oats milk honey`
• `learn neuro 45`""")

@bot.message_handler(commands=['quick', 'logs', 'formats'])
def cmd_quick(message):
    bot.reply_to(message, """📝 **Quick-Log Formate**

**Exercise:** (mehrere mit Komma)
`sauna 20 gofit`
`gym 45 legs, cardio 30`

**Meals:**
`meal oats milk banana honey`
`meal zeit zutaten` (z.B. `meal 12:30 pasta tomatoes`)

**Learning:** (mehrere mit Komma)
`learn neuro 45`
`learn stats 30 anki, spanish 20`

**Cravings:** (mehrere mit Komma)
`craving thc 7`
`craving thc 8, sugar 5`

**Finance:** (mehrere mit Komma)
`spent 15 food`
`spent 30 transport, 12 food`

**Supplements:**
`supps ja ja nein ja` (Blueprint, Omega3, NAC, Collagen)

**Mood:**
`mood 7 6 8 3 4 7 5` (mood energy focus anxiety stress motivation social)

**Habits:**
`habits 15 ja 10 5 30 ja 8` (sun blue med breath read social hydration)

**Foto:** Einfach schicken → dann `meal` oder `ringconn` sagen""")

@bot.message_handler(commands=['morning'])
def cmd_morning(message):
    send_morning_check()

@bot.message_handler(commands=['evening'])
def cmd_evening(message):
    send_evening_check()

@bot.message_handler(commands=['supplements'])
def cmd_supplements(message):
    send_evening_supplements()

@bot.message_handler(commands=['habits'])
def cmd_habits(message):
    send_evening_habits()

@bot.message_handler(commands=['mood'])
def cmd_mood(message):
    bot.reply_to(message, """🎭 **Mood loggen**
→ Format: mood energy focus anxiety stress motivation social
→ Alle 1-10
→ Beispiel: `mood 7 6 8 3 4 7 5`""")
    user_state[message.chat.id] = {"step": "quick_mood"}

@bot.message_handler(commands=['testproactive'])
def cmd_test_proactive(message):
    """Test that proactive messaging works"""
    bot.reply_to(message, "🧪 Teste proaktive Nachricht in 10 Sekunden...")
    import threading
    def delayed_test():
        import time
        time.sleep(10)
        bot.send_message(CHAT_ID, "✅ Proaktive Nachricht funktioniert!")
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
    
    # Ringconn steps 1-9
    if state and state.startswith("ringconn_"):
        step_num = int(state.split("_")[1])
        
        parsers = {
            1: ("Sleep Score", parse_ringconn_sleep_score),
            2: ("Summary", parse_ringconn_summary),
            3: ("Duration", parse_ringconn_duration),
            4: ("Stages %", parse_ringconn_stages_percent),
            5: ("Stages HR", parse_ringconn_stages_hr),
            6: ("Heart Rate", parse_ringconn_heart_rate),
            7: ("HRV", parse_ringconn_hrv),
            8: ("SpO2 & Temp", parse_ringconn_spo2_temp),
            9: ("Respiratory", parse_ringconn_respiratory)
        }
        
        title, parser = parsers.get(step_num, ("Unknown", None))
        if parser:
            bot.reply_to(message, f"🔄 Analysiere {title}...")
            result = parser(image_data)
            
            try:
                values = [x.strip() for x in result.split(',')]
                data = user_state[CHAT_ID].get("ringconn_data", {})
                
                # Map values based on step
                if step_num == 1 and len(values) >= 3:
                    data['sleep_score'] = values[0]
                    data['time_asleep_min'] = values[1]
                    data['sleep_efficiency'] = values[2]
                    bot.reply_to(message, f"✅ Score: {values[0]}, Sleep: {values[1]}min, Eff: {values[2]}%")
                
                elif step_num == 2 and len(values) >= 9:
                    data['sleeping_hr'] = values[0]
                    data['skin_temp'] = values[1]
                    data['skin_temp_offset'] = values[2]
                    data['time_asleep_min'] = values[3] if values[3] != '0' else data.get('time_asleep_min', '')
                    data['sleep_efficiency'] = values[4] if values[4] != '0' else data.get('sleep_efficiency', '')
                    data['sleep_goal_gap'] = values[5]
                    data['time_awake_ratio'] = values[6]
                    data['sleeping_hrv'] = values[7]
                    data['sleep_stability'] = values[8]
                    bot.reply_to(message, f"✅ HR: {values[0]}bpm, HRV: {values[7]}ms, Temp: {values[1]}°C")
                
                elif step_num == 3 and len(values) >= 5:
                    data['time_asleep_min'] = values[0] if values[0] != '0' else data.get('time_asleep_min', '')
                    data['time_in_bed_min'] = values[1]
                    data['sleep_efficiency'] = values[2] if values[2] != '0' else data.get('sleep_efficiency', '')
                    data['bedtime'] = values[3]
                    data['wake_time'] = values[4]
                    bot.reply_to(message, f"✅ Bed: {values[3]}, Wake: {values[4]}, In Bed: {values[1]}min")
                
                elif step_num == 4 and len(values) >= 8:
                    data['awake_pct'] = values[0]
                    data['awake_min'] = values[1]
                    data['rem_pct'] = values[2]
                    data['rem_min'] = values[3]
                    data['light_pct'] = values[4]
                    data['light_min'] = values[5]
                    data['deep_pct'] = values[6]
                    data['deep_min'] = values[7]
                    bot.reply_to(message, f"✅ Deep: {values[7]}min ({values[6]}%), REM: {values[3]}min ({values[2]}%)")
                
                elif step_num == 5 and len(values) >= 4:
                    data['hr_awake'] = values[0]
                    data['hr_rem'] = values[1]
                    data['hr_light'] = values[2]
                    data['hr_deep'] = values[3]
                    bot.reply_to(message, f"✅ HR - Awake: {values[0]}, REM: {values[1]}, Light: {values[2]}, Deep: {values[3]}")
                
                elif step_num == 6 and len(values) >= 4:
                    data['sleeping_hr'] = values[0] if values[0] != '0' else data.get('sleeping_hr', '')
                    bot.reply_to(message, f"✅ Avg HR: {values[0]}bpm, 7-night: {values[1]}bpm")
                
                elif step_num == 7 and len(values) >= 4:
                    data['sleeping_hrv'] = values[0] if values[0] != '0' else data.get('sleeping_hrv', '')
                    bot.reply_to(message, f"✅ Avg HRV: {values[0]}ms, 7-night: {values[1]}ms")
                
                elif step_num == 8 and len(values) >= 6:
                    data['spo2'] = values[0]
                    data['skin_temp'] = values[3] if values[3] != '0' else data.get('skin_temp', '')
                    data['skin_temp_offset'] = values[5] if values[5] != '0' else data.get('skin_temp_offset', '')
                    bot.reply_to(message, f"✅ SpO2: {values[0]}%, Temp: {values[3]}°C")
                
                elif step_num == 9 and len(values) >= 4:
                    data['respiratory_rate'] = values[0]
                    bot.reply_to(message, f"✅ Resp Rate: {values[0]}bpm")
                
                else:
                    bot.reply_to(message, f"⚠️ Konnte nicht alle Werte lesen:\n{result}")
                
                user_state[CHAT_ID]["ringconn_data"] = data
                
            except Exception as e:
                bot.reply_to(message, f"⚠️ Parsing-Fehler: {e}")
            
            # Move to next step or finalize
            if step_num < 9:
                send_ringconn_step(step_num + 1)
            else:
                finalize_ringconn()
    
    elif state == "evening_meals":
        bot.reply_to(message, "🔄 Analysiere Mahlzeit...")
        ingredients = parse_meal_image(image_data)
        
        now = datetime.now(TIMEZONE).strftime('%H:%M')
        success, msg = log_meal([[now, '', ingredients, '', '', '', '', '', '', 'YES', '']])
        
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
    text = message.text.strip()
    text_lower = text.lower()
    state = user_state.get(chat_id, {}).get("step")
    
    # === PHOTO IDENTIFICATION ===
    if state == "photo_identify":
        stored_image = user_state.get(chat_id, {}).get("image")
        if stored_image:
            if text_lower in ["meal", "essen", "food"]:
                bot.reply_to(message, "🔄 Analysiere Mahlzeit...")
                ingredients = parse_meal_image(stored_image)
                now = datetime.now(TIMEZONE).strftime('%H:%M')
                success, msg = log_meal([[now, '', ingredients, '', '', '', '', '', '', 'YES', '']])
                if success:
                    bot.reply_to(message, f"✅ Meal geloggt: {ingredients}")
                else:
                    bot.reply_to(message, f"❌ Fehler: {msg}")
                user_state[chat_id] = {"step": None}
            elif text_lower in ["ringconn", "ring", "sleep"]:
                bot.reply_to(message, "Starte Ringconn Flow...")
                user_state[chat_id] = {"step": "ringconn_1", "ringconn_data": {}, "image": stored_image}
                # Process as first ringconn screen
                result = parse_ringconn_sleep_score(stored_image)
                try:
                    values = [x.strip() for x in result.split(',')]
                    if len(values) >= 3:
                        user_state[CHAT_ID]["ringconn_data"] = {
                            'sleep_score': values[0],
                            'time_asleep_min': values[1],
                            'sleep_efficiency': values[2]
                        }
                        bot.reply_to(message, f"✅ Score: {values[0]}, Sleep: {values[1]}min")
                except:
                    pass
                send_ringconn_step(2)
            else:
                bot.reply_to(message, "→ Sag `meal` oder `ringconn`")
        return
    
    # === RINGCONN FLOW ===
    if state and state.startswith("ringconn_"):
        step_num = int(state.split("_")[1])
        
        if text_lower == "skip":
            if step_num < 9:
                send_ringconn_step(step_num + 1)
            else:
                finalize_ringconn()
        elif text_lower == "alle":
            # Skip all remaining screenshots
            finalize_ringconn()
        else:
            bot.reply_to(message, "📸 Bitte Screenshot schicken oder `skip`")
        return
    
    # === MORNING FLOW ===
    
    if state == "morning_steps":
        if text_lower == "skip":
            send_morning_sleep_supplements()
        else:
            try:
                steps = int(text.replace('.', '').replace(',', ''))
                today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
                # Update or add steps to today's health row
                data = user_state[CHAT_ID].get("ringconn_data", {})
                data['steps'] = str(steps)
                user_state[CHAT_ID]["ringconn_data"] = data
                bot.reply_to(message, f"✅ Steps: {steps}")
            except:
                bot.reply_to(message, "⚠️ Bitte eine Zahl eingeben")
                return
            send_morning_sleep_supplements()
        return
    
    if state == "morning_sleep_supplements":
        val = parse_yes_no(text_lower)
        today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
        # Log to supplements sheet column G (Schlaf)
        # We'll add this to a supplements entry
        user_state[CHAT_ID]["sleep_supps"] = val
        bot.reply_to(message, f"✅ Schlaf-Supplements: {val}")
        send_morning_fluid_cutoff()
        return
    
    if state == "morning_fluid_cutoff":
        val = parse_yes_no(text_lower)
        data = user_state[CHAT_ID].get("ringconn_data", {})
        data['fluid_cut_off'] = val
        user_state[CHAT_ID]["ringconn_data"] = data
        bot.reply_to(message, f"✅ Fluid Cutoff (20:30): {val}")
        send_morning_sleep()
        return
    
    if state == "morning_sleep":
        if text_lower == "skip":
            send_morning_cutoffs()
        else:
            values = text.split()
            if len(values) >= 5:
                try:
                    erholt, aufstehen, traume, body, klarheit = [int(v) for v in values[:5]]
                    avg = round((erholt + aufstehen + traume + body + klarheit) / 5, 1)
                    
                    data = user_state[CHAT_ID].get("ringconn_data", {})
                    data['subjective_erholt'] = str(erholt)
                    data['subjective_aufstehen'] = str(aufstehen)
                    data['subjective_traume'] = str(traume)
                    data['subjective_body'] = str(body)
                    data['subjective_klarheit'] = str(klarheit)
                    data['subjective_avg'] = str(avg)
                    user_state[CHAT_ID]["ringconn_data"] = data
                    
                    bot.reply_to(message, f"✅ Subjektiv geloggt! Ø {avg}")
                except:
                    bot.reply_to(message, "⚠️ Brauche 5 Zahlen: erholt aufstehen träume body klarheit")
                    return
            else:
                bot.reply_to(message, "⚠️ Brauche 5 Werte: erholt aufstehen träume body klarheit")
                return
            send_morning_cutoffs()
        return
    
    if state == "morning_cutoffs":
        if text_lower == "skip":
            # Finalize health logging
            data = user_state[CHAT_ID].get("ringconn_data", {})
            if data:
                success, msg = log_health_complete(data)
                if success:
                    bot.reply_to(message, "✅ Morning Check komplett! Guten Tag! ☀️")
                else:
                    bot.reply_to(message, f"⚠️ Health Log Fehler: {msg}")
            user_state[chat_id] = {"step": None}
        else:
            # Parse cutoffs: thc essen nikotin koffein screens
            parts = text.split()
            data = user_state[CHAT_ID].get("ringconn_data", {})
            
            # Map cutoffs with optional times
            cutoff_fields = [
                ('thc_ok', 'thc_time'),
                ('essen_ok', 'essen_time'),
                ('nikotin_ok', 'nikotin_time'),
                ('koffein_ok', 'koffein_time'),
                ('screens_ok', 'screens_time')
            ]
            
            i = 0
            for ok_field, time_field in cutoff_fields:
                if i < len(parts):
                    val = parse_yes_no(parts[i])
                    data[ok_field] = val
                    i += 1
                    # Check if next value is a time
                    if i < len(parts) and ':' in parts[i]:
                        data[time_field] = parts[i]
                        i += 1
            
            user_state[CHAT_ID]["ringconn_data"] = data
            
            # Finalize health logging
            success, msg = log_health_complete(data)
            if success:
                bot.reply_to(message, "✅ Morning Check komplett! Guten Tag! ☀️")
            else:
                bot.reply_to(message, f"⚠️ Fehler: {msg}")
            
            user_state[chat_id] = {"step": None}
        return
    
    # === EVENING FLOW ===
    
    if state == "evening_exercise":
        if text_lower == "nein":
            send_evening_meals()
        else:
            # Parse multiple exercises: typ dauer ort, typ dauer ort
            entries = []
            exercises = text.split(',')
            for ex in exercises:
                parts = ex.strip().split()
                if len(parts) >= 2:
                    typ = parts[0].capitalize()
                    dauer = parts[1]
                    ort = parts[2] if len(parts) > 2 else ""
                    # [type, duration, location, workout_type, intensity, rpe, stretching, sauna_temp, sauna_rounds, sauna_time, vo2max, notes]
                    entries.append([typ, dauer, ort, '', '', '', '', '', '', '', '', ''])
            
            if entries:
                success, msg = log_exercise(entries)
                sauna_count = get_sauna_count_this_week()
                has_sauna = any('sauna' in e[0].lower() for e in entries)
                extra = f" (Sauna: {sauna_count}/4)" if has_sauna else ""
                bot.reply_to(message, f"✅ {msg}{extra}")
            send_evening_meals()
        return
    
    if state == "evening_meals":
        if text_lower in ["nein", "done"]:
            send_evening_learning()
        else:
            # Parse: zeit zutaten | zeit zutaten
            entries = []
            meals = text.split('|')
            for meal in meals:
                parts = meal.strip().split(' ', 1)
                if len(parts) >= 2:
                    zeit = parts[0]
                    zutaten = parts[1]
                    # [time, meal_num, ingredients, calories, protein, carbs, fat, fiber, category, before_cutoff, notes]
                    entries.append([zeit, '', zutaten, '', '', '', '', '', '', 'YES', ''])
                elif len(parts) == 1:
                    now = datetime.now(TIMEZONE).strftime('%H:%M')
                    entries.append([now, '', parts[0], '', '', '', '', '', '', 'YES', ''])
            
            if entries:
                success, msg = log_meal(entries)
                bot.reply_to(message, f"✅ {msg}")
            send_evening_learning()
        return
    
    if state == "evening_learning":
        if text_lower == "nein":
            send_evening_cravings()
        else:
            # Parse multiple: topic dauer methode, topic dauer methode
            entries = []
            sessions = text.split(',')
            for sess in sessions:
                parts = sess.strip().split()
                if len(parts) >= 2:
                    topic = parts[0]
                    dauer = parts[1]
                    method = parts[2] if len(parts) > 2 else ""
                    # [start_time, end_time, duration_min, task, category, focus_quality, notes]
                    entries.append(['', '', dauer, topic, method, '', ''])
            
            if entries:
                success, msg = log_learning(entries)
                bot.reply_to(message, f"✅ {msg}")
            send_evening_cravings()
        return
    
    if state == "evening_cravings":
        if text_lower == "nein":
            bot.reply_to(message, "✅ Clean day! 💪")
            send_evening_finance()
        else:
            # Parse: typ intensität, typ intensität
            entries = []
            cravings = text.split(',')
            for cr in cravings:
                parts = cr.strip().split()
                if len(parts) >= 2:
                    try:
                        typ = parts[0]
                        intensity = int(parts[1])
                        # [type, intensity, before_cutoff, action, notes]
                        entries.append([typ, str(intensity), '', '', ''])
                    except ValueError:
                        continue
            
            if entries:
                success, msg = log_craving(entries)
                logged = [f"{e[0]} ({e[1]}/10)" for e in entries]
                bot.reply_to(message, f"✅ {msg}: {', '.join(logged)}")
            else:
                bot.reply_to(message, "⚠️ Format: typ intensität, typ intensität")
            send_evening_finance()
        return
    
    if state == "evening_finance":
        if text_lower == "nein":
            send_evening_supplements()
        else:
            # Parse: betrag kategorie, betrag kategorie
            entries = []
            expenses = text.split(',')
            for exp in expenses:
                parts = exp.strip().split()
                if len(parts) >= 2:
                    betrag = parts[0]
                    kategorie = parts[1]
                    desc = ' '.join(parts[2:]) if len(parts) > 2 else ''
                    # [amount, category, description, necessary, impulse, notes]
                    entries.append([betrag, kategorie, desc, '', '', ''])
            
            if entries:
                success, msg = log_finance(entries)
                bot.reply_to(message, f"✅ {msg}")
            send_evening_supplements()
        return
    
    if state == "evening_supplements":
        if text_lower == "nein":
            # Log all NO
            success, msg = log_supplements(['NO', 'NO', 'NO', 'NO', 'NO', ''])
            bot.reply_to(message, "✅ Keine Supplements")
        else:
            parts = text.split()
            # Blueprint, Omega3, NAC, Collagen
            blueprint = parse_yes_no(parts[0]) if len(parts) > 0 else 'NO'
            omega3 = parse_yes_no(parts[1]) if len(parts) > 1 else 'NO'
            nac = parse_yes_no(parts[2]) if len(parts) > 2 else 'NO'
            collagen = parse_yes_no(parts[3]) if len(parts) > 3 else 'NO'
            
            # [Blueprint_Stack, Omega3, ProButyrate, Collagen, NAC, Notes]
            # Note: NAC and Collagen order in sheet
            success, msg = log_supplements([blueprint, omega3, '', collagen, nac, ''])
            if success:
                logged = []
                if blueprint == 'YES': logged.append('Blueprint')
                if omega3 == 'YES': logged.append('Omega3')
                if nac == 'YES': logged.append('NAC')
                if collagen == 'YES': logged.append('Collagen')
                bot.reply_to(message, f"✅ Supplements: {', '.join(logged) if logged else 'Keine'}")
        send_evening_habits()
        return
    
    if state == "evening_habits":
        if text_lower == "skip":
            send_evening_gratitude()
        else:
            parts = text.split()
            # sun, blue, med, breath, read, social, hydration
            if len(parts) >= 7:
                sun = parts[0]
                blue = parse_yes_no(parts[1])
                med = parts[2]
                breath = parts[3]
                read = parts[4]
                social = parse_yes_no(parts[5])
                hydration = parts[6]
                
                # [Sunlight_Morning_Min, Blue_Light_Glasses, Meditation_Min, Breathwork_Min, 
                #  Reading_Min, Social_Interaction, Grateful_For, Hydration, Notes]
                success, msg = log_habits([sun, blue, med, breath, read, social, '', hydration, ''])
                if success:
                    bot.reply_to(message, f"✅ Habits geloggt!")
                else:
                    bot.reply_to(message, f"❌ {msg}")
            else:
                bot.reply_to(message, "⚠️ Brauche 7 Werte: sun blue med breath read social hydration")
                return
            send_evening_gratitude()
        return
    
    if state == "evening_gratitude":
        if text_lower == "skip":
            pass
        else:
            # Update today's habits row with gratitude text
            today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
            row_num = find_row_by_date('Habits', today)
            if row_num:
                update_cell('Habits', f'G{row_num}', text)
                bot.reply_to(message, "✅ Dankbarkeit geloggt! 🙏")
            else:
                # Create new habits entry just with gratitude
                success, msg = log_habits(['', '', '', '', '', '', text, '', ''])
                if success:
                    bot.reply_to(message, "✅ Dankbarkeit geloggt! 🙏")
        send_evening_done()
        return
    
    if state == "quick_mood":
        parts = text.split()
        if len(parts) >= 7:
            # [time, mood, energy, focus, anxiety, stress, motivation, social_battery, trigger, notes]
            now = datetime.now(TIMEZONE).strftime('%H:%M')
            success, msg = log_mood([now] + parts[:7] + ['', ''])
            if success:
                bot.reply_to(message, "✅ Mood geloggt!")
            else:
                bot.reply_to(message, f"❌ {msg}")
        else:
            bot.reply_to(message, "⚠️ Brauche 7 Werte: mood energy focus anxiety stress motivation social")
        user_state[chat_id] = {"step": None}
        return
    
    # === QUICK LOGS (no active state) ===
    
    # Exercise quick log
    if re.match(r'^(sauna|gym|workout|cardio|run|walk|swim|bike|yoga)\s+\d+', text_lower):
        entries = []
        exercises = text.split(',')
        for ex in exercises:
            parts = ex.strip().split()
            if len(parts) >= 2:
                typ = parts[0].capitalize()
                dauer = parts[1]
                ort = parts[2] if len(parts) > 2 else ""
                entries.append([typ, dauer, ort, '', '', '', '', '', '', '', '', ''])
        
        if entries:
            success, msg = log_exercise(entries)
            sauna_count = get_sauna_count_this_week()
            has_sauna = any('sauna' in e[0].lower() for e in entries)
            extra = f"\n🧖 Sauna: {sauna_count}/4" if has_sauna else ""
            bot.reply_to(message, f"✅ {msg}{extra}")
        return
    
    # Meal quick log
    if text_lower.startswith('meal '):
        ingredients = text[5:]
        now = datetime.now(TIMEZONE).strftime('%H:%M')
        # Check if first word is a time
        parts = ingredients.split(' ', 1)
        if ':' in parts[0]:
            zeit = parts[0]
            ingr = parts[1] if len(parts) > 1 else ''
        else:
            zeit = now
            ingr = ingredients
        
        success, msg = log_meal([[zeit, '', ingr, '', '', '', '', '', '', 'YES', '']])
        if success:
            bot.reply_to(message, "✅ Meal geloggt!")
        else:
            bot.reply_to(message, f"❌ {msg}")
        return
    
    # Learning quick log
    if text_lower.startswith('learn '):
        entries = []
        sessions = text[6:].split(',')
        for sess in sessions:
            parts = sess.strip().split()
            if len(parts) >= 2:
                topic = parts[0]
                dauer = parts[1]
                method = parts[2] if len(parts) > 2 else ""
                entries.append(['', '', dauer, topic, method, '', ''])
        
        if entries:
            success, msg = log_learning(entries)
            bot.reply_to(message, f"✅ {msg}")
        return
    
    # Craving quick log
    if text_lower.startswith('craving '):
        entries = []
        cravings = text[8:].split(',')
        for cr in cravings:
            parts = cr.strip().split()
            if len(parts) >= 2:
                try:
                    typ = parts[0]
                    intensity = int(parts[1])
                    entries.append([typ, str(intensity), '', '', ''])
                except ValueError:
                    continue
        
        if entries:
            success, msg = log_craving(entries)
            bot.reply_to(message, f"✅ {msg}")
        return
    
    # Finance quick log
    if text_lower.startswith('spent '):
        entries = []
        expenses = text[6:].split(',')
        for exp in expenses:
            parts = exp.strip().split()
            if len(parts) >= 2:
                betrag = parts[0]
                kategorie = parts[1]
                entries.append([betrag, kategorie, '', '', '', ''])
        
        if entries:
            success, msg = log_finance(entries)
            bot.reply_to(message, f"✅ {msg}")
        return
    
    # Supplements quick log
    if text_lower.startswith('supps '):
        parts = text[6:].split()
        blueprint = parse_yes_no(parts[0]) if len(parts) > 0 else 'NO'
        omega3 = parse_yes_no(parts[1]) if len(parts) > 1 else 'NO'
        nac = parse_yes_no(parts[2]) if len(parts) > 2 else 'NO'
        collagen = parse_yes_no(parts[3]) if len(parts) > 3 else 'NO'
        
        success, msg = log_supplements([blueprint, omega3, '', collagen, nac, ''])
        if success:
            bot.reply_to(message, "✅ Supplements geloggt!")
        return
    
    # Mood quick log
    if text_lower.startswith('mood '):
        parts = text[5:].split()
        if len(parts) >= 7:
            now = datetime.now(TIMEZONE).strftime('%H:%M')
            success, msg = log_mood([now] + parts[:7] + ['', ''])
            if success:
                bot.reply_to(message, "✅ Mood geloggt!")
        return
    
    # Habits quick log
    if text_lower.startswith('habits '):
        parts = text[7:].split()
        if len(parts) >= 7:
            sun = parts[0]
            blue = parse_yes_no(parts[1])
            med = parts[2]
            breath = parts[3]
            read = parts[4]
            social = parse_yes_no(parts[5])
            hydration = parts[6]
            
            success, msg = log_habits([sun, blue, med, breath, read, social, '', hydration, ''])
            if success:
                bot.reply_to(message, "✅ Habits geloggt!")
        return
    
    # Gratitude quick log (just text)
    if text_lower.startswith('dankbar ') or text_lower.startswith('grateful '):
        gratitude_text = text.split(' ', 1)[1] if ' ' in text else text
        today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
        row_num = find_row_by_date('Habits', today)
        if row_num:
            update_cell('Habits', f'G{row_num}', gratitude_text)
            bot.reply_to(message, "✅ Dankbarkeit geloggt! 🙏")
        else:
            success, msg = log_habits(['', '', '', '', '', '', gratitude_text, '', ''])
            if success:
                bot.reply_to(message, "✅ Dankbarkeit geloggt! 🙏")
        return
    
    # Default: send to Claude for general chat
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
    print("🚀 Zeroism Coach Bot v3 starting...")
    scheduler = start_scheduler()
    print("📱 Bot polling...")
    bot.infinity_polling()
