import os
import telebot
import anthropic

bot = telebot.TeleBot(os.getenv("TELEGRAM_BOT_TOKEN"))
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

conversations = {}

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Hallo! Ich bin dein Claude Bot. Schreib mir etwas!")

@bot.message_handler(commands=['reset'])
def reset(message):
    conversations[message.chat.id] = []
    bot.reply_to(message, "Konversation zurückgesetzt!")

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    chat_id = message.chat.id
    
    if chat_id not in conversations:
        conversations[chat_id] = []
    
    conversations[chat_id].append({"role": "user", "content": message.text})
    
    if len(conversations[chat_id]) > 50:
        conversations[chat_id] = conversations[chat_id][-50:]
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=conversations[chat_id]
        )
        
        reply = response.content[0].text
        conversations[chat_id].append({"role": "assistant", "content": reply})
        
        if len(reply) > 4000:
            for i in range(0, len(reply), 4000):
                bot.reply_to(message, reply[i:i+4000])
        else:
            bot.reply_to(message, reply)
            
    except Exception as e:
        bot.reply_to(message, f"Fehler: {str(e)}")

print("Bot starting...")
bot.polling()
