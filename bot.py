#!/usr/bin/env python3
"""
ZEROISM BOT v3 - Complete Health & Life Optimization Tracker
Features:
- Morning Check (10 steps) @ 07:00 Canary Time
- Evening Review (9 steps) @ 22:30
- Weekly Review @ Sunday 18:00
- Monthly Check @ 1st of month 10:00
- Quick-log commands
- Claude Vision for Ringconn screenshots
- Auto macro calculation for meals
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
temp_data = defaultdict(dict)  # Temporary storage for multi-step flows
collected_images = defaultdict(list)  # Store images during flows

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

def log_to_sheet(sheet_name, row_data, range_override=None):
    """Generic function to append data to any sheet"""
    try:
        service = get_sheets_service()
        if not service:
            return False, "Google Sheets nicht verfügbar"
        
        range_str = range_override or f'{sheet_name}!A:BZ'
        
        service.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=range_str,
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body={'values': [row_data]}
        ).execute()
        
        return True, "Geloggt"
    except Exception as e:
        return False, str(e)

def update_row_in_sheet(sheet_name, row_number, col_start, col_end, values):
    """Update specific cells in an existing row"""
    try:
        service = get_sheets_service()
        if not service:
            return False, "Google Sheets nicht verfügbar"
        
        range_str = f'{sheet_name}!{col_start}{row_number}:{col_end}{row_number}'
        
        service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=range_str,
            valueInputOption='USER_ENTERED',
            body={'values': [values]}
        ).execute()
        
        return True, "Updated"
    except Exception as e:
        return False, str(e)

def find_row_by_date(sheet_name, date_str):
    """Find row number for a specific date"""
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
                return i + 1  # 1-indexed
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

# === SPECIFIC LOGGING FUNCTIONS ===

def log_health_ringconn(data):
    """Log Ringconn sleep data to HEALTH sheet (columns B-AF)"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    
    # Build row with all sleep data
    row = [
        today,
        data.get('sleep_score', ''),
        data.get('sleep_quality', ''),
        data.get('time_asleep_min', ''),
        data.get('time_in_bed_min', ''),
        data.get('sleep_efficiency', ''),
        data.get('sleep_goal_gap', ''),
        data.get('time_awake_ratio', ''),
        data.get('sleeping_hr', ''),
        data.get('sleeping_hrv', ''),
        data.get('skin_temp', ''),
        data.get('skin_temp_offset', ''),
        data.get('spo2', ''),
        data.get('respiratory_rate', ''),
        data.get('awake_min', ''),
        data.get('awake_pct', ''),
        data.get('rem_min', ''),
        data.get('rem_pct', ''),
        data.get('light_min', ''),
        data.get('light_pct', ''),
        data.get('deep_min', ''),
        data.get('deep_pct', ''),
        data.get('hr_awake', ''),
        data.get('hr_rem', ''),
        data.get('hr_light', ''),
        data.get('hr_deep', ''),
        data.get('rem_latency', ''),
        data.get('time_falling_asleep', ''),
        data.get('time_final_wake', ''),
        data.get('sleep_stability', ''),
        data.get('bedtime', ''),
        data.get('wake_time', '')
    ]
    
    return log_to_sheet(SHEETS['health'], row)

def log_health_vitals(weight=None, ear_temp=None, body_fat=None, waist=None, bp_sys=None, bp_dia=None):
    """Log vitals to HEALTH sheet - updates existing row for today"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row_num = find_row_by_date(SHEETS['health'], today)
    
    if row_num:
        # Update existing row
        values = [weight or '', ear_temp or '', body_fat or '', waist or '', bp_sys or '', bp_dia or '']
        return update_row_in_sheet(SHEETS['health'], row_num, 'AG', 'AL', values)
    else:
        # Create new row with date and vitals
        row = [today] + [''] * 31 + [weight or '', ear_temp or '', body_fat or '', waist or '', bp_sys or '', bp_dia or '']
        return log_to_sheet(SHEETS['health'], row)

def log_subjective_sleep(data):
    """Log subjective sleep quality to HEALTH sheet (columns AM-AU)"""
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
    """Log cutoff compliance to HEALTH sheet (columns AV-BE)"""
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
    """Log sleep environment to HEALTH sheet (columns BF-BJ)"""
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
    """Log daily activity to HEALTH sheet (columns BK-BL)"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    row_num = find_row_by_date(SHEETS['health'], today)
    
    values = [steps, calories]
    
    if row_num:
        return update_row_in_sheet(SHEETS['health'], row_num, 'BK', 'BL', values)
    else:
        row = [today] + [''] * 61 + values
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
    """Log meal to MEALS sheet with macros"""
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
    """Log supplements to SUPPLEMENTS sheet"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    
    row = [
        today,
        data.get('blueprint_stack', ''),
        data.get('omega3', ''),
        data.get('probutyrate', ''),
        data.get('collagen', ''),
        data.get('nac', ''),
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
    """Get weather for Las Palmas"""
    try:
        response = requests.get("https://wttr.in/Las+Palmas?format=%t+%C+%h+%w", timeout=10)
        if response.status_code == 200:
            return f"🌴 Las Palmas: {response.text.strip()}"
    except:
        pass
    return "Wetter Las Palmas nicht verfügbar"

def get_weather_germany():
    """Get weather for Germany (Gießen)"""
    try:
        response = requests.get("https://wttr.in/Giessen?format=%t+%C+%h+%w", timeout=10)
        if response.status_code == 200:
            return f"🇩🇪 Gießen: {response.text.strip()}"
    except:
        pass
    return "Wetter Deutschland nicht verfügbar"

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
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        return events.get('items', [])
    except:
        return []

def format_events(events):
    """Format events for display"""
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
    """Count sauna sessions this week"""
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
        for row in values[1:]:  # Skip header
            if len(row) >= 3:
                if row[0] >= week_start_str and 'sauna' in row[2].lower():
                    count += 1
        return count
    except:
        return 0

def get_weekly_stats():
    """Get weekly statistics for review"""
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
            'mood_avg': [],
            'expenses_total': 0,
            'learning_hours': 0,
            'supplements_compliance': 0
        }
        
        # Get HEALTH data
        health_data = get_sheet_data(SHEETS['health'], 'A:BL')
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
        
        # Get EXERCISE data
        exercise_data = get_sheet_data(SHEETS['exercise'], 'A:D')
        if exercise_data:
            training_dates = set()
            for row in exercise_data[1:]:
                if len(row) > 0 and row[0] >= week_start:
                    training_dates.add(row[0])
                    if len(row) > 2 and 'sauna' in row[2].lower():
                        stats['sauna_count'] += 1
            stats['training_days'] = len(training_dates)
        
        # Get MEALS data
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
        
        # Get FINANCE data
        finance_data = get_sheet_data(SHEETS['finance'], 'A:B')
        if finance_data:
            for row in finance_data[1:]:
                if len(row) > 1 and row[0] >= week_start:
                    try:
                        stats['expenses_total'] += float(row[1])
                    except:
                        pass
        
        # Get LEARNING data
        learning_data = get_sheet_data(SHEETS['learning'], 'A:D')
        if learning_data:
            for row in learning_data[1:]:
                if len(row) > 3 and row[0] >= week_start:
                    try:
                        stats['learning_hours'] += float(row[3]) / 60
                    except:
                        pass
        
        return stats
    except Exception as e:
        print(f"Error getting weekly stats: {e}")
        return {}

# === CLAUDE VISION FUNCTIONS ===

def process_image_with_claude(image_data, prompt):
    """Send image to Claude for analysis"""
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
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

def process_multiple_images_with_claude(images_data, prompt):
    """Send multiple images to Claude for analysis"""
    try:
        content = []
        for img_data in images_data:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": img_data
                }
            })
        content.append({
            "type": "text",
            "text": prompt
        })
        
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": content
            }]
        )
        return response.content[0].text
    except Exception as e:
        return f"Fehler: {str(e)}"

def parse_ringconn_sleep_images(images):
    """Extract all sleep data from 8 Ringconn screenshots"""
    prompt = """Analysiere diese 8 Ringconn Sleep Screenshots und extrahiere ALLE Daten.

