# Intended to be used in @InfiniDee only

import config
import logging
from functools import wraps
from telegram import Update, Message, Bot, ChatPermissions
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, CallbackContext)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def restricted(func):
    @wraps(func)
    def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != config.OWNER_ID:
            logger.log(logging.INFO, "Unauthorized access to /{} denied for {}.".format(func.__name__, user_id))
            return
        return func(update, context, *args, **kwargs)
    return wrapped


def reply(message: Message, bot: Bot, text):
    bot.send_message(message.chat_id, text, reply_to_message_id=message.message_id, parse_mode="html")


def cmd_id(update: Update, context: CallbackContext):
    # if not a reply, display both group and user id
    message: Message = update.message
    if message.reply_to_message:
        reply(message, context.bot, f'Sender ID: <code>{message.reply_to_message.from_user.id}</code>')
    else:
        reply(message, context.bot, f'Your ID: <code>{message.from_user.id}</code>\n'
              f'Group ID: <code>{message.chat_id}</code>')
    pass


def cmd_start(update: Update, context: CallbackContext):
    update.message.reply_text('start!', quote=True)


# mod commands
@restricted
def cmd_ban(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        context.bot.kick_chat_member(replied.chat_id, replied.from_user.id)
        reply(update.message, context.bot, 'User banned!')


@restricted
def cmd_unban(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        context.bot.unban_chat_member(replied.chat_id, replied.from_user.id)


@restricted
def cmd_kick(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        context.bot.kick_chat_member(replied.chat_id, replied.from_user.id)
        context.bot.unban_chat_member(replied.chat_id, replied.from_user.id)
        reply(update.message, context.bot, 'User kicked!')


@restricted
def cmd_mute(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        context.bot.restrict_chat_member(replied.chat_id, replied.from_user.id, ChatPermissions())
        reply(update.message, context.bot, 'User muted!')


@restricted
def cmd_unmute(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        context.bot.restrict_chat_member(replied.chat_id, replied.from_user.id,
                                         ChatPermissions(True, True, True, True, True, True, True, True))


def main():
    updater = Updater(config.BOT_TOKEN, use_context=True)
    updater.dispatcher.add_handler(CommandHandler('start', cmd_start))
    updater.dispatcher.add_handler(CommandHandler('id', cmd_id))
    updater.dispatcher.add_handler(CommandHandler('ban', cmd_ban))
    updater.dispatcher.add_handler(CommandHandler('unban', cmd_unban))
    updater.dispatcher.add_handler(CommandHandler('kick', cmd_kick))
    updater.dispatcher.add_handler(CommandHandler('mute', cmd_mute))
    updater.dispatcher.add_handler(CommandHandler('unmute', cmd_unmute))
    # updater.dispatcher.add_handler()

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
