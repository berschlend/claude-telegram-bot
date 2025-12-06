#!/usr/bin/env python3
"""
ZEROISM BOT v3.1 - Complete Health & Life Optimization Tracker
Changes from v3:
- 9 Ringconn screenshots instead of 8
- Steps as manual input (no screenshot)
- Supplements asked individually (not conditional)
- Stackable answers with comma separator
- Fixed gratitude text input
- Added habits to evening flow
- Meta-commands in quick-logs
"""

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
from collections import defaultdict
import time

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

# Sheet names
SHEETS = {
    'health': 'HEALTH',
    'exercise': 'EXERCISE',
    'meals': 'MEALS',
    'mood': 'MOOD',
    'supplements': 'SUPPLEMENTS',
    'habits': 'HABITS',
    'learning': 'LEARNING',
    'cravings': 'CRAVINGS',
    'finance': 'FINANCE'
}

# === INIT ===
bot = telebot.TeleBot(TELEGRAM_TOKEN)
claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# State tracking
user_state = {}
temp_data = defaultdict(dict)
collected_images = defaultdict(list)

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

# === SHEET OPERATIONS ===

def log_to_sheet(sheet_name, row_data):
    """Append data to sheet"""
    try:
        service = get_sheets_service()
        if not service:
            return False, "Google Sheets nicht verfügbar"
        
        # Fix date format - if first column is a date, prefix with apostrophe to prevent serial number
        if row_data and row_data[0] and isinstance(row_data[0], str) and '-' in row_data[0]:
            # Keep date as-is, Google will handle it correctly with RAW
            pass
        
        service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=f'{sheet_name}!A:BZ',
            valueInputOption='RAW',  # Changed from USER_ENTERED to prevent date conversion
            insertDataOption='INSERT_ROWS',
            body={'values': [row_data]}
        ).execute()
        
        return True, "Geloggt"
    except Exception as e:
        return False, str(e)

def update_row_in_sheet(sheet_name, row_number, col_start, col_end, values):
    """Update specific cells in existing row"""
    try:
        service = get_sheets_service()
        if not service:
            return False, "Google Sheets nicht verfügbar"
        
        range_str = f'{sheet_name}!{col_start}{row_number}:{col_end}{row_number}'
        
        service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=range_str,
            valueInputOption='RAW',  # Changed from USER_ENTERED
            body={'values': [values]}
        ).execute()
        
        return True, "Updated"
    except Exception as e:
        return False, str(e)

def find_row_by_date(sheet_name, date_str):
    """Find row number for specific date"""
    try:
        service = get_sheets_service()
        if not service:
            return None
        
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f'{sheet_name}!A:A'
        ).execute()
        
        values = result.get('values', [])
        for i, row in enumerate(values):
            if row and row[0] == date_str:
                return i + 1
        return None
    except:
        return None

def get_sheet_data(sheet_name, range_str):
    """Get data from sheet"""
    try:
        service = get_sheets_service()
        if not service:
            return None
        
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f'{sheet_name}!{range_str}'
        ).execute()
        
        return result.get('values', [])
    except:
        return None

# === LOGGING FUNCTIONS ===

def log_health_ringconn(data):
    """Log Ringconn sleep data to HEALTH sheet (A-AF, columns 1-32)"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    
    row = [
        today,                                    # A: Date
        data.get('sleep_score', ''),              # B: Sleep_Score
        data.get('sleep_quality', ''),            # C: Sleep_Quality
        data.get('time_asleep_min', ''),          # D: Time_Asleep_Min
        data.get('time_in_bed_min', ''),          # E: Time_In_Bed_Min
        data.get('sleep_efficiency', ''),         # F: Sleep_Efficiency
        data.get('sleep_goal_gap', ''),           # G: Sleep_Goal_Gap
        data.get('time_awake_ratio', ''),         # H: Time_Awake_Ratio
        data.get('sleeping_hr', ''),              # I: Sleeping_HR
        data.get('sleeping_hrv', ''),             # J: Sleeping_HRV
        data.get('skin_temp', ''),                # K: Skin_Temp
        data.get('skin_temp_offset', ''),         # L: Skin_Temp_Offset
        data.get('spo2', ''),                     # M: SpO2
        data.get('respiratory_rate', ''),         # N: Respiratory_Rate
        data.get('awake_min', ''),                # O: Awake_Min
        data.get('awake_pct', ''),                # P: Awake_Pct
        data.get('rem_min', ''),                  # Q: REM_Min
        data.get('rem_pct', ''),                  # R: REM_Pct
        data.get('light_min', ''),                # S: Light_Min
        data.get('light_pct', ''),                # T: Light_Pct
        data.get('deep_min', ''),                 # U: Deep_Min
        data.get('deep_pct', ''),                 # V: Deep_Pct
        data.get('hr_awake', ''),                 # W: HR_Awake
        data.get('hr_rem', ''),                   # X: HR_REM
        data.get('hr_light', ''),                 # Y: HR_Light
        data.get('hr_deep', ''),                  # Z: HR_Deep
        data.get('rem_latency', ''),              # AA: REM_Latency
        data.get('time_falling_asleep', ''),      # AB: Time_Falling_Asleep
        data.get('time_final_wake', ''),          # AC: Time_Final_Wake
        data.get('sleep_stability', ''),          # AD: Sleep_Stability
        data.get('bedtime', ''),                  # AE: Bedtime
        data.get('wake_time', '')                 # AF: Wake_Time
    ]
    
    return log_to_sheet(SHEETS['health'], row)

def log_health_vitals(weight=None, ear_temp=None, body_fat=None, waist=None, bp_sys=None, bp_dia=None):
    """Log vitals to HEALTH sheet columns AG-AL"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row_num = find_row_by_date(SHEETS['health'], today)
    
    values = [
        weight if weight is not None else '',
        ear_temp if ear_temp is not None else '',
        body_fat if body_fat is not None else '',
        waist if waist is not None else '',
        bp_sys if bp_sys is not None else '',
        bp_dia if bp_dia is not None else ''
    ]
    
    if row_num:
        return update_row_in_sheet(SHEETS['health'], row_num, 'AG', 'AL', values)
    else:
        row = [today] + [''] * 31 + values
        return log_to_sheet(SHEETS['health'], row)

def log_subjective_sleep(data):
    """Log subjective sleep to HEALTH sheet columns AM-AU"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row_num = find_row_by_date(SHEETS['health'], today)
    
    avg = round(sum([
        data.get('erholt', 0),
        data.get('aufstehen', 0),
        data.get('traume', 0),
        data.get('body', 0),
        data.get('klarheit', 0)
    ]) / 5, 1)
    
    values = [
        data.get('erholt', ''),
        data.get('aufstehen', ''),
        data.get('traume', ''),
        data.get('body', ''),
        data.get('klarheit', ''),
        avg,
        data.get('durchgeschlafen', ''),
        data.get('aufwachen_count', ''),
        data.get('einschlafen_speed', '')
    ]
    
    if row_num:
        return update_row_in_sheet(SHEETS['health'], row_num, 'AM', 'AU', values)
    else:
        row = [today] + [''] * 37 + values
        return log_to_sheet(SHEETS['health'], row)

def log_cutoffs(data):
    """Log cutoffs to HEALTH sheet columns AV-BE"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row_num = find_row_by_date(SHEETS['health'], today)
    
    values = [
        data.get('thc_ok', ''),
        data.get('thc_time', ''),
        data.get('nikotin_ok', ''),
        data.get('nikotin_time', ''),
        data.get('koffein_ok', ''),
        data.get('koffein_time', ''),
        data.get('essen_ok', ''),
        data.get('essen_time', ''),
        data.get('screens_ok', ''),
        data.get('screens_time', '')
    ]
    
    if row_num:
        return update_row_in_sheet(SHEETS['health'], row_num, 'AV', 'BE', values)
    else:
        row = [today] + [''] * 46 + values
        return log_to_sheet(SHEETS['health'], row)