Die 8 Screenshots zeigen:
1. Sleep Score Übersicht
2. Sleep Stages Grafik  
3. Sleep Stages Details
4. Sleep HR
5. Sleep HRV
6. SpO2
7. Respiratory Rate
8. Skin Temperature

Extrahiere und antworte NUR im folgenden JSON Format:
{
    "sleep_score": "Zahl 0-100",
    "sleep_quality": "Text wie 'Good'",
    "time_asleep_min": "Minuten",
    "time_in_bed_min": "Minuten",
    "sleep_efficiency": "Prozent",
    "sleeping_hr": "BPM",
    "sleeping_hrv": "ms",
    "skin_temp": "°C",
    "spo2": "Prozent",
    "respiratory_rate": "pro Minute",
    "awake_min": "Minuten",
    "awake_pct": "Prozent",
    "rem_min": "Minuten",
    "rem_pct": "Prozent",
    "light_min": "Minuten",
    "light_pct": "Prozent",
    "deep_min": "Minuten",
    "deep_pct": "Prozent",
    "bedtime": "HH:MM",
    "wake_time": "HH:MM"
}

Wenn ein Wert nicht sichtbar ist, schreibe "". Nur JSON ausgeben, keine Erklärungen."""
    
    result = process_multiple_images_with_claude(images, prompt)
    
    # Parse JSON from response
    try:
        # Find JSON in response
        json_match = re.search(r'\{[^{}]+\}', result, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except:
        pass
    
    return {}

def parse_activity_screenshot(image_data):
    """Extract steps and calories from activity screenshot"""
    prompt = """Analysiere diesen Ringconn Activity Screenshot.

Extrahiere:
- Steps (Schritte)
- Calories (Kalorien verbrannt)

Antworte NUR im Format:
steps,calories

Beispiel: 8500,2400

Wenn ein Wert nicht sichtbar ist, schreibe 0."""
    
    result = process_image_with_claude(image_data, prompt)
    
    try:
        parts = result.strip().split(',')
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
    except:
        pass
    
    return 0, 0

def parse_meal_image(image_data):
    """Analyze meal photo and calculate macros"""
    prompt = """Analysiere dieses Foto einer Mahlzeit.

Beschreibe die Zutaten und schätze die Nährwerte.

Antworte NUR im JSON Format:
{
    "ingredients": "Komma-getrennte Liste",
    "calories": "geschätzte Kalorien",
    "protein": "Gramm Protein",
    "carbs": "Gramm Kohlenhydrate",
    "fat": "Gramm Fett",
    "fiber": "Gramm Ballaststoffe",
    "category": "breakfast/lunch/dinner/snack"
}

Schätze realistisch basierend auf Portionsgröße."""
    
    result = process_image_with_claude(image_data, prompt)
    
    try:
        json_match = re.search(r'\{[^{}]+\}', result, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except:
        pass
    
    return {}

def calculate_meal_macros(description):
    """Calculate macros from text description"""
    prompt = f"""Berechne die Nährwerte für diese Mahlzeit: {description}

Antworte NUR im JSON Format:
{{
    "ingredients": "{description}",
    "calories": "geschätzte Kalorien",
    "protein": "Gramm Protein", 
    "carbs": "Gramm Kohlenhydrate",
    "fat": "Gramm Fett",
    "fiber": "Gramm Ballaststoffe",
    "category": "breakfast/lunch/dinner/snack"
}}

Schätze realistisch basierend auf typischen Portionsgrößen."""
    
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

# === FLOW STEP HANDLERS ===

def set_state(chat_id, step, data=None):
    """Set user state and optionally store data"""
    user_state[chat_id] = {"step": step}
    if data:
        temp_data[chat_id].update(data)

def get_state(chat_id):
    """Get current step for user"""
    return user_state.get(chat_id, {}).get("step")

def clear_state(chat_id):
    """Clear all state for user"""
    user_state[chat_id] = {"step": None}
    temp_data[chat_id] = {}
    collected_images[chat_id] = []

# === MORNING FLOW FUNCTIONS ===

def send_morning_check(chat_id=CHAT_ID):
    """Start Morning Check flow"""
    clear_state(chat_id)
    
    # Step 1: Weather + Calendar
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
Schick mir deine 8 Screenshots:
1. Sleep Score Übersicht
2. Sleep Stages Grafik
3. Sleep Stages Details
4. Sleep HR
5. Sleep HRV
6. SpO2
7. Respiratory Rate
8. Skin Temperature

Schick alle 8 Bilder nacheinander."""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_sleep_screenshots")
    collected_images[chat_id] = []

