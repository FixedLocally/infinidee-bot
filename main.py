# Intended to be used in @InfiniDee only
import collections
import json
import logging
# import random
import re
import time
from functools import wraps

import mysql.connector
from telegram import Update, Message, Bot, ChatPermissions, MessageEntity
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, CallbackContext, DispatcherHandlerStop)

import config
from models import *

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
admin_cache = {}
cache_timeouts = {}
db_conn = None
auto_responders = {}  # {gid: {trigger1: response1, ...}, ...}
group_settings_cache = {}  # {gid: row}
message_time_log = {}  # {gid: {uid: deque}}


def init_db():
    global db_conn
    db_conn = mysql.connector.connect(
        host=config.DB_HOST,
        user=config.DB_USER,
        passwd=config.DB_PASS,
        database=config.DB_NAME,
        pool_size=4,
        pool_name="infinidee",
        auth_plugin='mysql_native_password',
        # charset='utf8mb4'
    )
    return db_conn


def get_cursor():
    global db_conn
    try:
        return db_conn.cursor()
    except:
        # reconnect your cursor as you did in __init__ or wherever
        init_db()
    return db_conn.cursor()


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
        if chat_id in group_settings_cache:
            result = group_settings_cache[chat_id]
            if result is not None:
                welcome = result.welcome
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
    if message is None:
        return
    # anti-spam
    if chat_id in group_settings_cache:
        threshold = group_settings_cache[chat_id].flood_threshold
        action = group_settings_cache[chat_id].flood_action
        sender = message.from_user.id
        group_msg_log = {}
        try:
            group_msg_log = message_time_log[chat_id]
        except KeyError:
            message_time_log[chat_id] = group_msg_log
        user_deque = collections.deque(maxlen=11)
        try:
            user_deque = group_msg_log[sender]
        except KeyError:
            group_msg_log[sender] = user_deque
        now = time.time()
        user_deque.append((now, message.message_id))
        if len(user_deque) > threshold:
            dur = now - user_deque[len(user_deque) - 1 - threshold][0]
            if dur < 5:
                # threshold messages in 5 secs, action
                if action == 'mute':
                    context.bot.restrict_chat_member(chat_id, sender, ChatPermissions())
                    reply(update.message, context.bot, f'[{message.from_user.first_name}](tg://user?id={sender}) () is flooding, muting!', parse_mode="markdown")
                    logger.log(logging.INFO, f'{sender} sent {threshold} messages in {dur} secs, muting!')
                elif action == 'kick':
                    context.bot.kick_chat_member(chat_id, sender)
                    context.bot.unban_chat_member(chat_id, sender)
                    reply(update.message, context.bot, f'[{message.from_user.first_name}](tg://user?id={sender}) () is flooding, kicking!', parse_mode="markdown")
                    logger.log(logging.INFO, f'{sender} sent {threshold} messages in {dur} secs, kicking!')
                elif action == 'ban':
                    context.bot.kick_chat_member(chat_id, sender)
                    reply(update.message, context.bot, f'[{message.from_user.first_name}](tg://user?id={sender}) () is flooding, banning!', parse_mode="markdown")
                    logger.log(logging.INFO, f'{sender} sent {threshold} messages in {dur} secs, banning!')
                items = list(user_deque)[:-1 - threshold:-1]
                for item in items:
                    context.bot.delete_message(chat_id, item[1])
    # auto responder
    reply_message = update.effective_message.reply_to_message or message
    msg = message.text
    if msg is None or len(msg) == 0:
        return
    msg = msg.lower()
    try:
        responders = auto_responders[chat_id][msg]
    except KeyError:
        return
    if responders is not None:
        response = responders[0]
        msg_type = response['msg_type']
        msg_text = response['msg_text']
        if msg_type == 'text':
            if response['entities'] is not None:
                msg_text_backup = msg_text
                for i in reversed(response['entities']):
                    segment = msg_text_backup[i[1]:i[1]+i[2]]
                    if i[0] == 'text_mention':
                        msg_text = msg_text_backup[:i[1]] + f'[{segment}](tg://user?id={i[3]})' + msg_text[i[1]+i[2]:]
                    elif i[0] == 'text_link':
                        msg_text = msg_text_backup[:i[1]] + f'[{segment}]({i[3]})' + msg_text[i[1]+i[2]:]
                    elif i[0] == 'italic':
                        msg_text = msg_text_backup[:i[1]] + f'_{segment}_' + msg_text[i[1]+i[2]:]
                    elif i[0] == 'bold':
                        msg_text = msg_text_backup[:i[1]] + f'*{segment}*' + msg_text[i[1]+i[2]:]
                    elif i[0] == 'code' or i[0] == 'pre':
                        if segment.find('\n') >= 0:
                            msg_text = msg_text_backup[:i[1]] + f'```{segment}```' + msg_text[i[1]+i[2]:]
                        else:
                            msg_text = msg_text_backup[:i[1]] + f'`{segment}`' + msg_text[i[1]+i[2]:]
            reply(reply_message, context.bot, msg_text, parse_mode="markdown")
        elif msg_type == 'sticker':
            context.bot.send_sticker(chat_id, msg_text, reply_to_message_id=reply_message.message_id)
        elif msg_type == 'photo':
            context.bot.send_photo(chat_id, msg_text, reply_to_message_id=reply_message.message_id)
        elif msg_type == 'gif':
            context.bot.send_animation(chat_id, msg_text, reply_to_message_id=reply_message.message_id)
        elif msg_type == 'voice':
            context.bot.send_voice(chat_id, msg_text, reply_to_message_id=reply_message.message_id)
        elif msg_type == 'audio':
            context.bot.send_audio(chat_id, msg_text, reply_to_message_id=reply_message.message_id)

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
    db_cursor = get_cursor()
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
    db_cursor.execute("SELECT content, msg_id from bulletin where gid=%s and expires>unix_timestamp() ORDER BY id",
                      [chat_id])
    result = db_cursor.fetchall()
    bulletin = '佈告版：\n'
    i = 1
    for x in result:
        if not isinstance(x[0], str):
            x[0] = str(x[0], encoding="utf8")
        bulletin += f'{i}. ['
        bulletin += x[0]\
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
    if update.message.reply_to_message:
        print(update.message.reply_to_message)
        entities = update.message.reply_to_message.parse_entities()
        for i in entities:
            print("=== start entity ===")
            entity: MessageEntity = i
            print(entity.type)
            print(entity.length)
            print(entity.to_json())
            # Message.de_json()
            print(entities[i])
            print(len(entities[i]))


