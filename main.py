# Intended to be used in @InfiniDee only

import config
import mysql.connector
import logging
import time
from functools import wraps
from telegram import Update, Message, Bot, ChatPermissions, ChatMember
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, CallbackContext, DispatcherHandlerStop)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
admin_cache = {}
cache_timeouts = {}
db_conn = mysql.connector.connect(
    host=config.DB_HOST,
    user=config.DB_USER,
    passwd=config.DB_PASS,
    database=config.DB_NAME,
    pool_size=4,
    pool_name="infinidee",
    auth_plugin='mysql_native_password',
    charset='utf8mb4'
)
db_cursor = db_conn.cursor()
auto_responders = {}  # dict of dict {gid: {trigger1: response1, ...}, ...}


def get_admin_ids(bot, chat_id):
    now = time.time()
    try:
        cache = admin_cache[chat_id]
        timeout = cache_timeouts[chat_id]
        if timeout > now:
            return cache
        else:
            raise KeyError
    except KeyError:
        admins = [admin.user.id for admin in bot.get_chat_administrators(chat_id)]
        admin_cache[chat_id] = admins
        cache_timeouts[chat_id] = now + 3600
        return admins


def restricted(func):
    @wraps(func)
    def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        if user_id != config.OWNER_ID:
            # see if the user is a chat admin
            if user_id not in get_admin_ids(context.bot, chat_id):
                logger.log(logging.INFO, "Unauthorized access to /{} denied for {}.".format(func.__name__, user_id))
                return
        return func(update, context, *args, **kwargs)

    return wrapped


def reply(message: Message, bot: Bot, text, parse_mode="html", **kwargs):
    bot.send_message(message.chat_id, text, reply_to_message_id=message.message_id, parse_mode=parse_mode, **kwargs)


def on_member_join(update: Update, context: CallbackContext):
    if update.message.new_chat_members is not None:
        chat = update.effective_chat
        chat_id = chat.id
        db_cursor.execute("SELECT welcome FROM group_settings where gid=%s", [chat_id])
        result = db_cursor.fetchall()
        if len(result) > 0:
            welcome = result[0][0]
            for user in update.message.new_chat_members:
                msg = welcome\
                    .replace('{{lastName}}', user.last_name or "")\
                    .replace('{{firstName}}', user.first_name or "")\
                    .replace('{{groupName}}', chat.title or "")\
                    .replace('{{uid}}', str(user.id or 0))
                reply(update.message, context.bot, msg)
        raise DispatcherHandlerStop