def process_morning_step(chat_id, step, message=None, image_data=None):
    """Process each step of morning flow"""
    
    if step == "morning_sleep_screenshots":
        if image_data:
            collected_images[chat_id].append(image_data)
            count = len(collected_images[chat_id])
            
            if count < 8:
                bot.send_message(chat_id, f"📸 {count}/8 Screenshots erhalten. Weiter...")
            else:
                bot.send_message(chat_id, "🔄 Analysiere Screenshots...")
                
                # Process all 8 images
                sleep_data = parse_ringconn_sleep_images(collected_images[chat_id])
                temp_data[chat_id]['sleep_data'] = sleep_data
                
                if sleep_data:
                    success, msg = log_health_ringconn(sleep_data)
                    score = sleep_data.get('sleep_score', '?')
                    bot.send_message(chat_id, f"✅ Sleep Data geloggt! Score: {score}")
                else:
                    bot.send_message(chat_id, "⚠️ Konnte Daten nicht extrahieren, aber weiter...")
                
                # Move to next step
                ask_subjective_sleep(chat_id)
        else:
            bot.send_message(chat_id, "📸 Bitte schick mir die Screenshots als Fotos.")
    
    elif step == "morning_subjective":
        if message:
            parse_subjective_sleep(chat_id, message.text)
    
    elif step == "morning_environment":
        if message:
            parse_sleep_environment(chat_id, message.text)
    
    elif step == "morning_cutoffs":
        if message:
            parse_cutoffs(chat_id, message.text)
    
    elif step == "morning_reading":
        if message:
            parse_reading(chat_id, message.text)
    
    elif step == "morning_supplements":
        if message:
            parse_supplements(chat_id, message.text)
    
    elif step == "morning_vitals":
        if message:
            parse_morning_vitals(chat_id, message.text)
    
    elif step == "morning_mood":
        if message:
            parse_morning_mood(chat_id, message.text)

def ask_subjective_sleep(chat_id):
    """Step 3: Ask for subjective sleep quality"""
    msg = """😴 **Subjektive Schlafqualität** (je 1-10)

Antworte im Format:
`erholt aufstehen träume körper klarheit durchgeschlafen aufwachen einschlafen`

Beispiel: `8 7 6 8 7 ja 1 schnell`

- durchgeschlafen: ja/nein
- aufwachen: Anzahl (0-X)
- einschlafen: schnell/normal/langsam"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_subjective")

def parse_subjective_sleep(chat_id, text):
    """Parse subjective sleep response"""
    parts = text.lower().split()
    
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
        
        success, msg = log_subjective_sleep(data)
        temp_data[chat_id]['subjective'] = data
        bot.send_message(chat_id, "✅ Subjektive Daten geloggt!")
    else:
        bot.send_message(chat_id, "⚠️ Format nicht erkannt, weiter...")
    
    ask_sleep_environment(chat_id)

def ask_sleep_environment(chat_id):
    """Step 4: Ask about sleep environment"""
    msg = """🛏️ **Schlafumgebung gestern**

Antworte im Format:
`dunkelheit lärm partner handy [raumtemp]`

Beispiel: `9 2 nein nein 19`

- dunkelheit: 1-10 (10=komplett dunkel)
- lärm: 1-10 (10=sehr laut)
- partner: ja/nein
- handy im Zimmer: ja/nein
- raumtemp: optional"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_environment")

def parse_sleep_environment(chat_id, text):
    """Parse sleep environment response"""
    parts = text.lower().split()
    
    if len(parts) >= 4:
        data = {
            'darkness': int(parts[0]) if parts[0].isdigit() else 5,
            'noise': int(parts[1]) if parts[1].isdigit() else 5,
            'partner': 'YES' if parts[2] in ['ja', 'yes', 'j', 'y'] else 'NO',
            'device_in_room': 'YES' if parts[3] in ['ja', 'yes', 'j', 'y'] else 'NO',
            'room_temp': parts[4] if len(parts) > 4 else ''
        }
        
        success, msg = log_sleep_environment(data)
        bot.send_message(chat_id, "✅ Umgebungsdaten geloggt!")
    else:
        bot.send_message(chat_id, "⚠️ Format nicht erkannt, weiter...")
    
    ask_cutoffs(chat_id)

def ask_cutoffs(chat_id):
    """Step 5: Ask about cutoffs yesterday"""
    msg = """⏰ **Cutoffs gestern eingehalten?**

Format: `thc nikotin koffein essen screens`
Jeweils: ja oder Uhrzeit wenn überschritten

Beispiele:
- `ja ja ja ja ja` (alles eingehalten)
- `23:00 ja 15:00 21:30 ja` (THC um 23:00, Koffein um 15:00, Essen um 21:30)"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_cutoffs")

def parse_cutoffs(chat_id, text):
    """Parse cutoffs response"""
    parts = text.lower().replace(',', '').split()
    
    if len(parts) >= 5:
        def parse_cutoff(val):
            if val in ['ja', 'yes', 'j', 'y']:
                return 'YES', ''
            elif ':' in val:
                return 'NO', val
            else:
                return 'NO', val
        
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
        
        success, msg = log_cutoffs(data)
        
        # Count violations
        violations = sum([1 for x in [thc_ok, nik_ok, koff_ok, ess_ok, scr_ok] if x == 'NO'])
        if violations == 0:
            bot.send_message(chat_id, "✅ Alle Cutoffs eingehalten! 💪")
        else:
            bot.send_message(chat_id, f"⚠️ {violations} Cutoff(s) überschritten - geloggt!")
    else:
        bot.send_message(chat_id, "⚠️ Format nicht erkannt, weiter...")
    
    ask_reading(chat_id)

def ask_reading(chat_id):
    """Step 6: Ask about reading yesterday evening"""
    msg = """📚 **Wie viele Minuten hast du gestern Abend gelesen?**

Antworte mit einer Zahl (oder 0/nein)"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_reading")

def parse_reading(chat_id, text):
    """Parse reading minutes"""
    text = text.lower().strip()
    
    if text in ['nein', 'no', 'n', '0']:
        minutes = 0
    else:
        try:
            minutes = int(re.search(r'\d+', text).group())
        except:
            minutes = 0
    
    # Log to habits for YESTERDAY
    data = {'reading': minutes}
    log_habits(data, for_yesterday=True)
    
    if minutes > 0:
        bot.send_message(chat_id, f"✅ {minutes} Minuten gelesen - nice!")
    else:
        bot.send_message(chat_id, "📚 Heute Abend lesen!")
    
    ask_supplements(chat_id)