def log_sleep_environment(data):
    """Log sleep environment to HEALTH sheet columns BF-BJ"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row_num = find_row_by_date(SHEETS['health'], today)
    
    values = [
        data.get('darkness', ''),
        data.get('noise', ''),
        data.get('partner', ''),
        data.get('device_in_room', ''),
        data.get('room_temp', '')
    ]
    
    if row_num:
        return update_row_in_sheet(SHEETS['health'], row_num, 'BF', 'BJ', values)
    else:
        row = [today] + [''] * 56 + values
        return log_to_sheet(SHEETS['health'], row)

def log_activity(steps, calories):
    """Log activity to HEALTH sheet columns BK-BL"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row_num = find_row_by_date(SHEETS['health'], today)
    
    values = [steps, calories]
    
    if row_num:
        return update_row_in_sheet(SHEETS['health'], row_num, 'BK', 'BL', values)
    else:
        row = [today] + [''] * 61 + values
        return log_to_sheet(SHEETS['health'], row)

def log_fluid_cutoff(fluid_ok):
    """Log fluid cutoff to HEALTH sheet column BN"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row_num = find_row_by_date(SHEETS['health'], today)
    
    if row_num:
        return update_row_in_sheet(SHEETS['health'], row_num, 'BN', 'BN', [fluid_ok])
    else:
        # BN is column 66 (A=1, so 65 empty cols before BN)
        row = [today] + [''] * 64 + [fluid_ok]
        return log_to_sheet(SHEETS['health'], row)

def log_exercise(data):
    """Log exercise to EXERCISE sheet"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    now = datetime.now(TIMEZONE).strftime('%H:%M')
    
    row = [
        today,
        data.get('time', now),
        data.get('type', ''),
        data.get('duration', ''),
        data.get('location', ''),
        data.get('workout_type', ''),
        data.get('intensity', ''),
        data.get('rpe', ''),
        data.get('stretching', ''),
        data.get('sauna_temp', ''),
        data.get('sauna_rounds', ''),
        data.get('sauna_time_per_round', ''),
        data.get('vo2max', ''),
        data.get('notes', '')
    ]
    
    return log_to_sheet(SHEETS['exercise'], row)

def log_meal(data):
    """Log meal to MEALS sheet"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    
    row = [
        today,
        data.get('time', ''),
        data.get('meal_num', ''),
        data.get('ingredients', ''),
        data.get('calories', ''),
        data.get('protein', ''),
        data.get('carbs', ''),
        data.get('fat', ''),
        data.get('fiber', ''),
        data.get('category', ''),
        data.get('before_cutoff', ''),
        data.get('notes', '')
    ]
    
    return log_to_sheet(SHEETS['meals'], row)

def log_mood(time_of_day, data):
    """Log mood to MOOD sheet"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    
    row = [
        today,
        time_of_day,
        data.get('mood', ''),
        data.get('energy', ''),
        data.get('focus', ''),
        data.get('anxiety', ''),
        data.get('stress', ''),
        data.get('motivation', ''),
        data.get('social_battery', ''),
        data.get('trigger', ''),
        data.get('notes', '')
    ]
    
    return log_to_sheet(SHEETS['mood'], row)

def log_supplements(data):
    """Log supplements to SUPPLEMENTS sheet
    Columns: Date, Blueprint_Stack, Omega3, ProButyrate, Collagen, NAC, Schlaf (Mag/Glyc), Notes
    """
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    
    row = [
        today,
        data.get('blueprint_stack', ''),
        data.get('omega3', ''),
        data.get('probutyrate', ''),
        data.get('collagen', ''),
        data.get('nac', ''),
        data.get('schlaf', ''),  # G: Schlaf (Magnesium, Glycin)
        data.get('notes', '')
    ]
    
    return log_to_sheet(SHEETS['supplements'], row)