# mod commands
@restricted
def cmd_ban(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        context.bot.kick_chat_member(replied.chat_id, replied.from_user.id)
        reply(update.message, context.bot, '已封鎖用戶！谷務：https://t.me/joinchat/FzCcTBPjQs9uYJgYm3oeYQ', disable_link_preview=True)
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
        reply(update.message, context.bot, '已移除用戶！谷務：https://t.me/joinchat/FzCcTBPjQs9uYJgYm3oeYQ', disable_link_preview=True)
        logger.log(logging.INFO, f'{update.effective_user.id} has used /kick against {replied.from_user.id}')


@restricted
def cmd_mute(update: Update, context: CallbackContext):
    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        context.bot.restrict_chat_member(replied.chat_id, replied.from_user.id, ChatPermissions())
        reply(update.message, context.bot, '已將用戶禁言！谷務：https://t.me/joinchat/FzCcTBPjQs9uYJgYm3oeYQ', disable_link_preview=True)
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
    group_settings_cache[chat_id].welcome = " ".join(msg[1::])
    args = [chat_id, group_settings_cache[chat_id].welcome, group_settings_cache[chat_id].flood_threshold,
            group_settings_cache[chat_id].flood_action]
    db_cursor = get_cursor()
    db_cursor.execute("REPLACE INTO group_settings (gid, welcome, flood_threshold, flood_action) VALUES (%s, %s, %s, %s)",
                      args)
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
        # see if its an image/gif/voice note/sticker
        if response.sticker:
            # is voice note
            msg_type = 'sticker'
            msg_text = response.sticker.file_id
        if response.voice:
            # is voice note
            msg_type = 'voice'
            msg_text = response.voice.file_id
        if response.audio:
            # is voice note
            msg_type = 'audio'
            msg_text = response.audio.file_id
        if response.photo:
            # is voice note
            msg_type = 'photo'
            msg_text = response.photo[0].file_id
        if response.document and response.document.mime_type == 'video/mp4':
            # gif
            msg_type = 'gif'
            msg_text = response.document.file_id
        # entities
        entities = update.message.reply_to_message.parse_entities()
        stored_entities_list = []  # [[type, start, offset, target]]
        emoji_positions = list(map(is_emoji, msg_text))
        offsets = [0]
        for i in emoji_positions:
            offsets.append(1 + i + offsets[len(offsets) - 1])
        for i in entities:
            entity: MessageEntity = i
            e_type = entity.type
            offset_adjustment = entity.offset - offsets.index(entity.offset)
            if e_type == 'text_link':
                stored_entities_list.append([e_type, entity.offset - offset_adjustment, len(entities[i].rstrip()), entity.url])
            elif e_type == 'text_mention':
                stored_entities_list.append([e_type, entity.offset - offset_adjustment, len(entities[i].rstrip()), entity.user.id])
            else:
                stored_entities_list.append([e_type, entity.offset - offset_adjustment, len(entities[i].rstrip()), ""])
        stored_entities = json.dumps(stored_entities_list)
        add_response_trigger(chat_id, msg_type, msg_text, trigger, stored_entities)
        db_cursor = get_cursor()
        db_cursor.execute("INSERT INTO auto_response (gid, msg_type, msg_text, `trigger`, entities) VALUES (%s, %s, %s, %s, %s)",
                          [chat_id, msg_type, msg_text, trigger, stored_entities])
        db_conn.commit()
        reply(update.message, context.bot, "Auto responder set")


@restricted
def cmd_link(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    link = context.bot.export_chat_invite_link(chat_id)
    reply(update.effective_message, context.bot, link, disable_web_page_preview=True)


@restricted
def cmd_revoke(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    context.bot.export_chat_invite_link(chat_id)
    reply(update.effective_message, context.bot, "Ok")


def cmd_schedule(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    db_cursor = get_cursor()
    if user_id in config.SCHEDULE_ADMIN:
        if len(context.args) > 2:
            # add to schedule
            args = update.message.text.split(" ", 3)
            start_date = parse_date(args[1])
            end_date = parse_date(args[2])
            event = args[3]
            if start_date > end_date:
                reply(update.message, context.bot, 'Error: event ends before starting')
                return
            db_cursor.execute("INSERT INTO schedule (start_time, end_time, event) VALUES (%s, %s, %s)",
                              [start_date, end_date, event])
            db_conn.commit()
            insert_id = db_cursor.lastrowid
            reply(update.message, context.bot, f'Inserted as record {insert_id}')
            # not ended and will start within a week
    db_cursor.execute("SELECT id, start_time, end_time, event FROM schedule WHERE "
                      "end_time>unix_timestamp() and start_time<unix_timestamp()+604800 "
                      "ORDER BY start_time")
    msg = '香港人日程：\n'
    while True:
        row = db_cursor.fetchone()
        if row is None:
            break
        msg += f'{row[0]}. {long_date(row[1])} - '
        if same_day(row[1], row[2]):
            msg += short_date(row[2])
        else:
            msg += long_date(row[2])
        msg += '\n'
        msg += row[3]
        msg += '\n\n'
    reply(update.message, context.bot, msg)


def add_response_trigger(chat_id, msg_type, msg_text, trigger, stored_entities):
    responders = {}
    if not isinstance(trigger, str):
        trigger = str(trigger, encoding="utf8")
    try:
        responders = auto_responders[chat_id]
    except KeyError:
        auto_responders[chat_id] = responders
    if trigger not in responders:
        responders[trigger] = []
    new_trigger = {'msg_type': msg_type, 'msg_text': msg_text, 'entities': None}
    if stored_entities is not None:
        new_trigger['entities'] = json.loads(stored_entities)
    responders[trigger].append(new_trigger)


def is_emoji(c):
    return len(re.findall(u'[\U0001f300-\U0001fa95]', c[0]))


def parse_date(s):  # yyyymmddhhmm[ss]
    try:
        year = int(s[0:4])
        month = int(s[4:6])
        day = int(s[6:8])
        hour = int(s[8:10])
        minute = int(s[10:12])
        second = int(s[12:14] or '0')
        return time.mktime((year, month, day, hour, minute, second, 1, 48, 0))
    except ValueError:
        return -1


def long_date(t):
    tm = time.localtime(t)
    return f'{tm.tm_year}-{tm.tm_mon}-{tm.tm_mday} {tm.tm_hour}:{tm.tm_min}'


def short_date(t):
    tm = time.localtime(t)
    return f'{tm.tm_hour}:{tm.tm_min}'


def same_day(t1, t2):
    tm1 = time.localtime(t1)
    tm2 = time.localtime(t2)
    return tm1.tm_year == tm2.tm_year and tm1.tm_mon == tm2.tm_mon and tm1.tm_mday == tm2.tm_mday


def main():
    # auto responders
    global db_conn
    db_conn = init_db()
    db_cursor = get_cursor()
    db_cursor.execute("SELECT gid, msg_type, msg_text, `trigger`, entities FROM auto_response")
    while True:
        row = db_cursor.fetchone()
        if row is None:
            break
        add_response_trigger(*row)

    # group settings
    db_cursor.execute("SELECT gid, welcome, flood_threshold, flood_action FROM group_settings")
    while True:
        row = db_cursor.fetchone()
        if row is None:
            break
        group_settings_cache[row[0]] = GroupSettings(row[1:])

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
    updater.dispatcher.add_handler(CommandHandler('schedule', cmd_schedule))
    updater.dispatcher.add_handler(CommandHandler('link', cmd_link))
    updater.dispatcher.add_handler(CommandHandler('revoke', cmd_revoke))
    updater.dispatcher.add_handler(MessageHandler(Filters.status_update.new_chat_members, on_member_join))
    updater.dispatcher.add_handler(MessageHandler(None, on_message))

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
