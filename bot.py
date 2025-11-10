import logging
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ConversationHandler
from datetime import datetime

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

ADMIN_ID = 1012195906
DATA_FILE = 'taxi_data.json'
ADD_CAR, TAKE_CAR, UPLOAD_MEDIA = range(3)
admin_ids = [ADMIN_ID]

def load_data():
    global admin_ids
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            cars = {int(k): v for k, v in data.get('cars', {}).items()}
            for car in cars.values():
                if car['shift_start']:
                    car['shift_start'] = datetime.fromisoformat(car['shift_start'])
            shifts = data.get('shifts', [])
            for shift in shifts:
                shift['start_time'] = datetime.fromisoformat(shift['start_time'])
            admin_ids = data.get('admins', [ADMIN_ID])
            return cars, shifts
    return {}, []

def save_data():
    data = {
        'cars': {k: {**v, 'shift_start': v['shift_start'].isoformat() if v['shift_start'] else None} for k, v in cars.items()},
        'shifts': [{**s, 'start_time': s['start_time'].isoformat()} for s in shifts],
        'admins': admin_ids
    }
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

cars, shifts = load_data()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in admin_ids:
        await update.message.reply_text(
            'Админ-панель:\n'
            '/addcar - Добавить машину\n'
            '/cars - Список машин\n'
            '/active - Активные смены\n'
            '/history - История смен\n'
            '/addadmin - Добавить админа\n'
            '/admins - Список админов'
        )
    else:
        await update.message.reply_text(
            'Водитель:\n'
            '/takecar - Взять машину\n'
            '/endshift - Завершить смену\n'
            '/cars - Список машин'
        )

async def add_car_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in admin_ids:
        await update.message.reply_text('Доступ запрещен.')
        return ConversationHandler.END
    await update.message.reply_text('Введите модель и номер машины (например: Toyota Camry А123БВ)')
    return ADD_CAR

async def add_car_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    car_id = len(cars) + 1
    cars[car_id] = {'info': update.message.text, 'driver': None, 'shift_start': None}
    save_data()
    await update.message.reply_text(f'Машина #{car_id} добавлена: {update.message.text}')
    return ConversationHandler.END

async def list_cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not cars:
        await update.message.reply_text('Нет машин в таксопарке.')
        return
    
    msg = 'Машины:\n'
    for car_id, car in cars.items():
        status = f"Занята: {car['driver']}" if car['driver'] else "Свободна"
        msg += f"#{car_id} {car['info']} - {status}\n"
    await update.message.reply_text(msg)

async def take_car_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    free_cars = {cid: c for cid, c in cars.items() if not c['driver']}
    if not free_cars:
        await update.message.reply_text('Нет свободных машин.')
        return ConversationHandler.END
    
    keyboard = [[InlineKeyboardButton(f"#{cid} {c['info']}", callback_data=f"car_{cid}")] for cid, c in free_cars.items()]
    await update.message.reply_text('Выберите машину:', reply_markup=InlineKeyboardMarkup(keyboard))
    return TAKE_CAR

async def take_car_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    car_id = int(query.data.split('_')[1])
    context.user_data['car_id'] = car_id
    
    await query.edit_message_text('Отправьте фото/видео состояния автомобиля (можно несколько). Когда закончите, отправьте /done')
    context.user_data['media'] = []
    return UPLOAD_MEDIA

async def upload_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data['media'].append(('photo', update.message.photo[-1].file_id))
        await update.message.reply_text(f"Фото {len(context.user_data['media'])} получено. Отправьте еще или /done")
    elif update.message.video:
        context.user_data['media'].append(('video', update.message.video.file_id))
        await update.message.reply_text(f"Видео {len(context.user_data['media'])} получено. Отправьте еще или /done")
    elif update.message.document:
        context.user_data['media'].append(('document', update.message.document.file_id))
        await update.message.reply_text(f"Файл {len(context.user_data['media'])} получен. Отправьте еще или /done")
    return UPLOAD_MEDIA