def log_habits(data, for_yesterday=False):
    """Log habits to HABITS sheet"""
    if for_yesterday:
        date = (datetime.now(TIMEZONE) - timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        date = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    
    row = [
        date,
        data.get('sunlight_morning', ''),
        data.get('blue_light_glasses', ''),
        data.get('meditation', ''),
        data.get('breathwork', ''),
        data.get('reading', ''),
        data.get('social_interaction', ''),
        data.get('grateful_for', ''),
        data.get('hydration', ''),
        data.get('notes', '')
    ]
    
    return log_to_sheet(SHEETS['habits'], row)

def log_learning(data):
    """Log learning to LEARNING sheet"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    
    row = [
        today,
        data.get('start_time', ''),
        data.get('end_time', ''),
        data.get('duration', ''),
        data.get('task', ''),
        data.get('category', ''),
        data.get('focus_quality', ''),
        data.get('notes', '')
    ]
    
    return log_to_sheet(SHEETS['learning'], row)

def log_craving(data):
    """Log craving to CRAVINGS sheet"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    now = datetime.now(TIMEZONE).strftime('%H:%M')
    
    row = [
        today,
        data.get('time', now),
        data.get('type', ''),
        data.get('intensity', ''),
        data.get('before_cutoff', ''),
        data.get('action_taken', ''),
        data.get('notes', '')
    ]
    
    return log_to_sheet(SHEETS['cravings'], row)

def log_finance(data):
    """Log expense to FINANCE sheet"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    
    row = [
        today,
        data.get('amount', ''),
        data.get('category', ''),
        data.get('description', ''),
        data.get('necessary', ''),
        data.get('impulse', ''),
        data.get('notes', '')
    ]
    
    return log_to_sheet(SHEETS['finance'], row)

# === HELPER FUNCTIONS ===

def get_weather_las_palmas():
    try:
        response = requests.get("https://wttr.in/Las+Palmas?format=%t+%C+%h+%w", timeout=10)
        if response.status_code == 200:
            return f"🌴 Las Palmas: {response.text.strip()}"
    except:
        pass
    return "Wetter Las Palmas nicht verfügbar"

def get_weather_germany():
    try:
        response = requests.get("https://wttr.in/Giessen?format=%t+%C+%h+%w", timeout=10)
        if response.status_code == 200:
            return f"🇩🇪 Gießen: {response.text.strip()}"
    except:
        pass
    return "Wetter Deutschland nicht verfügbar"

def get_todays_events():
    try:
        service = get_calendar_service()
        if not service:
            return []
        
        now = datetime.now(TIMEZONE)
        start = now.replace(hour=0, minute=0, second=0).isoformat()
        end = now.replace(hour=23, minute=59, second=59).isoformat()
        
        events = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        return events.get('items', [])
    except:
        return []

def format_events(events):
    if not events:
        return "📅 Keine Termine heute"
    
    lines = ["📅 Heute:"]
    for event in events:
        start = event.get('start', {})
        time_str = start.get('dateTime', start.get('date', ''))
        if 'T' in time_str:
            time_str = time_str.split('T')[1][:5]
        else:
            time_str = "ganztägig"
        lines.append(f"  • {time_str}: {event.get('summary', 'Ohne Titel')}")
    
    return "\n".join(lines)

def get_sauna_count_this_week():
    try:
        service = get_sheets_service()
        if not service:
            return 0
        
        now = datetime.now(TIMEZONE)
        week_start = now - timedelta(days=now.weekday())
        week_start_str = week_start.strftime('%Y-%m-%d')
        
        result = service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f'{SHEETS["exercise"]}!A:C'
        ).execute()
        
        values = result.get('values', [])
        count = 0
        for row in values[1:]:
            if len(row) >= 3:
                if row[0] >= week_start_str and 'sauna' in row[2].lower():
                    count += 1
        return count
    except:
        return 0

def get_weekly_stats():
    try:
        service = get_sheets_service()
        if not service:
            return {}
        
        now = datetime.now(TIMEZONE)
        week_start = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d')
        
        stats = {
            'sleep_scores': [],
            'hrv_values': [],
            'training_days': 0,
            'sauna_count': 0,
            'calories': [],
            'protein': [],
            'expenses_total': 0,
            'learning_hours': 0
        }
        
        health_data = get_sheet_data(SHEETS['health'], 'A:J')
        if health_data:
            for row in health_data[1:]:
                if len(row) > 0 and row[0] >= week_start:
                    if len(row) > 1 and row[1]:
                        try:
                            stats['sleep_scores'].append(float(row[1]))
                        except:
                            pass
                    if len(row) > 9 and row[9]:
                        try:
                            stats['hrv_values'].append(float(row[9]))
                        except:
                            pass
        
        exercise_data = get_sheet_data(SHEETS['exercise'], 'A:D')
        if exercise_data:
            training_dates = set()
            for row in exercise_data[1:]:
                if len(row) > 0 and row[0] >= week_start:
                    training_dates.add(row[0])
                    if len(row) > 2 and 'sauna' in row[2].lower():
                        stats['sauna_count'] += 1
            stats['training_days'] = len(training_dates)
        
        meals_data = get_sheet_data(SHEETS['meals'], 'A:F')
        if meals_data:
            for row in meals_data[1:]:
                if len(row) > 0 and row[0] >= week_start:
                    if len(row) > 4 and row[4]:
                        try:
                            stats['calories'].append(float(row[4]))
                        except:
                            pass
                    if len(row) > 5 and row[5]:
                        try:
                            stats['protein'].append(float(row[5]))
                        except:
                            pass
        
        finance_data = get_sheet_data(SHEETS['finance'], 'A:B')
        if finance_data:
            for row in finance_data[1:]:
                if len(row) > 1 and row[0] >= week_start:
                    try:
                        stats['expenses_total'] += float(row[1])
                    except:
                        pass
        
        learning_data = get_sheet_data(SHEETS['learning'], 'A:D')
        if learning_data:
            for row in learning_data[1:]:
                if len(row) > 3 and row[0] >= week_start:
                    try:
                        stats['learning_hours'] += float(row[3]) / 60
                    except:
                        pass
        
        return stats
    except:
        return {}

# === CLAUDE VISION ===

def process_image_with_claude(image_data, prompt):
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                    {"type": "text", "text": prompt}
                ]
            }]
        )
        return response.content[0].text
    except Exception as e:
        return f"Fehler: {str(e)}"

def process_multiple_images_with_claude(images_data, prompt):
    try:
        content = []
        for img_data in images_data:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_data}})
        content.append({"type": "text", "text": prompt})
        
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": content}]
        )
        return response.content[0].text
    except Exception as e:
        return f"Fehler: {str(e)}"

def parse_ringconn_sleep_images(images):
    """Extract sleep data from 9 Ringconn screenshots"""
    prompt = """Analysiere diese Ringconn Sleep Screenshots und extrahiere ALLE Daten.

Die Screenshots zeigen typischerweise:
1. Sleep Score Übersicht (Score, Time Asleep, Efficiency)
2. Sleep Score Factors (HR, Skin Temp, HRV, Goal Gap, Awake Ratio, Stability)
3. Time Details (Time in Bed, Bedtime, Wake Time)
4. Sleep Stages mit % und Minuten (Awake, REM, Light, Deep)
5. Sleep Stages mit HR pro Stage
6. Heart Rate Details
7. HRV Details
8. SpO2 Details
9. Respiratory Rate + Skin Temperature

WICHTIG - Analysiere die Sleep Stages Grafik genau:
- REM_Latency: Zeit vom Einschlafen bis zum ERSTEN lila REM-Balken (schau auf die Zeitachse unten)
- Time_Falling_Asleep: Zeit vom Schlafbeginn (linker Rand) bis zum ersten farbigen Schlaf-Balken (nicht grau/Awake)
- Time_Final_Wake: Schau auf den letzten grauen Balken am Ende - wie lange war das?

Die grauen Balken = Awake Zeit. Die farbigen Balken:
- Pink/Rosa = Awake
- Lila = REM
- Hellblau = Light Sleep
- Dunkelblau = Deep Sleep

Extrahiere und antworte NUR im JSON Format:
{
    "sleep_score": "Zahl 0-100",
    "sleep_quality": "Excellent/Good/Fair/Poor",
    "time_asleep_min": "Gesamtminuten (8hr3min = 483)",
    "time_in_bed_min": "Gesamtminuten",
    "sleep_efficiency": "Zahl ohne %",
    "sleep_goal_gap": "Minuten (+3 oder -10)",
    "time_awake_ratio": "Zahl ohne %",
    "sleeping_hr": "BPM",
    "sleeping_hrv": "ms",
    "skin_temp": "°C",
    "skin_temp_offset": "°C",
    "spo2": "Zahl ohne %",
    "respiratory_rate": "bpm",
    "awake_min": "Minuten",
    "awake_pct": "Zahl ohne %",
    "rem_min": "Minuten",
    "rem_pct": "Zahl ohne %",
    "light_min": "Minuten",
    "light_pct": "Zahl ohne %",
    "deep_min": "Minuten",
    "deep_pct": "Zahl ohne %",
    "hr_awake": "BPM",
    "hr_rem": "BPM",
    "hr_light": "BPM",
    "hr_deep": "BPM",
    "rem_latency": "Minuten bis erster REM (schätze aus Grafik)",
    "time_falling_asleep": "Minuten (vom Start bis erster Schlaf-Balken)",
    "time_final_wake": "Minuten (letzter Awake-Abschnitt)",
    "sleep_stability": "Text",
    "bedtime": "HH:MM",
    "wake_time": "HH:MM"
}

Konvertiere Stunden:Minuten zu Minuten. Leere Werte = "". Nur JSON!"""
    
    result = process_multiple_images_with_claude(images, prompt)
    
    try:
        json_match = re.search(r'\{[^{}]+\}', result, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except:
        pass
    return {}

def parse_meal_image(image_data):
    """Analyze meal photo"""
    prompt = """Analysiere dieses Foto einer Mahlzeit.

Antworte NUR im JSON Format:
{
    "ingredients": "Komma-getrennte Liste",
    "calories": "geschätzte Kalorien",
    "protein": "Gramm",
    "carbs": "Gramm",
    "fat": "Gramm",
    "fiber": "Gramm",
    "category": "breakfast/lunch/dinner/snack"
}"""
    
    result = process_image_with_claude(image_data, prompt)
    try:
        json_match = re.search(r'\{[^{}]+\}', result, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except:
        pass
    return {}

def calculate_meal_macros(description):
    """Calculate macros from text"""
    prompt = f"""Berechne Nährwerte für: {description}

Antworte NUR im JSON Format:
{{"ingredients": "{description}", "calories": "X", "protein": "X", "carbs": "X", "fat": "X", "fiber": "X", "category": "meal"}}"""
    
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        result = response.content[0].text
        json_match = re.search(r'\{[^{}]+\}', result, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except:
        pass
    return {"ingredients": description}

# === FLOW STATE MANAGEMENT ===

def set_state(chat_id, step, data=None):
    user_state[chat_id] = {"step": step}
    if data:
        temp_data[chat_id].update(data)

def get_state(chat_id):
    return user_state.get(chat_id, {}).get("step")

def clear_state(chat_id):
    user_state[chat_id] = {"step": None}
    temp_data[chat_id] = {}
    collected_images[chat_id] = []

def skip_to_next_morning_step(chat_id, current_step):
    bot.send_message(chat_id, "⏭️ Übersprungen!")
    
    steps = ["morning_sleep_screenshots", "morning_subjective", "morning_environment", 
             "morning_cutoffs", "morning_reading", "morning_supplements", "morning_vitals", "morning_mood"]
    
    try:
        idx = steps.index(current_step)
        if idx < len(steps) - 1:
            next_step = steps[idx + 1]
            step_functions = {
                "morning_subjective": ask_subjective_sleep,
                "morning_environment": ask_sleep_environment,
                "morning_cutoffs": ask_cutoffs,
                "morning_reading": ask_reading,
                "morning_supplements": ask_supplements,
                "morning_vitals": ask_morning_vitals,
                "morning_mood": ask_morning_mood
            }
            if next_step in step_functions:
                step_functions[next_step](chat_id)
        else:
            finish_morning_check(chat_id)
    except:
        finish_morning_check(chat_id)

def skip_to_next_evening_step(chat_id, current_step):
    bot.send_message(chat_id, "⏭️ Übersprungen!")
    
    steps = ["evening_steps", "evening_exercise", "evening_meals", "evening_learning",
             "evening_habits", "evening_gratitude", "evening_cravings", "evening_finance", "evening_mood"]
    
    try:
        idx = steps.index(current_step)
        if idx < len(steps) - 1:
            next_step = steps[idx + 1]
            step_functions = {
                "evening_exercise": ask_evening_exercise,
                "evening_meals": ask_evening_meals,
                "evening_learning": ask_evening_learning,
                "evening_habits": ask_evening_habits,
                "evening_gratitude": ask_gratitude,
                "evening_cravings": ask_evening_cravings,
                "evening_finance": ask_evening_finance,
                "evening_mood": ask_evening_mood
            }
            if next_step in step_functions:
                step_functions[next_step](chat_id)
        else:
            finish_evening_review(chat_id)
    except:
        finish_evening_review(chat_id)

# === MORNING FLOW ===

def send_morning_check(chat_id=CHAT_ID):
    clear_state(chat_id)
    
    weather_lp = get_weather_las_palmas()
    weather_de = get_weather_germany()
    events = get_todays_events()
    events_text = format_events(events)
    today = datetime.now(TIMEZONE).strftime('%A, %d.%m.%Y')
    
    msg = f"""☀️ **MORNING CHECK**
{today}

{weather_lp}
{weather_de}

{events_text}

---

📱 **Ringconn Sleep Screenshots**
Schick mir deine 9 Screenshots:
1. Sleep Score Übersicht
2. Sleep Score Factors
3. Time Asleep Details
4. Sleep Stages (% + Min)
5. Sleep Stages (mit HR)
6. Heart Rate
7. HRV
8. SpO2 + Skin Temp
9. Respiratory Rate

Schick Bilder, `done` wenn fertig, oder `skip`.
`/abort` bricht ab."""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_sleep_screenshots")
    collected_images[chat_id] = []

def process_morning_step(chat_id, step, message=None, image_data=None):
    if message and message.text.lower().strip() == 'skip':
        skip_to_next_morning_step(chat_id, step)
        return
    
    if step == "morning_sleep_screenshots":
        if image_data:
            collected_images[chat_id].append(image_data)
            count = len(collected_images[chat_id])
            if count < 9:
                bot.send_message(chat_id, f"📸 {count}/9 - weiter oder `done`/`skip`")
            else:
                process_sleep_screenshots(chat_id)
        elif message and message.text.lower().strip() == 'done':
            if collected_images[chat_id]:
                process_sleep_screenshots(chat_id)
            else:
                ask_subjective_sleep(chat_id)
        else:
            bot.send_message(chat_id, "📸 Screenshots, `done` oder `skip`")
    
    elif step == "morning_subjective":
        parse_subjective_sleep(chat_id, message.text if message else "")
    elif step == "morning_environment":
        parse_sleep_environment(chat_id, message.text if message else "")
    elif step == "morning_cutoffs":
        parse_cutoffs(chat_id, message.text if message else "")
    elif step == "morning_reading":
        parse_reading(chat_id, message.text if message else "")
    elif step == "morning_supplements":
        parse_supplements(chat_id, message.text if message else "")
    elif step == "morning_vitals":
        parse_morning_vitals(chat_id, message.text if message else "")
    elif step == "morning_mood":
        parse_morning_mood(chat_id, message.text if message else "")

def process_sleep_screenshots(chat_id):
    bot.send_message(chat_id, f"🔄 Analysiere {len(collected_images[chat_id])} Screenshots...")
    sleep_data = parse_ringconn_sleep_images(collected_images[chat_id])
    temp_data[chat_id]['sleep_data'] = sleep_data
    if sleep_data:
        log_health_ringconn(sleep_data)
        score = sleep_data.get('sleep_score', '?')
        bot.send_message(chat_id, f"✅ Sleep Data geloggt! Score: {score}")
    else:
        bot.send_message(chat_id, "⚠️ Konnte nicht extrahieren, weiter...")
    ask_subjective_sleep(chat_id)

def ask_subjective_sleep(chat_id):
    msg = """😴 **Subjektive Schlafqualität** (je 1-10)

Format: `erholt, aufstehen, träume, körper, klarheit, durchgeschlafen, aufwachen, einschlafen`

Beispiel: `8, 7, 6, 8, 7, ja, 1, schnell`

Oder `skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_subjective")

def parse_subjective_sleep(chat_id, text):
    parts = [p.strip() for p in text.lower().replace(',', ' ').split()]
    
    if len(parts) >= 8:
        data = {
            'erholt': int(parts[0]) if parts[0].isdigit() else 5,
            'aufstehen': int(parts[1]) if parts[1].isdigit() else 5,
            'traume': int(parts[2]) if parts[2].isdigit() else 5,
            'body': int(parts[3]) if parts[3].isdigit() else 5,
            'klarheit': int(parts[4]) if parts[4].isdigit() else 5,
            'durchgeschlafen': 'YES' if parts[5] in ['ja', 'yes', 'j', 'y'] else 'NO',
            'aufwachen_count': int(parts[6]) if parts[6].isdigit() else 0,
            'einschlafen_speed': parts[7]
        }
        log_subjective_sleep(data)
        bot.send_message(chat_id, "✅ Subjektive Daten geloggt!")
    else:
        bot.send_message(chat_id, "⚠️ Format nicht erkannt, weiter...")
    ask_sleep_environment(chat_id)

def ask_sleep_environment(chat_id):
    msg = """🛏️ **Schlafumgebung gestern**

Format: `dunkelheit, lärm, partner, handy, raumtemp`

Beispiel: `9, 2, nein, nein, 19`

Oder `skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_environment")

def parse_sleep_environment(chat_id, text):
    parts = [p.strip() for p in text.lower().replace(',', ' ').split()]
    
    if len(parts) >= 4:
        data = {
            'darkness': int(parts[0]) if parts[0].isdigit() else 5,
            'noise': int(parts[1]) if parts[1].isdigit() else 5,
            'partner': 'YES' if parts[2] in ['ja', 'yes', 'j', 'y'] else 'NO',
            'device_in_room': 'YES' if parts[3] in ['ja', 'yes', 'j', 'y'] else 'NO',
            'room_temp': parts[4] if len(parts) > 4 else ''
        }
        log_sleep_environment(data)
        bot.send_message(chat_id, "✅ Umgebung geloggt!")
    ask_cutoffs(chat_id)

def ask_cutoffs(chat_id):
    msg = """⏰ **Cutoffs gestern**

Format: `thc nikotin koffein essen screens fluid`
(ja oder Uhrzeit wenn überschritten)
Fluid Cutoff = 20:30

Beispiel: `ja ja ja ja ja ja` oder `23:00 ja 15:00 21:30 ja nein`

Oder `skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_cutoffs")

def parse_cutoffs(chat_id, text):
    parts = [p.strip() for p in text.lower().replace(',', ' ').split()]
    
    def parse_cutoff(val):
        if val in ['ja', 'yes', 'j', 'y']:
            return 'YES', ''
        elif ':' in val:
            return 'NO', val
        else:
            return 'NO', val
    
    if len(parts) >= 5:
        thc_ok, thc_time = parse_cutoff(parts[0])
        nik_ok, nik_time = parse_cutoff(parts[1])
        koff_ok, koff_time = parse_cutoff(parts[2])
        ess_ok, ess_time = parse_cutoff(parts[3])
        scr_ok, scr_time = parse_cutoff(parts[4])
        
        data = {
            'thc_ok': thc_ok, 'thc_time': thc_time,
            'nikotin_ok': nik_ok, 'nikotin_time': nik_time,
            'koffein_ok': koff_ok, 'koffein_time': koff_time,
            'essen_ok': ess_ok, 'essen_time': ess_time,
            'screens_ok': scr_ok, 'screens_time': scr_time
        }
        log_cutoffs(data)
        
        # Fluid cutoff (6th value) - logged separately to column BN
        if len(parts) >= 6:
            fluid_ok, _ = parse_cutoff(parts[5])
            log_fluid_cutoff(fluid_ok)
        
        violations = sum([1 for x in [thc_ok, nik_ok, koff_ok, ess_ok, scr_ok] if x == 'NO'])
        if len(parts) >= 6:
            fluid_ok, _ = parse_cutoff(parts[5])
            if fluid_ok == 'NO':
                violations += 1
        
        if violations == 0:
            bot.send_message(chat_id, "✅ Alle Cutoffs eingehalten! 💪")
        else:
            bot.send_message(chat_id, f"⚠️ {violations} Cutoff(s) überschritten")
    ask_reading(chat_id)

def ask_reading(chat_id):
    msg = """📚 **Minuten gelesen gestern Abend?**

Zahl eingeben oder `0`/`skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_reading")

def parse_reading(chat_id, text):
    text = text.lower().strip()
    if text in ['nein', 'no', 'n', '0']:
        minutes = 0
    else:
        try:
            minutes = int(re.search(r'\d+', text).group())
        except:
            minutes = 0
    
    log_habits({'reading': minutes}, for_yesterday=True)
    if minutes > 0:
        bot.send_message(chat_id, f"✅ {minutes}min gelesen!")
    ask_supplements(chat_id)

def ask_supplements(chat_id):
    msg = """💊 **Supplements**

Format: `blueprint omega3 probutyrate collagen nac schlaf`
(jeweils ja/nein, mit Space getrennt)

Schlaf = Magnesium + Glycin (gestern Abend)

Beispiel: `ja ja ja ja ja ja` oder `nein ja nein ja ja nein`

Oder `skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_supplements")

def parse_supplements(chat_id, text):
    parts = [p.strip().lower() for p in text.replace(',', ' ').split()]
    
    def yn(val):
        return 'YES' if val in ['ja', 'yes', 'j', 'y', '1'] else 'NO'
    
    # Order: blueprint, omega3, probutyrate, collagen, nac, schlaf
    if len(parts) >= 6:
        data = {
            'blueprint_stack': yn(parts[0]),
            'omega3': yn(parts[1]),
            'probutyrate': yn(parts[2]),
            'collagen': yn(parts[3]),
            'nac': yn(parts[4]),
            'schlaf': yn(parts[5])
        }
    elif len(parts) >= 5:
        data = {
            'blueprint_stack': yn(parts[0]),
            'omega3': yn(parts[1]),
            'probutyrate': yn(parts[2]),
            'collagen': yn(parts[3]),
            'nac': yn(parts[4]),
            'schlaf': ''
        }
    elif len(parts) == 1 and parts[0] in ['ja', 'yes', 'j', 'y', 'all']:
        data = {'blueprint_stack': 'YES', 'omega3': 'YES', 'probutyrate': 'YES', 'collagen': 'YES', 'nac': 'YES', 'schlaf': 'YES'}
    else:
        bot.send_message(chat_id, "⚠️ Format: `ja ja ja ja ja ja` (6 Werte). Nochmal?")
        return
    
    log_supplements(data)
    bot.send_message(chat_id, "✅ Supplements geloggt!")
    ask_morning_vitals(chat_id)

def ask_morning_vitals(chat_id):
    is_sunday = datetime.now(TIMEZONE).weekday() == 6
    if is_sunday:
        msg = """⚖️ **Morning Vitals** (Sonntag = auch BP)

Format: `gewicht, ohrtemp, sys, dia`
Beispiel: `73.5, 36.8, 118, 75`"""
    else:
        msg = """⚖️ **Morning Vitals**

Format: `gewicht, ohrtemp`
Beispiel: `73.5, 36.8`"""
    
    msg += "\n\nOder `skip`"
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_vitals")

def parse_morning_vitals(chat_id, text):
    parts = [p.strip().replace(',', '.') for p in text.replace(',', ' ').split()]
    
    weight = ear_temp = bp_sys = bp_dia = None
    try:
        if len(parts) >= 1 and parts[0]:
            weight = float(parts[0])
        if len(parts) >= 2 and parts[1]:
            ear_temp = float(parts[1])
        if len(parts) >= 4:
            bp_sys = int(float(parts[2]))
            bp_dia = int(float(parts[3]))
    except:
        pass
    
    log_health_vitals(weight=weight, ear_temp=ear_temp, bp_sys=bp_sys, bp_dia=bp_dia)
    msg = f"✅ Vitals: {weight}kg"
    if bp_sys:
        msg += f", BP {bp_sys}/{bp_dia}"
    bot.send_message(chat_id, msg)
    ask_morning_mood(chat_id)

def ask_morning_mood(chat_id):
    msg = """🌅 **Morning Mood** (je 1-10)

Format: `stimmung, energie, motivation`
Beispiel: `7, 6, 8`

Oder `skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_mood")

def parse_morning_mood(chat_id, text):
    parts = [p.strip() for p in text.replace(',', ' ').split()]
    
    if len(parts) >= 3:
        data = {
            'mood': int(parts[0]) if parts[0].isdigit() else 5,
            'energy': int(parts[1]) if parts[1].isdigit() else 5,
            'motivation': int(parts[2]) if parts[2].isdigit() else 5
        }
        log_mood("morning", data)
        bot.send_message(chat_id, "✅ Mood geloggt!")
    finish_morning_check(chat_id)

def finish_morning_check(chat_id):
    sleep_data = temp_data[chat_id].get('sleep_data', {})
    score = sleep_data.get('sleep_score', '?')
    
    if score != '?' and int(score) >= 85:
        reco = "🎯 Super Schlaf! Nutze die Energie!"
    elif score != '?' and int(score) >= 70:
        reco = "👍 Solider Schlaf. Hydration + Movement!"
    else:
        reco = "⚡ Fokus auf Erholung. Sauna? Früh ins Bett."
    
    msg = f"""✅ **MORNING CHECK KOMPLETT**

Sleep Score: {score}
{reco}

📸 Mach heute Fotos von deinen Mahlzeiten!

Guten Tag! ☀️"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    clear_state(chat_id)

# === EVENING FLOW ===

def send_evening_check(chat_id=CHAT_ID):
    clear_state(chat_id)
    
    msg = """🌙 **EVENING REVIEW**

👟 **Steps heute?**

Gib die Zahl ein (z.B. `8500`)

Oder `skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_steps")

def process_evening_step(chat_id, step, message=None, image_data=None):
    if message and message.text.lower().strip() == 'skip':
        skip_to_next_evening_step(chat_id, step)
        return
    
    if step == "evening_steps":
        parse_evening_steps(chat_id, message.text if message else "")
    elif step == "evening_exercise":
        parse_evening_exercise(chat_id, message.text if message else "")
    elif step == "evening_meals":
        parse_evening_meals(chat_id, message, image_data)
    elif step == "evening_learning":
        parse_evening_learning(chat_id, message.text if message else "")
    elif step == "evening_habits":
        parse_evening_habits(chat_id, message.text if message else "")
    elif step == "evening_gratitude":
        parse_gratitude(chat_id, message.text if message else "")
    elif step == "evening_cravings":
        parse_evening_cravings(chat_id, message.text if message else "")
    elif step == "evening_finance":
        parse_evening_finance(chat_id, message.text if message else "")
    elif step == "evening_mood":
        parse_evening_mood(chat_id, message.text if message else "")

def parse_evening_steps(chat_id, text):
    try:
        steps = int(re.search(r'\d+', text.replace(',', '')).group())
        log_activity(steps, 0)
        temp_data[chat_id]['steps'] = steps
        bot.send_message(chat_id, f"✅ {steps:,} Steps geloggt!")
    except:
        bot.send_message(chat_id, "⚠️ Keine Zahl erkannt, weiter...")
    ask_evening_exercise(chat_id)

def ask_evening_exercise(chat_id):
    msg = """🏋️ **Training heute?**

Formate:
- `gym 45 push 8` (min, type, rpe)
- `cardio 30 run`
- `sauna 80 3 7` (temp, runden, min/runde)
- `walk 45`
- `fussball 90`

Nach jeder Eingabe: Nächstes oder `done`

Oder `nein`/`skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_exercise")
    temp_data[chat_id]['exercises_logged'] = 0

def parse_evening_exercise(chat_id, text):
    text = text.lower().strip()
    
    if text in ['nein', 'no', 'n', 'done', 'fertig']:
        count = temp_data[chat_id].get('exercises_logged', 0)
        if count > 0:
            if 'sauna' in str(temp_data[chat_id].get('last_exercise', '')):
                sauna_count = get_sauna_count_this_week()
                bot.send_message(chat_id, f"✅ {count} Training(s) geloggt! 🧖 Sauna: {sauna_count}/4")
            else:
                bot.send_message(chat_id, f"✅ {count} Training(s) geloggt!")
        ask_evening_meals(chat_id)
        return
    
    parts = text.split()
    if not parts:
        bot.send_message(chat_id, "⚠️ Format nicht erkannt. Nochmal oder `done`?")
        return
    
    exercise_type = parts[0]
    data = {'type': exercise_type.capitalize()}
    
    if exercise_type == 'gym' and len(parts) >= 4:
        data['duration'] = parts[1]
        data['workout_type'] = parts[2]
        data['rpe'] = parts[3]
    elif exercise_type == 'cardio' and len(parts) >= 3:
        data['duration'] = parts[1]
        data['workout_type'] = parts[2]
    elif exercise_type == 'sauna' and len(parts) >= 4:
        data['sauna_temp'] = parts[1]
        data['sauna_rounds'] = parts[2]
        data['sauna_time_per_round'] = parts[3]
        data['duration'] = int(parts[2]) * int(parts[3])
    elif exercise_type in ['walk', 'fussball', 'yoga', 'sport', 'schwimmen'] and len(parts) >= 2:
        data['duration'] = parts[1]
    else:
        bot.send_message(chat_id, "⚠️ Format nicht erkannt. Nochmal oder `done`?")
        return
    
    log_exercise(data)
    temp_data[chat_id]['exercises_logged'] = temp_data[chat_id].get('exercises_logged', 0) + 1
    temp_data[chat_id]['last_exercise'] = exercise_type
    bot.send_message(chat_id, f"✅ {exercise_type.capitalize()} geloggt! Noch eins oder `done`?")

def ask_evening_meals(chat_id):
    msg = """🍽️ **Mahlzeiten heute?**

Foto schicken ODER Text (Komma = mehrere Mahlzeiten)

Beispiel: `oatmeal blueberries, chicken rice vegetables, yogurt nuts`

`done` wenn fertig, `skip` zum Überspringen"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_meals")
    temp_data[chat_id]['meal_count'] = 0
    temp_data[chat_id]['total_calories'] = 0
    temp_data[chat_id]['total_protein'] = 0

def parse_evening_meals(chat_id, message, image_data):
    if message and message.text.lower().strip() == 'done':
        total_cal = temp_data[chat_id].get('total_calories', 0)
        total_prot = temp_data[chat_id].get('total_protein', 0)
        count = temp_data[chat_id].get('meal_count', 0)
        if count > 0:
            bot.send_message(chat_id, f"✅ {count} Mahlzeit(en)! ~{total_cal}kcal, ~{total_prot}g Protein")
        ask_evening_learning(chat_id)
        return
    
    now = datetime.now(TIMEZONE).strftime('%H:%M')
    
    if image_data:
        bot.send_message(chat_id, "🔄 Analysiere...")
        macros = parse_meal_image(image_data)
        if macros:
            macros['time'] = now
            macros['meal_num'] = temp_data[chat_id].get('meal_count', 0) + 1
            log_meal(macros)
            temp_data[chat_id]['meal_count'] += 1
            try:
                temp_data[chat_id]['total_calories'] += int(macros.get('calories', 0))
                temp_data[chat_id]['total_protein'] += int(macros.get('protein', 0))
            except:
                pass
            bot.send_message(chat_id, f"✅ Geloggt: {macros.get('ingredients', '')} (~{macros.get('calories', '?')}kcal)")
        else:
            bot.send_message(chat_id, "⚠️ Nicht erkannt. Text eingeben?")
    elif message:
        meals = [m.strip() for m in message.text.split(',')]
        for meal_desc in meals:
            if not meal_desc:
                continue
            macros = calculate_meal_macros(meal_desc)
            macros['time'] = now
            macros['meal_num'] = temp_data[chat_id].get('meal_count', 0) + 1
            log_meal(macros)
            temp_data[chat_id]['meal_count'] += 1
            try:
                temp_data[chat_id]['total_calories'] += int(macros.get('calories', 0))
                temp_data[chat_id]['total_protein'] += int(macros.get('protein', 0))
            except:
                pass
        bot.send_message(chat_id, f"✅ {len(meals)} Mahlzeit(en) geloggt! Weitere oder `done`")

def ask_evening_learning(chat_id):
    msg = """📚 **Gelernt heute?**

Format: `thema dauer kategorie focus`
Kategorien: uni/work/personal/admin
Mehrere mit Komma trennen

Beispiel: `neuro 45 uni 8, spanish 30 personal 7`

Oder `nein`/`skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_learning")

def parse_evening_learning(chat_id, text):
    if text.lower().strip() in ['nein', 'no', 'n']:
        ask_evening_habits(chat_id)
        return
    
    entries = [e.strip() for e in text.split(',')]
    for entry in entries:
        parts = entry.split()
        if len(parts) >= 4:
            data = {
                'task': parts[0],
                'duration': parts[1],
                'category': parts[2],
                'focus_quality': parts[3]
            }
            log_learning(data)
    
    bot.send_message(chat_id, f"✅ {len(entries)} Learning-Einträge geloggt!")
    ask_evening_habits(chat_id)

def ask_evening_habits(chat_id):
    msg = """☀️ **Habits heute**

Format: `sonnenlicht blaulicht meditation atem sozial hydration`
(Min/ja-nein/Min/Min/1-10/1-10)

Beispiel: `15 ja 10 5 7 8`

Oder `skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_habits")

def parse_evening_habits(chat_id, text):
    parts = text.replace(',', ' ').split()
    
    if len(parts) >= 6:
        data = {
            'sunlight_morning': parts[0] if parts[0].isdigit() else '0',
            'blue_light_glasses': 'YES' if parts[1].lower() in ['ja', 'yes', 'j', 'y', '1'] else 'NO',
            'meditation': parts[2] if parts[2].isdigit() else '0',
            'breathwork': parts[3] if parts[3].isdigit() else '0',
            'social_interaction': parts[4] if parts[4].isdigit() else '5',
            'hydration': parts[5] if parts[5].isdigit() else '5',
            'grateful_for': ''
        }
        temp_data[chat_id]['habits_data'] = data
        ask_gratitude(chat_id)
    else:
        bot.send_message(chat_id, "⚠️ Format: `15 ja 10 5 7 8` (6 Werte). Nochmal?")

def ask_gratitude(chat_id):
    msg = """🙏 **Wofür bist du heute dankbar?**

Freier Text oder `skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_gratitude")

def parse_gratitude(chat_id, text):
    data = temp_data[chat_id].get('habits_data', {})
    data['grateful_for'] = text.strip()
    log_habits(data)
    bot.send_message(chat_id, "✅ Habits + Dankbarkeit geloggt!")
    ask_evening_cravings(chat_id)

def ask_evening_cravings(chat_id):
    msg = """🍬 **Cravings heute?**

Format: `typ intensität [yes wenn nachgegeben]`
Mehrere mit Komma

Beispiel: `thc 7, nic 5 yes`

Oder `nein`/`skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_cravings")

def parse_evening_cravings(chat_id, text):
    if text.lower().strip() in ['nein', 'no', 'n']:
        bot.send_message(chat_id, "✅ Clean day! 💪")
        ask_evening_finance(chat_id)
        return
    
    entries = [e.strip() for e in text.split(',')]
    for entry in entries:
        parts = entry.split()
        if len(parts) >= 2:
            data = {
                'type': parts[0],
                'intensity': parts[1],
                'action_taken': 'YES' if len(parts) > 2 and parts[2].lower() in ['yes', 'ja', 'y'] else 'NO'
            }
            log_craving(data)
    
    bot.send_message(chat_id, f"✅ {len(entries)} Craving(s) geloggt!")
    ask_evening_finance(chat_id)

def ask_evening_finance(chat_id):
    msg = """💸 **Ausgaben heute?**

Format: `betrag kategorie [i für Impuls]`
Mehrere mit Komma

Beispiel: `15 food, 50 shopping i`

Oder `nein`/`skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_finance")

def parse_evening_finance(chat_id, text):
    if text.lower().strip() in ['nein', 'no', 'n']:
        ask_evening_mood(chat_id)
        return
    
    entries = [e.strip() for e in text.split(',')]
    total = 0
    
    for entry in entries:
        parts = entry.split()
        if len(parts) >= 2:
            try:
                amount = float(parts[0])
                total += amount
            except:
                continue
            
            data = {
                'amount': parts[0],
                'category': parts[1],
                'impulse': 'YES' if 'i' in [p.lower() for p in parts[2:]] else 'NO'
            }
            log_finance(data)
    
    bot.send_message(chat_id, f"✅ {len(entries)} Ausgabe(n)! Total: €{total:.2f}")
    ask_evening_mood(chat_id)

def ask_evening_mood(chat_id):
    msg = """🌙 **Evening Mood** (je 1-10)

Format: `stimmung, focus, angst, stress, social`

Beispiel: `7, 6, 3, 4, 5`

Oder `skip`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_mood")

def parse_evening_mood(chat_id, text):
    parts = [p.strip() for p in text.replace(',', ' ').split()]
    
    if len(parts) >= 5:
        data = {
            'mood': int(parts[0]) if parts[0].isdigit() else 5,
            'focus': int(parts[1]) if parts[1].isdigit() else 5,
            'anxiety': int(parts[2]) if parts[2].isdigit() else 5,
            'stress': int(parts[3]) if parts[3].isdigit() else 5,
            'social_battery': int(parts[4]) if parts[4].isdigit() else 5
        }
        log_mood("evening", data)
        bot.send_message(chat_id, "✅ Mood geloggt!")
    finish_evening_review(chat_id)

def finish_evening_review(chat_id):
    total_cal = temp_data[chat_id].get('total_calories', 0)
    total_prot = temp_data[chat_id].get('total_protein', 0)
    steps = temp_data[chat_id].get('steps', 0)
    sauna_count = get_sauna_count_this_week()
    
    msg = f"""✅ **EVENING REVIEW KOMPLETT**

📊 Heute:
- Steps: {steps:,}
- Kalorien: ~{total_cal}kcal
- Protein: ~{total_prot}g
- Sauna: {sauna_count}/4

Gute Nacht! 🌙"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    clear_state(chat_id)

# === WEEKLY & MONTHLY ===

def send_weekly_review(chat_id=CHAT_ID):
    stats = get_weekly_stats()
    
    sleep_avg = sum(stats['sleep_scores']) / len(stats['sleep_scores']) if stats['sleep_scores'] else 0
    hrv_avg = sum(stats['hrv_values']) / len(stats['hrv_values']) if stats['hrv_values'] else 0
    cal_avg = sum(stats['calories']) / len(stats['calories']) if stats['calories'] else 0
    prot_avg = sum(stats['protein']) / len(stats['protein']) if stats['protein'] else 0
    
    msg = f"""📊 **WEEKLY REVIEW**

😴 Sleep Score Ø: {sleep_avg:.1f}
💓 HRV Ø: {hrv_avg:.0f}ms
🏋️ Training: {stats['training_days']} Tage
🧖 Sauna: {stats['sauna_count']}/4 {"✅" if stats['sauna_count'] >= 4 else "❌"}
🍽️ Kalorien Ø: {cal_avg:.0f}
🥩 Protein Ø: {prot_avg:.0f}g
💸 Ausgaben: €{stats['expenses_total']:.2f}
📚 Lernen: {stats['learning_hours']:.1f}h

Nächste Woche besser! 💪"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')

def send_monthly_check(chat_id=CHAT_ID):
    msg = """📅 **MONTHLY CHECK**

Zeit für monatliche Messungen:
1. 📏 Body Fat %
2. 📐 Taillenumfang
3. 🏃 VO2max Test?

Format: `bodyfat, waist`
Beispiel: `18.5, 82`"""
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "monthly_measurements")

