import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import anthropic

# Initialize Claude client
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Store conversation history per chat
conversations = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hallo! Ich bin dein Claude Bot. Schreib mir etwas!")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversations[chat_id] = []
    await update.message.reply_text("Konversation zurückgesetzt!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_message = update.message.text
    
    # Initialize conversation history if not exists
    if chat_id not in conversations:
        conversations[chat_id] = []
    
    # Add user message to history
    conversations[chat_id].append({"role": "user", "content": user_message})
    
    # Keep only last 50 messages
    if len(conversations[chat_id]) > 50:
        conversations[chat_id] = conversations[chat_id][-50:]
    
    try:
        # Call Claude API
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=conversations[chat_id]
        )
        
        assistant_message = response.content[0].text
        
        # Add assistant response to history
        conversations[chat_id].append({"role": "assistant", "content": assistant_message})
        
        # Send response (split if too long)
        if len(assistant_message) > 4000:
            for i in range(0, len(assistant_message), 4000):
                await update.message.reply_text(assistant_message[i:i+4000])
        else:
            await update.message.reply_text(assistant_message)
            
    except Exception as e:
        await update.message.reply_text(f"Fehler: {str(e)}")

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
```

4. Klicke **"Commit changes"**

---

## Datei 3: `Procfile`

1. Klicke nochmal **"Add file"** → **"Create new file"**
2. Name: `Procfile` (genau so, ohne Endung!)
3. Inhalt:
```
worker: python bot.py