def ask_supplements(chat_id):
    """Step 7: Ask about supplements"""
    msg = """💊 **Supplements**

Blueprint Stack komplett? 
Antworte: `ja` oder `nein`

Falls nein, welche extra?
Format: `nein omega nac collagen`"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_supplements")

def parse_supplements(chat_id, text):
    """Parse supplements response"""
    text = text.lower().strip()
    
    if text in ['ja', 'yes', 'j', 'y']:
        data = {
            'blueprint_stack': 'YES',
            'omega3': 'YES',
            'probutyrate': 'YES',
            'collagen': 'YES',
            'nac': 'YES'
        }
    else:
        parts = text.replace(',', '').split()
        data = {
            'blueprint_stack': 'NO',
            'omega3': 'YES' if 'omega' in parts or 'omega3' in parts else 'NO',
            'probutyrate': 'YES' if 'probutyrate' in parts or 'pro' in parts else 'NO',
            'collagen': 'YES' if 'collagen' in parts or 'col' in parts else 'NO',
            'nac': 'YES' if 'nac' in parts else 'NO'
        }
    
    success, msg = log_supplements(data)
    bot.send_message(chat_id, "✅ Supplements geloggt!")
    
    ask_morning_vitals(chat_id)

def ask_morning_vitals(chat_id):
    """Step 8: Ask for morning vitals"""
    now = datetime.now(TIMEZONE)
    is_sunday = now.weekday() == 6
    
    if is_sunday:
        msg = """⚖️ **Morning Vitals**

Heute ist Sonntag - auch Blutdruck!
Format: `gewicht ohrtemp sys dia`

Beispiel: `73.5 36.8 118 75`"""
    else:
        msg = """⚖️ **Morning Vitals**

Format: `gewicht ohrtemp`

Beispiel: `73.5 36.8`"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_vitals")

def parse_morning_vitals(chat_id, text):
    """Parse morning vitals"""
    parts = text.replace(',', '.').split()
    
    weight = None
    ear_temp = None
    bp_sys = None
    bp_dia = None
    
    try:
        if len(parts) >= 1:
            weight = float(parts[0])
        if len(parts) >= 2:
            ear_temp = float(parts[1])
        if len(parts) >= 4:
            bp_sys = int(parts[2])
            bp_dia = int(parts[3])
    except:
        pass
    
    success, msg = log_health_vitals(weight=weight, ear_temp=ear_temp, bp_sys=bp_sys, bp_dia=bp_dia)
    
    vitals_msg = f"✅ Vitals geloggt: {weight}kg"
    if bp_sys:
        vitals_msg += f", BP: {bp_sys}/{bp_dia}"
    bot.send_message(chat_id, vitals_msg)
    
    ask_morning_mood(chat_id)

def ask_morning_mood(chat_id):
    """Step 9: Ask for morning mood"""
    msg = """🌅 **Wie fühlst du dich?** (je 1-10)

Format: `stimmung energie motivation`

Beispiel: `7 6 8`"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "morning_mood")

def parse_morning_mood(chat_id, text):
    """Parse morning mood and finish"""
    parts = text.split()
    
    if len(parts) >= 3:
        data = {
            'mood': int(parts[0]) if parts[0].isdigit() else 5,
            'energy': int(parts[1]) if parts[1].isdigit() else 5,
            'motivation': int(parts[2]) if parts[2].isdigit() else 5
        }
        
        success, msg = log_mood("morning", data)
        bot.send_message(chat_id, "✅ Mood geloggt!")
    
    finish_morning_check(chat_id)

def finish_morning_check(chat_id):
    """Complete morning check with summary"""
    sleep_data = temp_data[chat_id].get('sleep_data', {})
    score = sleep_data.get('sleep_score', '?')
    
    # Generate recommendation based on sleep
    if score != '?' and int(score) >= 85:
        reco = "🎯 Super Schlaf! Nutze die Energie heute."
    elif score != '?' and int(score) >= 70:
        reco = "👍 Solider Schlaf. Focus auf Hydration und Movement."
    else:
        reco = "⚡ Fokus auf Erholung heute. Sauna? Früh ins Bett."
    
    msg = f"""✅ **MORNING CHECK KOMPLETT**

Sleep Score: {score}
{reco}

📸 Reminder: Mach heute Fotos von deinen Mahlzeiten!

Guten Tag! ☀️"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    clear_state(chat_id)

# === EVENING FLOW FUNCTIONS ===

def send_evening_check(chat_id=CHAT_ID):
    """Start Evening Review flow"""
    clear_state(chat_id)
    
    msg = """🌙 **EVENING REVIEW**

📱 Schick mir deinen Ringconn Activity Screenshot (Steps & Calories)"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_activity")

def process_evening_step(chat_id, step, message=None, image_data=None):
    """Process each step of evening flow"""
    
    if step == "evening_activity":
        if image_data:
            bot.send_message(chat_id, "🔄 Analysiere Activity...")
            steps, calories = parse_activity_screenshot(image_data)
            log_activity(steps, calories)
            temp_data[chat_id]['steps'] = steps
            temp_data[chat_id]['calories'] = calories
            bot.send_message(chat_id, f"✅ {steps:,} Steps, {calories} kcal geloggt!")
            ask_evening_exercise(chat_id)
        else:
            bot.send_message(chat_id, "📸 Bitte schick den Activity Screenshot.")
    
    elif step == "evening_exercise":
        if message:
            parse_evening_exercise(chat_id, message.text)
    
    elif step == "evening_exercise_details":
        if message:
            parse_exercise_details(chat_id, message.text)
    
    elif step == "evening_meals":
        if message or image_data:
            parse_evening_meals(chat_id, message, image_data)
    
    elif step == "evening_learning":
        if message:
            parse_evening_learning(chat_id, message.text)
    
    elif step == "evening_habits":
        if message:
            parse_evening_habits(chat_id, message.text)
    
    elif step == "evening_cravings":
        if message:
            parse_evening_cravings(chat_id, message.text)
    
    elif step == "evening_finance":
        if message:
            parse_evening_finance(chat_id, message.text)
    
    elif step == "evening_mood":
        if message:
            parse_evening_mood(chat_id, message.text)

def ask_evening_exercise(chat_id):
    """Step 2: Ask about exercise"""
    msg = """🏋️ **Training heute?**