# === QUICK LOGS ===

def handle_quick_log(chat_id, text):
    text = text.lower().strip()
    parts = text.split()
    if not parts:
        return False
    
    cmd = parts[0]
    
    # Weight
    if cmd == 'weight' and len(parts) >= 2:
        try:
            weight = float(parts[1].replace(',', '.'))
            log_health_vitals(weight=weight)
            bot.send_message(chat_id, f"✅ Gewicht: {weight}kg")
            return True
        except:
            pass
    
    # Temperature
    elif cmd == 'temp' and len(parts) >= 2:
        try:
            temp = float(parts[1].replace(',', '.'))
            log_health_vitals(ear_temp=temp)
            bot.send_message(chat_id, f"✅ Temp: {temp}°C")
            return True
        except:
            pass
    
    # Blood pressure
    elif cmd == 'bp' and len(parts) >= 3:
        try:
            log_health_vitals(bp_sys=int(parts[1]), bp_dia=int(parts[2]))
            bot.send_message(chat_id, f"✅ BP: {parts[1]}/{parts[2]}")
            return True
        except:
            pass
    
    # Steps
    elif cmd == 'steps' and len(parts) >= 2:
        try:
            steps = int(parts[1].replace(',', ''))
            log_activity(steps, 0)
            bot.send_message(chat_id, f"✅ Steps: {steps:,}")
            return True
        except:
            pass
    
    # Mood
    elif cmd == 'mood' and len(parts) >= 4:
        try:
            data = {'mood': int(parts[1]), 'energy': int(parts[2]), 'motivation': int(parts[3])}
            log_mood("quick", data)
            bot.send_message(chat_id, f"✅ Mood: {parts[1]}/{parts[2]}/{parts[3]}")
            return True
        except:
            pass
    
    # Gym
    elif cmd == 'gym' and len(parts) >= 4:
        data = {'type': 'Gym', 'duration': parts[1], 'workout_type': parts[2], 'rpe': parts[3]}
        log_exercise(data)
        bot.send_message(chat_id, f"✅ Gym {parts[1]}min ({parts[2]}) RPE {parts[3]}")
        return True
    
    # Cardio
    elif cmd == 'cardio' and len(parts) >= 3:
        data = {'type': 'Cardio', 'duration': parts[1], 'workout_type': parts[2]}
        log_exercise(data)
        bot.send_message(chat_id, f"✅ Cardio {parts[1]}min ({parts[2]})")
        return True
    
    # Sauna
    elif cmd == 'sauna' and len(parts) >= 4:
        data = {'type': 'Sauna', 'duration': parts[1], 'sauna_temp': parts[2]}
        if 'x' in parts[3]:
            r, t = parts[3].split('x')
            data['sauna_rounds'] = r
            data['sauna_time_per_round'] = t
        log_exercise(data)
        count = get_sauna_count_this_week()
        bot.send_message(chat_id, f"✅ Sauna! 🧖 {count}/4")
        return True
    
    # Walk
    elif cmd == 'walk' and len(parts) >= 2:
        log_exercise({'type': 'Walk', 'duration': parts[1]})
        bot.send_message(chat_id, f"✅ Walk {parts[1]}min")
        return True
    
    # Meal
    elif cmd == 'meal' and len(parts) >= 2:
        desc = ' '.join(parts[1:])
        macros = calculate_meal_macros(desc)
        macros['time'] = datetime.now(TIMEZONE).strftime('%H:%M')
        log_meal(macros)
        bot.send_message(chat_id, f"✅ Meal: {desc} (~{macros.get('calories', '?')}kcal)")
        return True
    
    # Craving
    elif cmd == 'craving' and len(parts) >= 3:
        gave_in = 'YES' if len(parts) > 3 and parts[3] in ['yes', 'ja', 'y'] else 'NO'
        log_craving({'type': parts[1], 'intensity': parts[2], 'action_taken': gave_in})
        emoji = "😔" if gave_in == 'YES' else "💪"
        bot.send_message(chat_id, f"✅ Craving: {parts[1]} ({parts[2]}/10) {emoji}")
        return True
    
    # Learn
    elif cmd == 'learn' and len(parts) >= 4:
        data = {'task': parts[1], 'duration': parts[2], 'focus_quality': parts[3]}
        log_learning(data)
        bot.send_message(chat_id, f"✅ Learn: {parts[1]} {parts[2]}min")
        return True
    
    # Spent
    elif cmd == 'spent' and len(parts) >= 3:
        impulse = 'YES' if 'i' in parts[3:] else 'NO'
        log_finance({'amount': parts[1], 'category': parts[2], 'impulse': impulse})
        bot.send_message(chat_id, f"✅ €{parts[1]} ({parts[2]})")
        return True
    
    # Supps - order: blueprint, omega3, probutyrate, collagen, nac, schlaf
    elif cmd == 'supps':
        if len(parts) >= 7:
            def yn(v): return 'YES' if v in ['ja', 'yes', 'j', 'y'] else 'NO'
            data = {'blueprint_stack': yn(parts[1]), 'omega3': yn(parts[2]), 'probutyrate': yn(parts[3]), 'collagen': yn(parts[4]), 'nac': yn(parts[5]), 'schlaf': yn(parts[6])}
        elif len(parts) >= 6:
            def yn(v): return 'YES' if v in ['ja', 'yes', 'j', 'y'] else 'NO'
            data = {'blueprint_stack': yn(parts[1]), 'omega3': yn(parts[2]), 'probutyrate': yn(parts[3]), 'collagen': yn(parts[4]), 'nac': yn(parts[5]), 'schlaf': ''}
        elif len(parts) == 2 and parts[1] in ['ja', 'yes', 'all']:
            data = {'blueprint_stack': 'YES', 'omega3': 'YES', 'probutyrate': 'YES', 'collagen': 'YES', 'nac': 'YES', 'schlaf': 'YES'}
        else:
            data = {'blueprint_stack': 'NO'}
        log_supplements(data)
        bot.send_message(chat_id, "✅ Supps geloggt!")
        return True
    
    # Grateful
    elif cmd == 'grateful':
        text = ' '.join(parts[1:])
        log_habits({'grateful_for': text})
        bot.send_message(chat_id, f"✅ Dankbarkeit: {text}")
        return True
    
    # Habits quick
    elif cmd == 'habits' and len(parts) >= 7:
        def yn(v): return 'YES' if v in ['ja', 'yes', 'j', 'y'] else 'NO'
        data = {
            'sunlight_morning': parts[1],
            'blue_light_glasses': yn(parts[2]),
            'meditation': parts[3],
            'breathwork': parts[4],
            'social_interaction': parts[5],
            'hydration': parts[6]
        }
        log_habits(data)
        bot.send_message(chat_id, "✅ Habits geloggt!")
        return True
    
    return False