async def done_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    car_id = context.user_data['car_id']
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    cars[car_id]['driver'] = username
    cars[car_id]['shift_start'] = datetime.now()
    
    shift = {
        'driver_id': user_id,
        'driver_name': username,
        'car_id': car_id,
        'car_info': cars[car_id]['info'],
        'start_time': datetime.now(),
        'media': context.user_data['media']
    }
    shifts.append(shift)
    save_data()
    
    await update.message.reply_text(f"Смена начата! Машина #{car_id} {cars[car_id]['info']}")
    
    msg = f"🚗 Новая смена\nВодитель: @{username}\nМашина: #{car_id} {cars[car_id]['info']}\nВремя: {shift['start_time'].strftime('%H:%M %d.%m.%Y')}"
    for admin_id in admin_ids:
        await context.bot.send_message(admin_id, msg)
        for media_type, file_id in context.user_data['media']:
            if media_type == 'photo':
                await context.bot.send_photo(admin_id, file_id)
            elif media_type == 'video':
                await context.bot.send_video(admin_id, file_id)
            else:
                await context.bot.send_document(admin_id, file_id)
    
    return ConversationHandler.END

async def end_shift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    car_id = None
    for cid, car in cars.items():
        if car['driver'] == username:
            car_id = cid
            break
    
    if not car_id:
        await update.message.reply_text('У вас нет активной смены.')
        return
    
    cars[car_id]['driver'] = None
    cars[car_id]['shift_start'] = None
    save_data()
    
    await update.message.reply_text(f"Смена завершена. Машина #{car_id} освобождена.")
    for admin_id in admin_ids:
        await context.bot.send_message(admin_id, f"✅ Смена завершена\nВодитель: @{username}\nМашина: #{car_id}")