Antworte `nein` oder mit Details:

Gym: `gym 45 push 8 [stretching_min]`
Cardio: `cardio 30 run`
Sauna: `sauna 80 3 7` (temp, runden, min/runde)
Walk: `walk 45`
Fußball: `fussball 90`"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_exercise")

def parse_evening_exercise(chat_id, text):
    """Parse exercise response"""
    text = text.lower().strip()
    
    if text == 'nein':
        ask_evening_meals(chat_id)
        return
    
    parts = text.split()
    exercise_type = parts[0] if parts else ''
    
    data = {'type': exercise_type}
    
    if exercise_type == 'gym' and len(parts) >= 4:
        data['duration'] = parts[1]
        data['workout_type'] = parts[2]
        data['rpe'] = parts[3]
        data['stretching'] = parts[4] if len(parts) > 4 else ''
    
    elif exercise_type == 'cardio' and len(parts) >= 3:
        data['duration'] = parts[1]
        data['workout_type'] = parts[2]
    
    elif exercise_type == 'sauna' and len(parts) >= 4:
        data['sauna_temp'] = parts[1]
        data['sauna_rounds'] = parts[2]
        data['sauna_time_per_round'] = parts[3]
        data['duration'] = int(parts[2]) * int(parts[3])  # Calculate total time
    
    elif exercise_type in ['walk', 'fussball', 'sport', 'yoga'] and len(parts) >= 2:
        data['duration'] = parts[1]
    
    else:
        bot.send_message(chat_id, "⚠️ Format nicht erkannt, weiter...")
        ask_evening_meals(chat_id)
        return
    
    success, msg = log_exercise(data)
    
    # Check sauna count
    if exercise_type == 'sauna':
        count = get_sauna_count_this_week()
        bot.send_message(chat_id, f"✅ Sauna geloggt! 🧖 Diese Woche: {count}/4")
    else:
        bot.send_message(chat_id, f"✅ {exercise_type.capitalize()} geloggt!")
    
    ask_evening_meals(chat_id)

def ask_evening_meals(chat_id):
    """Step 3: Ask about meals"""
    msg = """🍽️ **Was hast du heute gegessen?**

Schick Fotos ODER Text-Beschreibung.
Mehrere Mahlzeiten mit `|` trennen.

Beispiele:
- Foto schicken
- `oatmeal blueberries | chicken rice vegetables | yogurt nuts`

Oder `done` wenn fertig."""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_meals")
    temp_data[chat_id]['meal_count'] = 0
    temp_data[chat_id]['total_calories'] = 0
    temp_data[chat_id]['total_protein'] = 0

def parse_evening_meals(chat_id, message, image_data):
    """Parse meal input"""
    if message and message.text.lower() == 'done':
        total_cal = temp_data[chat_id].get('total_calories', 0)
        total_prot = temp_data[chat_id].get('total_protein', 0)
        count = temp_data[chat_id].get('meal_count', 0)
        
        if count > 0:
            bot.send_message(chat_id, f"✅ {count} Mahlzeit(en) geloggt!\n📊 Total: ~{total_cal} kcal, ~{total_prot}g Protein")
        
        ask_evening_learning(chat_id)
        return
    
    now = datetime.now(TIMEZONE).strftime('%H:%M')
    
    if image_data:
        bot.send_message(chat_id, "🔄 Analysiere Mahlzeit...")
        macros = parse_meal_image(image_data)
        
        if macros:
            macros['time'] = now
            macros['meal_num'] = temp_data[chat_id].get('meal_count', 0) + 1
            
            success, msg = log_meal(macros)
            temp_data[chat_id]['meal_count'] += 1
            
            try:
                temp_data[chat_id]['total_calories'] += int(macros.get('calories', 0))
                temp_data[chat_id]['total_protein'] += int(macros.get('protein', 0))
            except:
                pass
            
            bot.send_message(chat_id, f"✅ Mahlzeit geloggt: {macros.get('ingredients', '')} (~{macros.get('calories', '?')} kcal)")
        else:
            bot.send_message(chat_id, "⚠️ Konnte nicht analysieren. Beschreib textlich?")
    
    elif message:
        meals = message.text.split('|')
        
        for meal_desc in meals:
            meal_desc = meal_desc.strip()
            if not meal_desc:
                continue
            
            macros = calculate_meal_macros(meal_desc)
            macros['time'] = now
            macros['meal_num'] = temp_data[chat_id].get('meal_count', 0) + 1
            
            success, msg = log_meal(macros)
            temp_data[chat_id]['meal_count'] += 1
            
            try:
                temp_data[chat_id]['total_calories'] += int(macros.get('calories', 0))
                temp_data[chat_id]['total_protein'] += int(macros.get('protein', 0))
            except:
                pass
        
        bot.send_message(chat_id, f"✅ {len(meals)} Mahlzeit(en) geloggt! Weitere? Oder `done`")

def ask_evening_learning(chat_id):
    """Step 4: Ask about learning"""
    msg = """📚 **Was gelernt heute?**

Format: `thema dauer kategorie focus`
Kategorien: uni/work/personal/admin

Beispiel: `neuro 45 uni 8`

Oder `nein`"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_learning")

def parse_evening_learning(chat_id, text):
    """Parse learning response"""
    text = text.lower().strip()
    
    if text == 'nein':
        ask_evening_habits(chat_id)
        return
    
    parts = text.split()
    
    if len(parts) >= 4:
        data = {
            'task': parts[0],
            'duration': parts[1],
            'category': parts[2],
            'focus_quality': parts[3]
        }
        
        success, msg = log_learning(data)
        bot.send_message(chat_id, f"✅ Learning geloggt: {parts[0]} {parts[1]}min")
    else:
        bot.send_message(chat_id, "⚠️ Format nicht erkannt, weiter...")
    
    ask_evening_habits(chat_id)

def ask_evening_habits(chat_id):
    """Step 5: Ask about daily habits"""
    msg = """☀️ **Tägliche Gewohnheiten**

Format: `sonnenlicht blaulicht meditation atem sozial hydration`

Beispiel: `15 ja 10 5 7 8`

- sonnenlicht: Minuten morgens
- blaulicht: ja/nein (Brille abends)
- meditation: Minuten
- atem: Minuten Atemübungen
- sozial: 1-10
- hydration: 1-10