# === TELEGRAM HANDLERS ===

@bot.message_handler(commands=['start'])
def cmd_start(message):
    msg = """👋 **Zeroism Bot v3.1**

**Automatische Checks:**
- ☀️ 07:00 Morning Check
- 🌙 22:30 Evening Review
- 📊 Sonntag 18:00 Weekly
- 📅 1. des Monats Monthly

**Commands:**
/morning - Morning Check
/evening - Evening Review
/status - Heutiger Status
/weekly - Weekly Review
/quick - Quick-Log Hilfe

**Während Flows:**
- `skip` - Schritt überspringen
- `done` - Abschnitt beenden
- `/abort` - Flow abbrechen

Los geht's! 💪"""
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(commands=['morning'])
def cmd_morning(message):
    send_morning_check(message.chat.id)

@bot.message_handler(commands=['evening'])
def cmd_evening(message):
    send_evening_check(message.chat.id)

@bot.message_handler(commands=['status'])
def cmd_status(message):
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    health_data = get_sheet_data(SHEETS['health'], 'A:BL')
    today_health = None
    if health_data:
        for row in health_data:
            if row and row[0] == today:
                today_health = row
                break
    
    sauna_count = get_sauna_count_this_week()
    score = today_health[1] if today_health and len(today_health) > 1 else '?'
    weight = today_health[32] if today_health and len(today_health) > 32 else '?'
    
    msg = f"""📊 **Status {today}**

😴 Sleep: {score}
⚖️ Weight: {weight}kg
🧖 Sauna: {sauna_count}/4"""
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(commands=['weekly'])
def cmd_weekly(message):
    send_weekly_review(message.chat.id)