async def active_shifts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in admin_ids:
        await update.message.reply_text('Доступ запрещен.')
        return
    
    active = {cid: c for cid, c in cars.items() if c['driver']}
    if not active:
        await update.message.reply_text('Нет активных смен.')
        return
    
    msg = '🚗 Активные смены:\n'
    for cid, car in active.items():
        duration = datetime.now() - car['shift_start']
        hours = int(duration.total_seconds() // 3600)
        msg += f"#{cid} {car['info']}\nВодитель: @{car['driver']}\nВремя: {hours}ч\n\n"
    await update.message.reply_text(msg)

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in admin_ids:
        await update.message.reply_text('Доступ запрещен.')
        return
    
    if not shifts:
        await update.message.reply_text('Нет истории смен.')
        return
    
    years = sorted(set(s['start_time'].year for s in shifts), reverse=True)
    keyboard = [[InlineKeyboardButton(str(year), callback_data=f"year_{year}")] for year in years]
    await update.message.reply_text('📋 Выберите год:', reply_markup=InlineKeyboardMarkup(keyboard))

async def history_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    year = int(query.data.split('_')[1])
    
    year_shifts = [s for s in shifts if s['start_time'].year == year]
    months = sorted(set(s['start_time'].month for s in year_shifts), reverse=True)
    
    month_names = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
    keyboard = [[InlineKeyboardButton(f"{month_names[m-1]} {year}", callback_data=f"month_{year}_{m}")] for m in months]
    await query.edit_message_text('📅 Выберите месяц:', reply_markup=InlineKeyboardMarkup(keyboard))

async def history_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, year, month = query.data.split('_')
    year, month = int(year), int(month)
    
    month_shifts = [s for s in shifts if s['start_time'].year == year and s['start_time'].month == month]
    days = sorted(set(s['start_time'].day for s in month_shifts), reverse=True)
    
    keyboard = [[InlineKeyboardButton(f"{day:02d}.{month:02d}.{year}", callback_data=f"day_{year}_{month}_{day}")] for day in days]
    await query.edit_message_text('📆 Выберите день:', reply_markup=InlineKeyboardMarkup(keyboard))

async def history_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, year, month, day = query.data.split('_')
    year, month, day = int(year), int(month), int(day)
    
    day_shifts = [(i, s) for i, s in enumerate(shifts) if s['start_time'].year == year and s['start_time'].month == month and s['start_time'].day == day]
    
    keyboard = [[InlineKeyboardButton(
        f"{s['start_time'].strftime('%H:%M')} - @{s['driver_name']} - #{s['car_id']} {s['car_info']}", 
        callback_data=f"shift_{idx}"
    )] for idx, s in day_shifts]
    
    await query.edit_message_text(f'📋 Смены за {day:02d}.{month:02d}.{year} ({len(day_shifts)} шт.):', reply_markup=InlineKeyboardMarkup(keyboard))

async def history_shift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    shift_idx = int(query.data.split('_')[1])
    s = shifts[shift_idx]
    
    msg = f"🚗 {s['start_time'].strftime('%d.%m.%Y %H:%M')}\n@{s['driver_name']}\nМашина: #{s['car_id']} {s['car_info']}"
    await query.edit_message_text(msg)
    
    for media_type, file_id in s['media']:
        if media_type == 'photo':
            await context.bot.send_photo(query.message.chat_id, file_id)
        elif media_type == 'video':
            await context.bot.send_video(query.message.chat_id, file_id)
        else:
            await context.bot.send_document(query.message.chat_id, file_id)

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in admin_ids:
        await update.message.reply_text('Доступ запрещен.')
        return
    
    if not context.args:
        await update.message.reply_text('Использование: /addadmin <user_id>')
        return
    
    new_admin_id = int(context.args[0])
    if new_admin_id not in admin_ids:
        admin_ids.append(new_admin_id)
        save_data()
        await update.message.reply_text(f'Админ {new_admin_id} добавлен.')
    else:
        await update.message.reply_text('Уже является админом.')

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in admin_ids:
        await update.message.reply_text('Доступ запрещен.')
        return
    
    await update.message.reply_text(f'Админы: {", ".join(map(str, admin_ids))}')

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Отменено.')
    return ConversationHandler.END

async def post_init(app: Application):
    driver_commands = [
        ('start', 'Главное меню'),
        ('takecar', 'Взять машину на смену'),
        ('endshift', 'Завершить смену'),
        ('cars', 'Список машин'),
        ('cancel', 'Отменить действие')
    ]
    
    admin_commands = driver_commands + [
        ('addcar', 'Добавить машину'),
        ('active', 'Активные смены'),
        ('history', 'История смен'),
        ('addadmin', 'Добавить админа'),
        ('admins', 'Список админов')
    ]
    
    for admin_id in admin_ids:
        await app.bot.set_my_commands(admin_commands, scope={'type': 'chat', 'chat_id': admin_id})
    
    await app.bot.set_my_commands(driver_commands)

def main():
    app = Application.builder().token("8449289280:AAHPap4CYO_nXBixXCAPaHfTJvdNNA8jEYE").post_init(post_init).build()
    
    add_car_conv = ConversationHandler(
        entry_points=[CommandHandler('addcar', add_car_start)],
        states={ADD_CAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_car_finish)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    take_car_conv = ConversationHandler(
        entry_points=[CommandHandler('takecar', take_car_start)],
        states={
            TAKE_CAR: [CallbackQueryHandler(take_car_selected)],
            UPLOAD_MEDIA: [
                MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, upload_media),
                CommandHandler('done', done_upload)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(add_car_conv)
    app.add_handler(take_car_conv)
    app.add_handler(CommandHandler('cars', list_cars))
    app.add_handler(CommandHandler('endshift', end_shift))
    app.add_handler(CommandHandler('active', active_shifts))
    app.add_handler(CommandHandler('history', history))
    app.add_handler(CallbackQueryHandler(history_year, pattern='^year_'))
    app.add_handler(CallbackQueryHandler(history_month, pattern='^month_'))
    app.add_handler(CallbackQueryHandler(history_day, pattern='^day_'))
    app.add_handler(CallbackQueryHandler(history_shift, pattern='^shift_'))
    app.add_handler(CommandHandler('addadmin', add_admin))
    app.add_handler(CommandHandler('admins', list_admins))
    
    app.run_polling()

if __name__ == '__main__':
    main()