Optional am Ende: Dankbarkeit (Text)"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_habits")

def parse_evening_habits(chat_id, text):
    """Parse habits response"""
    parts = text.split()
    
    if len(parts) >= 6:
        data = {
            'sunlight_morning': parts[0],
            'blue_light_glasses': 'YES' if parts[1] in ['ja', 'yes', 'j', 'y'] else 'NO',
            'meditation': parts[2],
            'breathwork': parts[3],
            'social_interaction': parts[4],
            'hydration': parts[5],
            'grateful_for': ' '.join(parts[6:]) if len(parts) > 6 else ''
        }
        
        success, msg = log_habits(data)
        bot.send_message(chat_id, "✅ Habits geloggt!")
    else:
        bot.send_message(chat_id, "⚠️ Format nicht erkannt, weiter...")
    
    ask_evening_cravings(chat_id)

def ask_evening_cravings(chat_id):
    """Step 6: Ask about cravings"""
    msg = """🍬 **Cravings heute?**

Format: `typ intensität [nachgegeben]`

Beispiele:
- `thc 7`
- `nic 5 yes` (nachgegeben)
- `thc 6, nic 4` (mehrere)

Oder `nein`"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_cravings")

def parse_evening_cravings(chat_id, text):
    """Parse cravings response"""
    text = text.lower().strip()
    
    if text == 'nein':
        bot.send_message(chat_id, "✅ Clean day! 💪")
        ask_evening_finance(chat_id)
        return
    
    # Handle multiple cravings
    cravings = text.split(',')
    
    for craving in cravings:
        parts = craving.strip().split()
        
        if len(parts) >= 2:
            data = {
                'type': parts[0],
                'intensity': parts[1],
                'action_taken': 'YES' if len(parts) > 2 and parts[2] in ['yes', 'ja', 'y'] else 'NO'
            }
            
            log_craving(data)
    
    bot.send_message(chat_id, f"✅ {len(cravings)} Craving(s) geloggt!")
    ask_evening_finance(chat_id)

def ask_evening_finance(chat_id):
    """Step 7: Ask about expenses"""
    msg = """💸 **Ausgaben heute?**

Format: `betrag kategorie [beschreibung] [n/i]`
- n = notwendig
- i = impuls

Beispiele:
- `15 food`
- `50 shopping amazon i` (Impulskauf)
- `12 food, 30 transport`

Oder `nein`"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_finance")

def parse_evening_finance(chat_id, text):
    """Parse finance response"""
    text = text.lower().strip()
    
    if text == 'nein':
        ask_evening_mood(chat_id)
        return
    
    # Handle multiple expenses
    expenses = text.split(',')
    total = 0
    
    for expense in expenses:
        parts = expense.strip().split()
        
        if len(parts) >= 2:
            try:
                amount = float(parts[0])
                total += amount
            except:
                continue
            
            data = {
                'amount': parts[0],
                'category': parts[1],
                'description': parts[2] if len(parts) > 2 and parts[2] not in ['n', 'i'] else '',
                'necessary': 'YES' if 'n' in parts else 'NO',
                'impulse': 'YES' if 'i' in parts else 'NO'
            }
            
            log_finance(data)
    
    bot.send_message(chat_id, f"✅ {len(expenses)} Ausgabe(n) geloggt! Total: €{total:.2f}")
    ask_evening_mood(chat_id)

def ask_evening_mood(chat_id):
    """Step 8: Ask for evening mood"""
    msg = """🌙 **Wie geht's dir?** (je 1-10)

Format: `stimmung focus angst stress social`

Beispiel: `7 6 3 4 5`"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "evening_mood")

def parse_evening_mood(chat_id, text):
    """Parse evening mood and finish"""
    parts = text.split()
    
    if len(parts) >= 5:
        data = {
            'mood': int(parts[0]) if parts[0].isdigit() else 5,
            'focus': int(parts[1]) if parts[1].isdigit() else 5,
            'anxiety': int(parts[2]) if parts[2].isdigit() else 5,
            'stress': int(parts[3]) if parts[3].isdigit() else 5,
            'social_battery': int(parts[4]) if parts[4].isdigit() else 5
        }
        
        success, msg = log_mood("evening", data)
        bot.send_message(chat_id, "✅ Mood geloggt!")
    
    finish_evening_review(chat_id)

def finish_evening_review(chat_id):
    """Complete evening review with summary"""
    total_cal = temp_data[chat_id].get('total_calories', 0)
    total_prot = temp_data[chat_id].get('total_protein', 0)
    steps = temp_data[chat_id].get('steps', 0)
    sauna_count = get_sauna_count_this_week()
    
    msg = f"""✅ **EVENING REVIEW KOMPLETT**

📊 Heute:
- Steps: {steps:,}
- Kalorien: ~{total_cal} kcal
- Protein: ~{total_prot}g

🧖 Sauna diese Woche: {sauna_count}/4

Gute Nacht! 🌙"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    clear_state(chat_id)

# === WEEKLY REVIEW ===

def send_weekly_review(chat_id=CHAT_ID):
    """Send weekly review summary"""
    stats = get_weekly_stats()
    
    sleep_avg = sum(stats['sleep_scores']) / len(stats['sleep_scores']) if stats['sleep_scores'] else 0
    hrv_avg = sum(stats['hrv_values']) / len(stats['hrv_values']) if stats['hrv_values'] else 0
    cal_avg = sum(stats['calories']) / len(stats['calories']) if stats['calories'] else 0
    prot_avg = sum(stats['protein']) / len(stats['protein']) if stats['protein'] else 0
    
    msg = f"""📊 **WEEKLY REVIEW**

😴 **Schlaf**
- Sleep Score Ø: {sleep_avg:.1f}
- HRV Ø: {hrv_avg:.0f}ms

🏋️ **Training**
- Trainingstage: {stats['training_days']}
- Sauna: {stats['sauna_count']}/4 {"✅" if stats['sauna_count'] >= 4 else "❌"}

🍽️ **Ernährung**
- Kalorien Ø: {cal_avg:.0f} kcal
- Protein Ø: {prot_avg:.0f}g

💸 **Ausgaben**: €{stats['expenses_total']:.2f}

📚 **Lernen**: {stats['learning_hours']:.1f}h

---
Nächste Woche besser! 💪"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')

# === MONTHLY CHECK ===

def send_monthly_check(chat_id=CHAT_ID):
    """Send monthly measurement reminder"""
    msg = """📅 **MONTHLY CHECK**