@bot.message_handler(commands=['quick'])
def cmd_quick(message):
    msg = """⚡ **Quick-Logs**

```
weight 73.5
temp 36.8
bp 118 75
steps 8500
mood 7 6 8

gym 45 push 8
cardio 30 run
sauna 20 80 3x7
walk 45

meal reis huhn gemüse
craving thc 7
craving nic 5 yes
learn neuro 45 8

spent 15 food
spent 50 shopping i

supps ja ja ja ja ja ja
(blueprint omega3 probutyrate collagen nac schlaf)

grateful Sonne heute
habits 15 ja 10 5 7 8
```"""
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(commands=['reset', 'abort'])
def cmd_reset(message):
    clear_state(message.chat.id)
    bot.reply_to(message, "✅ Abgebrochen/Reset!")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    state = get_state(chat_id)
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    image_data = base64.b64encode(downloaded_file).decode('utf-8')
    
    if state and state.startswith('morning_'):
        process_morning_step(chat_id, state, image_data=image_data)
    elif state and state.startswith('evening_'):
        process_evening_step(chat_id, state, image_data=image_data)
    else:
        bot.reply_to(message, "📸 Starte /morning oder /evening")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text
    state = get_state(chat_id)
    
    if not state:
        if handle_quick_log(chat_id, text):
            return
    
    if state and state.startswith('morning_'):
        process_morning_step(chat_id, state, message=message)
    elif state and state.startswith('evening_'):
        process_evening_step(chat_id, state, message=message)
    elif state == 'monthly_measurements':
        parts = [p.strip() for p in text.replace(',', ' ').split()]
        if len(parts) >= 2:
            try:
                log_health_vitals(body_fat=float(parts[0]), waist=float(parts[1]))
                bot.reply_to(message, f"✅ Body Fat: {parts[0]}%, Waist: {parts[1]}cm")
                clear_state(chat_id)
            except:
                bot.reply_to(message, "Format: `bodyfat, waist`")
    else:
        try:
            response = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system="Du bist der Zeroism Coach Bot. Kurz, direkt, supportiv. Deutsch.",
                messages=[{"role": "user", "content": text}]
            )
            bot.reply_to(message, response.content[0].text)
        except Exception as e:
            bot.reply_to(message, f"Fehler: {str(e)}")

# === SCHEDULER ===

def start_scheduler():
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    scheduler.add_job(send_morning_check, CronTrigger(hour=7, minute=0), id='morning')
    scheduler.add_job(send_evening_check, CronTrigger(hour=22, minute=30), id='evening')
    scheduler.add_job(send_weekly_review, CronTrigger(day_of_week='sun', hour=18, minute=0), id='weekly')
    scheduler.add_job(send_monthly_check, CronTrigger(day=1, hour=10, minute=0), id='monthly')
    scheduler.start()
    print("⏰ Scheduler gestartet!")
    return scheduler

# === MAIN ===

if __name__ == "__main__":
    print("🚀 Zeroism Bot v3.1 starting...")
    print(f"📍 Timezone: {TIMEZONE}")
    scheduler = start_scheduler()
    print("📱 Bot polling...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(5)