def on_message(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    message = update.effective_message
    msg = message.text
    if msg is None or len(msg) == 0:
        return
    msg = msg.lower()
    response = None
    try:
        response = auto_responders[chat_id][msg]
    except KeyError:
        return
    if response is not None:
        msg_type = response['msg_type']
        msg_text = response['msg_text']
        if msg_type == 'text':
            reply(update.message, context.bot, msg_text)
        elif msg_type == 'photo':
            context.bot.send_photo(chat_id, msg_text, reply_to_message_id=message.message_id)
        elif msg_type == 'gif':
            context.bot.send_animation(chat_id, msg_text, reply_to_message_id=message.message_id)
        elif msg_type == 'voice':
            context.bot.send_voice(chat_id, msg_text, reply_to_message_id=message.message_id)

        raise DispatcherHandlerStop


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


def cmd_bulletin(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if update.message.reply_to_message:
        if user_id in get_admin_ids(context.bot, chat_id):
            # add message to bulletin
            text = update.message.text.split(' ')
            time_limit = 604800  # 1 week
            if len(text) > 1:
                try:
                    time_limit = int(text[1])
                except ValueError:
                    reply(update.message, context.bot, f'{text[1]} is not a valid number')
                    return
            db_cursor.execute("SELECT 1 from bulletin WHERE gid=%s and msg_id=%s", [chat_id, update.message.reply_to_message.message_id])
            result = db_cursor.fetchall()
            if len(result) > 0:
                db_cursor.execute("DELETE FROM bulletin WHERE gid=%s and msg_id=%s", [chat_id, update.message.reply_to_message.message_id])
                db_conn.commit()
                reply(update.message, context.bot, "Removed from bulletin")
            else:
                db_cursor.execute("INSERT INTO bulletin (gid, content, expires, msg_id) values (%s, %s, "
                                  "%s + unix_timestamp(), %s)",
                                  [chat_id, update.message.reply_to_message.text + ' ~' + update.message.reply_to_message.from_user.first_name, time_limit, update.message.reply_to_message.message_id])
                db_conn.commit()
                reply(update.message, context.bot, "Added to bulletin")
            return
    db_cursor.execute("SELECT content, msg_id from bulletin where gid=%s and expires>unix_timestamp() ORDER BY id", [chat_id])
    result = db_cursor.fetchall()
    bulletin = '佈告版：\n'
    i = 1
    for x in result:
        bulletin += f'{i}. ['
        bulletin += str(x[0], encoding="utf8")\
            .replace('`', '\\`')\
            .replace('[', '\\[')\
            .replace(']', '\\]')\
            .replace('(', '\\(')\
            .replace(')', '\\)')\
            .replace('*', '\\*')\
            .replace('_', '\\_')
        # -1001352189020 -> 1352189020
        cid = -chat_id - 1000000000000
        bulletin += f'](https://t.me/c/{cid}/{x[1]})\n\n'
        i += 1
    if len(result) > 0:
        reply(update.message, context.bot, bulletin, parse_mode="markdown")


def cmd_log(update: Update, context: CallbackContext):
    print(update.message.reply_to_message)


# mod commands
@restricted
def cmd_ban(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        context.bot.kick_chat_member(replied.chat_id, replied.from_user.id)
        reply(update.message, context.bot, 'User banned!')
        logger.log(logging.INFO, f'{update.effective_user.id} has used /ban against {replied.from_user.id}')


@restricted
def cmd_unban(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        context.bot.unban_chat_member(replied.chat_id, replied.from_user.id)
        logger.log(logging.INFO, f'{update.effective_user.id} has used /unban against {replied.from_user.id}')


@restricted
def cmd_kick(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        context.bot.kick_chat_member(replied.chat_id, replied.from_user.id)
        context.bot.unban_chat_member(replied.chat_id, replied.from_user.id)
        reply(update.message, context.bot, 'User kicked!')
        logger.log(logging.INFO, f'{update.effective_user.id} has used /kick against {replied.from_user.id}')


@restricted
def cmd_mute(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        context.bot.restrict_chat_member(replied.chat_id, replied.from_user.id, ChatPermissions())
        reply(update.message, context.bot, 'User muted!')
        logger.log(logging.INFO, f'{update.effective_user.id} has used /mute against {replied.from_user.id}')


@restricted
def cmd_unmute(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        context.bot.restrict_chat_member(replied.chat_id, replied.from_user.id,
                                         ChatPermissions(True, True, True, True, True, True, True, True))
        logger.log(logging.INFO, f'{update.effective_user.id} has used /unmute against {replied.from_user.id}')


@restricted
def cmd_welcome(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    msg = update.message.text.split(" ")
    db_cursor.execute("REPLACE INTO group_settings (gid, welcome) VALUES (%s, %s)", [chat_id, " ".join(msg[1::])])
    db_conn.commit()
    reply(update.message, context.bot, "Welcome message set")


@restricted
def cmd_respond(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if update.message.reply_to_message:
        trigger = " ".join(context.args).lower()
        response = update.message.reply_to_message
        msg_type = 'text'
        msg_text = response.text
        # see if its an image/gif/voice note
        if response.voice:
            # is voice note
            msg_type = 'voice'
            msg_text = response.voice.file_id
        if response.photo:
            # is voice note
            msg_type = 'photo'
            msg_text = response.photo[0].file_id
        if response.document and response.document.mime_type == 'video/mp4':
            # gif
            msg_type = 'gif'
            msg_text = response.document.file_id
        add_response_trigger(chat_id, msg_type, msg_text, trigger)
        db_cursor.execute("INSERT INTO auto_response (gid, msg_type, msg_text, `trigger`) VALUES (%s, %s, %s, %s)",
                          [chat_id, msg_type, msg_text, trigger])
        db_conn.commit()
        reply(update.message, context.bot, "Auto responder set")


def add_response_trigger(chat_id, msg_type, msg_text, trigger):
    responders = {}
    try:
        responders = auto_responders[chat_id]
    except KeyError:
        pass
    responders[trigger] = {}
    responders[trigger]['msg_type'] = msg_type
    responders[trigger]['msg_text'] = msg_text
    auto_responders[chat_id] = responders


def main():
    # auto responders
    db_cursor.execute("SELECT gid, msg_type, msg_text, `trigger` FROM auto_response")
    while True:
        row = db_cursor.fetchone()
        if row is None:
            break
        add_response_trigger(*row)

    # handlers
    updater = Updater(config.BOT_TOKEN, use_context=True)
    updater.dispatcher.add_handler(CommandHandler('start', cmd_start))
    updater.dispatcher.add_handler(CommandHandler('id', cmd_id))
    updater.dispatcher.add_handler(CommandHandler('ban', cmd_ban))
    updater.dispatcher.add_handler(CommandHandler('unban', cmd_unban))
    updater.dispatcher.add_handler(CommandHandler('kick', cmd_kick))
    updater.dispatcher.add_handler(CommandHandler('mute', cmd_mute))
    updater.dispatcher.add_handler(CommandHandler('unmute', cmd_unmute))
    updater.dispatcher.add_handler(CommandHandler('bulletin', cmd_bulletin))
    updater.dispatcher.add_handler(CommandHandler('welcome', cmd_welcome))
    updater.dispatcher.add_handler(CommandHandler('log', cmd_log))
    updater.dispatcher.add_handler(CommandHandler('respond', cmd_respond))
    updater.dispatcher.add_handler(MessageHandler(Filters.status_update.new_chat_members, on_member_join))
    updater.dispatcher.add_handler(MessageHandler(None, on_message))

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