Zeit für die monatlichen Messungen:

1. 📏 Body Fat % messen
2. 📐 Taillenumfang messen
3. 🏃 VO2max Test fällig?

Antworte mit:
`bodyfat waist`

Beispiel: `18.5 82`"""
    
    bot.send_message(chat_id, msg, parse_mode='Markdown')
    set_state(chat_id, "monthly_measurements")

# === QUICK LOG COMMANDS ===

def handle_quick_log(chat_id, text):
    """Handle quick log commands"""
    text = text.lower().strip()
    parts = text.split()
    
    if not parts:
        return False
    
    cmd = parts[0]
    
    # Weight
    if cmd == 'weight' and len(parts) >= 2:
        try:
            weight = float(parts[1].replace(',', '.'))
            success, msg = log_health_vitals(weight=weight)
            bot.send_message(chat_id, f"✅ Gewicht: {weight}kg")
            return True
        except:
            pass
    
    # Temperature
    elif cmd == 'temp' and len(parts) >= 2:
        try:
            temp = float(parts[1].replace(',', '.'))
            success, msg = log_health_vitals(ear_temp=temp)
            bot.send_message(chat_id, f"✅ Temperatur: {temp}°C")
            return True
        except:
            pass
    
    # Blood pressure
    elif cmd == 'bp' and len(parts) >= 3:
        try:
            sys = int(parts[1])
            dia = int(parts[2])
            success, msg = log_health_vitals(bp_sys=sys, bp_dia=dia)
            bot.send_message(chat_id, f"✅ Blutdruck: {sys}/{dia}")
            return True
        except:
            pass
    
    # Mood (morning format)
    elif cmd == 'mood' and len(parts) >= 4:
        try:
            data = {
                'mood': int(parts[1]),
                'energy': int(parts[2]),
                'motivation': int(parts[3])
            }
            success, msg = log_mood("quick", data)
            bot.send_message(chat_id, f"✅ Mood: {parts[1]}/{parts[2]}/{parts[3]}")
            return True
        except:
            pass
    
    # Gym
    elif cmd == 'gym' and len(parts) >= 4:
        data = {
            'type': 'Gym',
            'duration': parts[1],
            'workout_type': parts[2],
            'rpe': parts[3],
            'stretching': parts[4] if len(parts) > 4 else ''
        }
        success, msg = log_exercise(data)
        bot.send_message(chat_id, f"✅ Gym {parts[1]}min ({parts[2]}) RPE {parts[3]}")
        return True
    
    # Cardio
    elif cmd == 'cardio' and len(parts) >= 3:
        data = {
            'type': 'Cardio',
            'duration': parts[1],
            'workout_type': parts[2]
        }
        success, msg = log_exercise(data)
        bot.send_message(chat_id, f"✅ Cardio {parts[1]}min ({parts[2]})")
        return True
    
    # Sauna
    elif cmd == 'sauna' and len(parts) >= 4:
        # Format: sauna 20 80 3x7 -> duration temp rounds x time
        data = {
            'type': 'Sauna',
            'duration': parts[1],
            'sauna_temp': parts[2]
        }
        if 'x' in parts[3]:
            rounds, time_per = parts[3].split('x')
            data['sauna_rounds'] = rounds
            data['sauna_time_per_round'] = time_per
        
        success, msg = log_exercise(data)
        count = get_sauna_count_this_week()
        bot.send_message(chat_id, f"✅ Sauna {parts[1]}min @ {parts[2]}°C\n🧖 Diese Woche: {count}/4")
        return True
    
    # Walk
    elif cmd == 'walk' and len(parts) >= 2:
        data = {
            'type': 'Walk',
            'duration': parts[1]
        }
        success, msg = log_exercise(data)
        bot.send_message(chat_id, f"✅ Walk {parts[1]}min")
        return True
    
    # Meal
    elif cmd == 'meal' and len(parts) >= 2:
        description = ' '.join(parts[1:])
        macros = calculate_meal_macros(description)
        macros['time'] = datetime.now(TIMEZONE).strftime('%H:%M')
        
        success, msg = log_meal(macros)
        cal = macros.get('calories', '?')
        prot = macros.get('protein', '?')
        bot.send_message(chat_id, f"✅ Meal: {description}\n~{cal} kcal, ~{prot}g protein")
        return True
    
    # Craving
    elif cmd == 'craving' and len(parts) >= 3:
        gave_in = 'YES' if len(parts) > 3 and parts[3] in ['yes', 'ja', 'y'] else 'NO'
        data = {
            'type': parts[1],
            'intensity': parts[2],
            'action_taken': gave_in
        }
        success, msg = log_craving(data)
        emoji = "😔" if gave_in == 'YES' else "💪"
        bot.send_message(chat_id, f"✅ Craving: {parts[1]} ({parts[2]}/10) {emoji}")
        return True
    
    # Learn
    elif cmd == 'learn' and len(parts) >= 4:
        data = {
            'task': parts[1],
            'duration': parts[2],
            'focus_quality': parts[3],
            'category': parts[4] if len(parts) > 4 else 'personal'
        }
        success, msg = log_learning(data)
        bot.send_message(chat_id, f"✅ Learned: {parts[1]} {parts[2]}min (Focus: {parts[3]})")
        return True
    
    # Spent
    elif cmd == 'spent' and len(parts) >= 3:
        impulse = 'YES' if 'i' in parts else 'NO'
        data = {
            'amount': parts[1],
            'category': parts[2],
            'impulse': impulse
        }
        success, msg = log_finance(data)
        emoji = "🤔" if impulse == 'YES' else ""
        bot.send_message(chat_id, f"✅ Spent: €{parts[1]} ({parts[2]}) {emoji}")
        return True
    
    # Supps
    elif cmd == 'supps':
        if len(parts) >= 2 and parts[1] in ['ja', 'yes', 'y']:
            data = {
                'blueprint_stack': 'YES',
                'omega3': 'YES',
                'probutyrate': 'YES',
                'collagen': 'YES',
                'nac': 'YES'
            }
        else:
            data = {
                'blueprint_stack': 'NO',
                'omega3': 'YES' if 'omega' in text else 'NO',
                'probutyrate': 'YES' if 'pro' in text else 'NO',
                'collagen': 'YES' if 'collagen' in text or 'col' in text else 'NO',
                'nac': 'YES' if 'nac' in text else 'NO'
            }
        
        success, msg = log_supplements(data)
        bot.send_message(chat_id, "✅ Supplements geloggt!")
        return True
    
    return False

# === TELEGRAM HANDLERS ===

@bot.message_handler(commands=['start'])
def cmd_start(message):
    """Welcome message"""
    msg = """👋 **Zeroism Bot v3**

