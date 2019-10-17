# Intended to be used in @InfiniDee only

import config
import logging
from telegram import Update, Message, Bot
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, CallbackContext)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    updater = Updater(config.BOT_TOKEN, use_context=True)
    updater.dispatcher.add_handler(CommandHandler('start', cmd_start))
    updater.dispatcher.add_handler(CommandHandler('id', cmd_id))
    updater.dispatcher.add_handler()

    updater.start_polling()
    updater.idle()


def cmd_id(update: Update, context: CallbackContext):
    # if not a reply, display both group and user id
    message: Message = update.message
    if message.reply_to_message:
        reply(update.message, context.bot, f'Sender ID: <code>{message.reply_to_message.from_user.id}</code>')
    else:
        reply(update.message, context.bot, f'Your ID: <code>{message.from_user.id}</code>\n'
              f'Group ID: <code>{message.chat_id}</code>')
    pass


def cmd_start(update: Update, context: CallbackContext):
    print(update.message)
    print(context.chat_data)
    update.message.reply_text('start!', quote=True)
    pass


def reply(message: Message, bot: Bot, text):
    bot.send_message(message.chat_id, text, reply_to_message_id=message.message_id, parse_mode="html")


if __name__ == '__main__':
    main()
