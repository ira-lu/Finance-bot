import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import threading
from flask import Flask
import os
import json

#connection to google table
table_name = 'LuOv_finance'

scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']

credentials = ServiceAccountCredentials.from_json_keyfile_name('luov-finance-project-b33b78877788.json', scope)

gs = gspread.authorize(credentials)
work_sheet = gs.open(table_name)
#select 1st sheet
sheet1 = work_sheet.sheet1


#get data in python lists format
data = sheet1.get_all_values()


#get header from data
headers = data.pop(0)

#connection to Telegram
bot_token = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(bot_token)
#connection to sheet with names of categories
categories_sheet = work_sheet.worksheet('Categories')
title_categories = categories_sheet.col_values(1)
title_categories.remove('') if '' in title_categories else title_categories #delete spaces
#function for creation keyboard with categories
def create_category_keyboard():
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2) #create a keyboard with 2 columns
    categories = title_categories
    buttons = [telebot.types.InlineKeyboardButton(text=category, callback_data=category) for category in categories] #create category buttons
    keyboard.add(*buttons)
    return keyboard
@bot.message_handler(commands=['start'])
#can be changed. Message handler respond to all incoming messages
#for example: @bot.message_handler(func=lambda message: 'hello' in message.text.lower()

#function for processing messages from the user
def start(message):
    bot.send_message(message.chat.id, 'Choose the category:', reply_markup=create_category_keyboard())
#lists of categories per user
user_categories = {}
@bot.callback_query_handler(func=lambda call: call.data in title_categories) 

def handle_category_callback(call):
    category=call.data
    user_id=call.message.chat.id
    user_categories[user_id] = category  # save the chosen category for this user
    
    bot.send_message(user_id,f'You have selected a category "{category}"')
    bot.send_message(user_id,f'Enter the purchase amount')
def create_question_keyboard():
    keyboard = telebot.types.InlineKeyboardMarkup()
    button_yes = telebot.types.InlineKeyboardButton(text="Yes", callback_data="add_another")
    button_no = telebot.types.InlineKeyboardButton(text="No", callback_data="finish")
    keyboard.add(button_yes, button_no)
    return keyboard
@bot.message_handler(func=lambda message: message.chat.id in user_categories.keys()) 
#message.chat.id in user_categories.keys() - for identification user that choose a category before

def handle_amount_input(message):
    if message.text == '/start':
         start(message)
    else:
        try:
            amount = float(message.text.strip())
            sheet1.update_cell(len(sheet1.col_values(2)) + 1, 2, user_categories[message.chat.id])
            sheet1.update_cell(len(sheet1.col_values(2)), 3, amount)
      
            message_datetime = datetime.fromtimestamp(message.date)
            formatted_datetime = message_datetime.strftime('%Y-%m-%d')
            sheet1.update_cell(len(sheet1.col_values(2)), 1, formatted_datetime)
    
            bot.send_message(message.chat.id, 'Data was successfully added to the Google Sheet.\nDo you want to add another category?',reply_markup=create_question_keyboard())
            
            
            #del user_categories[message.chat.id]
            
        except ValueError:
            bot.send_message(message.chat.id, "Please enter a valid number for the purchase amount")
@bot.callback_query_handler(func=lambda call: call.data == "add_another")
def add_another(call):
    start(call.message)
@bot.callback_query_handler(func=lambda call: call.data == "finish")

def finish(call):
    
    user_id = call.from_user.id
    if user_id in user_categories:
        del user_categories[user_id]
    bot.send_message(call.message.chat.id, "Thank you! Your data has been saved.")

def run_bot():
    bot.polling()

# --- Flask Web Server ---
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot's working!"

if name == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()

    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)