Dein persönlicher Health & Life Tracker.

**Automatische Checks:**
- ☀️ 07:00 Morning Check
- 🌙 22:30 Evening Review
- 📊 Sonntag 18:00 Weekly Review
- 📅 Monatlich Measurements

**Commands:**
/morning - Morning Check starten
/evening - Evening Review starten
/status - Heutiger Status
/weekly - Weekly Review
/quick - Quick-Log Hilfe
/reset - State zurücksetzen

Los geht's! 💪"""
    
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(commands=['morning'])
def cmd_morning(message):
    """Start morning check manually"""
    send_morning_check(message.chat.id)

@bot.message_handler(commands=['evening'])
def cmd_evening(message):
    """Start evening review manually"""
    send_evening_check(message.chat.id)

@bot.message_handler(commands=['status'])
def cmd_status(message):
    """Show today's status"""
    today = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
    
    # Get today's data
    health_data = get_sheet_data(SHEETS['health'], f'A:BL')
    today_health = None
    if health_data:
        for row in health_data:
            if row and row[0] == today:
                today_health = row
                break
    
    sauna_count = get_sauna_count_this_week()
    
    msg = f"""📊 **Status {today}**

😴 Sleep Score: {today_health[1] if today_health and len(today_health) > 1 else '?'}
⚖️ Weight: {today_health[32] if today_health and len(today_health) > 32 else '?'}kg
🧖 Sauna diese Woche: {sauna_count}/4

/morning oder /evening starten!"""
    
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(commands=['weekly'])
def cmd_weekly(message):
    """Show weekly review"""
    send_weekly_review(message.chat.id)

@bot.message_handler(commands=['quick'])
def cmd_quick(message):
    """Show quick log help"""
    msg = """⚡ **Quick-Log Commands**

```
weight 73.5          → Gewicht
temp 36.8            → Ohr-Temp
bp 118 75            → Blutdruck

mood 7 6 8           → Mood (stimmung energie motivation)

gym 45 push 8        → Gym (min type rpe)
cardio 30 run        → Cardio
sauna 20 80 3x7      → Sauna (min temp rounds×time)
walk 45              → Walk

meal reis huhn       → Meal + Auto-Macros

craving thc 7        → Craving
craving nic 5 yes    → Craving (nachgegeben)

learn neuro 45 8     → Learning (topic min focus)

spent 15 food        → Ausgabe
spent 50 shopping i  → Impulskauf

supps ja             → Supplements (Stack=yes)
supps nein omega nac → Supplements einzeln
```"""
    
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(commands=['reset'])
def cmd_reset(message):
    """Reset conversation state"""
    clear_state(message.chat.id)
    bot.reply_to(message, "✅ State zurückgesetzt!")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    """Handle photo messages"""
    chat_id = message.chat.id
    state = get_state(chat_id)
    
    # Download image
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    image_data = base64.b64encode(downloaded_file).decode('utf-8')
    
    # Process based on state
    if state and state.startswith('morning_'):
        process_morning_step(chat_id, state, image_data=image_data)
    elif state and state.startswith('evening_'):
        process_evening_step(chat_id, state, image_data=image_data)
    else:
        # No active state - try to identify image type
        bot.reply_to(message, "📸 Starte /morning oder /evening um Screenshots zu verarbeiten.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    """Handle all text messages"""
    chat_id = message.chat.id
    text = message.text
    state = get_state(chat_id)
    
    # Check for quick log first (if no active state)
    if not state or state is None:
        if handle_quick_log(chat_id, text):
            return
    
    # Process based on current state
    if state and state.startswith('morning_'):
        process_morning_step(chat_id, state, message=message)
    elif state and state.startswith('evening_'):
        process_evening_step(chat_id, state, message=message)
    elif state == 'monthly_measurements':
        # Handle monthly measurements
        parts = text.split()
        if len(parts) >= 2:
            try:
                body_fat = float(parts[0])
                waist = float(parts[1])
                success, msg = log_health_vitals(body_fat=body_fat, waist=waist)
                bot.reply_to(message, f"✅ Body Fat: {body_fat}%, Waist: {waist}cm")
                clear_state(chat_id)
            except:
                bot.reply_to(message, "⚠️ Format: `bodyfat waist` (z.B. 18.5 82)")
    else:
        # General conversation with Claude
        try:
            response = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system="Du bist der Zeroism Coach Bot. Kurz, direkt, supportiv. Deutsch. Hilf bei Health Tracking und gib motivierende Tipps.",
                messages=[{"role": "user", "content": text}]
            )
            bot.reply_to(message, response.content[0].text)
        except Exception as e:
            bot.reply_to(message, f"Fehler: {str(e)}")

# === SCHEDULER ===

def start_scheduler():
    """Initialize and start the scheduler"""
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    
    # Morning Check: 07:00
    scheduler.add_job(
        send_morning_check,
        CronTrigger(hour=7, minute=0),
        id='morning_check'
    )
    
    # Evening Review: 22:30
    scheduler.add_job(
        send_evening_check,
        CronTrigger(hour=22, minute=30),
        id='evening_review'
    )
    
    # Weekly Review: Sunday 18:00
    scheduler.add_job(
        send_weekly_review,
        CronTrigger(day_of_week='sun', hour=18, minute=0),
        id='weekly_review'
    )
    
    # Monthly Check: 1st of month 10:00
    scheduler.add_job(
        send_monthly_check,
        CronTrigger(day=1, hour=10, minute=0),
        id='monthly_check'
    )
    
    scheduler.start()
    print("⏰ Scheduler gestartet!")
    return scheduler

# === MAIN ===

if __name__ == "__main__":
    print("🚀 Zeroism Bot v3 starting...")
    print(f"📍 Timezone: {TIMEZONE}")
    print(f"📊 Sheet ID: {SHEET_ID}")
    
    scheduler = start_scheduler()
    
    print("📱 Bot polling...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"❌ Polling error: {e}")
            time.sleep(5)
