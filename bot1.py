import disnake
from disnake.ext import commands, tasks
from disnake import TextInputStyle
import json
import os
from datetime import datetime
import io
import re
import random
import string

intents = disnake.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Конфигурация для разных серверов
SERVER_CONFIGS = {
    # Первый сервер (из main.py)
    1429544000188317831: {
        "static_channel_id": 1429831404379705474,
        "admin_role_ids": [1310673963000528949, 1223589384452833290, 1429544345463296000],
        "data_file": "rollback_data_server1.json"
    },
    # Второй сервер (из bot1.py)
    1003525677640851496: {
        "static_channel_id": 1429128623776075916,
        "admin_ids": [1381084245321056438, 427922282959077386, 300627668460634124, 773983223595139083, 415145467702280192],
        "data_file": "rollback_data.json"
    }
}

def get_server_config(guild_id):
    """Получает конфигурацию для сервера"""
    return SERVER_CONFIGS.get(guild_id)

def get_data_file(guild_id):
    """Получает файл данных для сервера"""
    config = get_server_config(guild_id)
    if config:
        return config.get("data_file", "rollback_data.json")
    return "rollback_data.json"

def load_data(guild_id):
    """Загружает данные для конкретного сервера"""
    data_file = get_data_file(guild_id)
    if os.path.exists(data_file):
        with open(data_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"lists": {}, "settings": {}}

def save_data(guild_id, data):
    """Сохраняет данные для конкретного сервера"""
    data_file = get_data_file(guild_id)
     directory = os.path.dirname(data_file)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_admin(member):
    """Проверяет, имеет ли пользователь права администратора"""
    if not member:
        return False
    
    config = get_server_config(member.guild.id)
    if not config:
        return False
    
    # Для первого сервера проверяем по ролям
    if member.guild.id == 1429544000188317831:
        try:
            member_role_ids = [role.id for role in member.roles]
            return any(role_id in config["admin_role_ids"] for role_id in member_role_ids)
        except:
            return False
    # Для второго сервера проверяем по ID пользователей
    elif member.guild.id == 1003525677640851496:
        try:
            return member.id in config["admin_ids"]
        except:
            return False
    
    return False

def generate_list_id():
    """Генерирует случайный ID из 5 символов"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))

def create_new_list(list_id, list_name, channel_id, created_by, guild_id):
    """Создает новый список для указанного сервера"""
    data = load_data(guild_id)
    config = get_server_config(guild_id)
    
    data["lists"][list_id] = {
        "id": list_id,
        "name": list_name,
        "channel_id": channel_id,  # Канал где создан список (с кнопками)
        "static_channel_id": config["static_channel_id"] if config else channel_id,
        "created_by": created_by,
        "guild_id": guild_id,
        "created_at": datetime.now().isoformat(),
        "participants": {},
        "rollbacks": {},
        "message_id": None,
        "status_message_id": None
    }
    save_data(guild_id, data)
    return data["lists"][list_id]

def get_list(list_id, guild_id):
    """Получает список по ID для указанного сервера"""
    data = load_data(guild_id)
    return data["lists"].get(list_id)

def remove_user_rollback(list_data, user_id):
    """Удаляет откат пользователя"""
    if user_id not in list_data["participants"]:
        return False
    
    # Удаляем все откаты пользователя
    rollbacks_to_remove = []
    for timestamp, rollback in list_data["rollbacks"].items():
        if rollback["user_id"] == user_id:
            rollbacks_to_remove.append(timestamp)
    
    for timestamp in rollbacks_to_remove:
        del list_data["rollbacks"][timestamp]
    
    # Сбрасываем статус отката
    list_data["participants"][user_id]["has_rollback"] = False
    
    return True

def clean_rollback_text(text):
    """Очищает текст отката от форматирования"""
    if not text:
        return ""
    
    # Удаляем HTML-теги
    clean_text = re.sub(r'<[^>]+>', '', text)
    
    # Убираем лишние пробелы
    clean_text = re.sub(r'\s+', ' ', clean_text)
    clean_text = clean_text.strip()
    
    return clean_text

async def update_status_message(list_data):
    """Обновляет сообщение со статусом откатов в СТАТИЧЕСКОМ канале"""
    try:
        config = get_server_config(list_data["guild_id"])
        if not config:
            return
            
        channel_id = config["static_channel_id"]  # Статический канал из конфига
        channel = bot.get_channel(channel_id)
        if not channel:
            return
        
        # Формируем содержимое сообщения
        total_participants = len(list_data['participants'])
        completed_rollbacks = sum(1 for p in list_data['participants'].values() if p['has_rollback'])
        
        message_content = f"📊 **СТАТУС ОТКАТОВ: {list_data['name']}**\n\n"
        message_content += f"📋 ID списка: `{list_data['id']}`\n"
        message_content += f"👥 Всего участников: **{total_participants}**\n"
        message_content += f"✅ Отправили откат: **{completed_rollbacks}** / **{total_participants}**\n"
        message_content += f"{'='*50}\n\n"
        
        if not list_data['participants']:
            message_content += "*Список участников пуст*\n"
        else:
            for user_id, participant in sorted(list_data['participants'].items(), key=lambda x: x[1]['registered_at']):
                status = "🟢" if participant['has_rollback'] else "🔴"
                username = participant['display_name']
                message_content += f"{status} **{username}**\n"
                
                if participant['has_rollback']:
                    user_rollback = None
                    for rollback in list_data['rollbacks'].values():
                        if rollback['user_id'] == user_id:
                            user_rollback = rollback
                            break
                    if user_rollback:
                        rollback_text = user_rollback['text']
                        if rollback_text:
                            rollback_preview = rollback_text[:150]
                            if len(rollback_text) > 150:
                                rollback_preview += "..."
                            message_content += f"  └ 📝 {rollback_preview}\n"
                message_content += "\n"
        
        # Проверяем, есть ли уже сообщение со статусом
        status_message_id = list_data.get("status_message_id")
        data = load_data(list_data["guild_id"])
        
        if status_message_id:
            try:
                status_message = await channel.fetch_message(status_message_id)
                await status_message.edit(content=message_content)
                return
            except:
                # Сообщение не найдено, создадим новое
                pass
        
        # Создаём новое сообщение
        new_message = await channel.send(message_content)
        list_data["status_message_id"] = new_message.id
        data["lists"][list_data["id"]] = list_data
        save_data(list_data["guild_id"], data)
        
    except Exception as e:
        print(f"Ошибка при обновлении статуса списка {list_data['id']}: {e}")

class CreateListModal(disnake.ui.Modal):
    def __init__(self, guild_id):
        self.guild_id = guild_id
        components = [
            disnake.ui.TextInput(
                label="Время",
                placeholder="Укажите время (например: 18:00)",
                custom_id="time",
                style=TextInputStyle.short,
                max_length=10,
                required=True
            ),
            disnake.ui.TextInput(
                label="Дата",
                placeholder="Укажите дату (например: 25.10.2025)",
                custom_id="date",
                style=TextInputStyle.short,
                max_length=20,
                required=True
            ),
            disnake.ui.TextInput(
                label="Название",
                placeholder="Название события",
                custom_id="name",
                style=TextInputStyle.short,
                max_length=50,
                required=True
            ),
            disnake.ui.TextInput(
                label="Сервер события",
                placeholder="Название сервера",
                custom_id="event_server",
                style=TextInputStyle.short,
                max_length=50,
                required=True
            )
        ]
        super().__init__(title="Создание нового списка", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        data = load_data(self.guild_id)
        time_value = inter.text_values["time"].strip()
        date_value = inter.text_values["date"].strip()
        name_value = inter.text_values["name"].strip()
        server_value = inter.text_values["event_server"].strip()
        
        # Генерируем уникальный 5-символьный ID
        list_id = generate_list_id()
        while list_id in data["lists"]:
            list_id = generate_list_id()
        
        # Создаём полное название
        full_name = f"{time_value} | {date_value} | {name_value} | {server_value}"
        
        # Используем канал, где вызвана команда - для списка с кнопками
        channel_id = inter.channel_id
        
        # Создаём список
        list_data = create_new_list(list_id, full_name, channel_id, str(inter.author.id), self.guild_id)
        
        config = get_server_config(self.guild_id)
        static_channel_mention = f"<#{config['static_channel_id']}>" if config else "не указан"
        
        await inter.response.send_message(
            f"✅ Список создан!\n"
            f"ID: `{list_id}`\n"
            f"Название: {full_name}\n"
            f"Канал с кнопками: {inter.channel.mention}\n"
            f"Статус откатов: {static_channel_mention}\n\n"
            f"Для регистрации участников используйте:\n"
            f"`/register_user list_id:{list_id} users:@участник1 @участник2`",
            ephemeral=True
        )
        
        # Создаем сообщения:
        # 1. Список с кнопками - в канале где вызвана команда
        await update_participants_message(inter.channel, list_data)
        # 2. Статус откатов - в статическом канале
        await update_status_message(list_data)

class RollbackModal(disnake.ui.Modal):
    def __init__(self, list_id, guild_id, has_existing_rollback=False):
        self.list_id = list_id
        self.guild_id = guild_id
        self.has_existing_rollback = has_existing_rollback
        
        placeholder = "Опишите подробно вашу идею или предложение..."
        if has_existing_rollback:
            placeholder = "Ваш старый откат будет заменен на новый..."
        
        components = [
            disnake.ui.TextInput(
                label="Ваш откат",
                placeholder=placeholder,
                custom_id="rollback_text",
                style=TextInputStyle.paragraph,
                max_length=2000,
                required=True
            )
        ]
        
        title = "Заменить откат" if has_existing_rollback else "Отправить откат"
        super().__init__(title=title, components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        list_data = get_list(self.list_id, self.guild_id)
        if not list_data:
            await inter.response.send_message("❌ Список не найден!", ephemeral=True)
            return
            
        user_id = str(inter.author.id)
        
        if user_id not in list_data["participants"]:
            await inter.response.send_message(
                "❌ Вы не зарегистрированы в этом списке! Обратитесь к администратору.",
                ephemeral=True
            )
            return
            
        rollback_text = inter.text_values["rollback_text"]
        
        # Очищаем текст от форматирования
        cleaned_text = clean_rollback_text(rollback_text)
        
        if not cleaned_text:
            await inter.response.send_message(
                "❌ Текст отката не может быть пустым! Пожалуйста, напишите ваш откат текстом, а не только ссылками.",
                ephemeral=True
            )
            return
        
        timestamp = datetime.now().isoformat()
        
        # Обновляем серверный никнейм участника
        server_nickname = inter.author.display_name
        list_data["participants"][user_id]["display_name"] = server_nickname
        
        # Удаляем старый откат, если он есть
        if self.has_existing_rollback:
            remove_user_rollback(list_data, user_id)
        
        # Добавляем новый откат
        list_data["rollbacks"][timestamp] = {
            "user_id": user_id,
            "user_name": server_nickname,
            "text": cleaned_text,
            "timestamp": timestamp
        }
        list_data["participants"][user_id]["has_rollback"] = True
        
        data = load_data(self.guild_id)
        data["lists"][self.list_id] = list_data
        save_data(self.guild_id, data)
        
        if self.has_existing_rollback:
            message = f"✅ Ваш откат в списке '{list_data['name']}' заменен на новый! Статус обновлен."
        else:
            message = f"✅ Ваш откат отправлен в список '{list_data['name']}'! Статус обновлен."
            
        await inter.response.send_message(message, ephemeral=True)
        
        # Обновляем оба сообщения:
        # 1. Список с кнопками - в канале списка
        channel = bot.get_channel(list_data["channel_id"])
        if channel:
            await update_participants_message(channel, list_data)
        # 2. Статус откатов - в статическом канале
        await update_status_message(list_data)

class DeleteRollbackView(disnake.ui.View):
    def __init__(self, list_id, guild_id):
        super().__init__(timeout=60)
        self.list_id = list_id
        self.guild_id = guild_id
    
    @disnake.ui.button(label="Да, удалить мой откат", style=disnake.ButtonStyle.danger)
    async def confirm_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        list_data = get_list(self.list_id, self.guild_id)
        if not list_data:
            await inter.response.send_message("❌ Список не найден!", ephemeral=True)
            return
            
        user_id = str(inter.author.id)
        
        if user_id not in list_data["participants"]:
            await inter.response.send_message("❌ Вы не зарегистрированы в этом списке!", ephemeral=True)
            return
            
        if not list_data["participants"][user_id]["has_rollback"]:
            await inter.response.send_message("❌ У вас нет отправленного отката!", ephemeral=True)
            return
        
        # Удаляем откат
        if remove_user_rollback(list_data, user_id):
            data = load_data(self.guild_id)
            data["lists"][self.list_id] = list_data
            save_data(self.guild_id, data)
            
            await inter.response.send_message(
                f"✅ Ваш откат удален из списка '{list_data['name']}'!", 
                ephemeral=True
            )
            
            # Обновляем сообщения
            channel = bot.get_channel(list_data["channel_id"])
            if channel:
                await update_participants_message(channel, list_data)
            await update_status_message(list_data)
        else:
            await inter.response.send_message("❌ Не удалось удалить откат!", ephemeral=True)
        
        # Удаляем кнопки после использования
        await inter.message.delete()
    
    @disnake.ui.button(label="Отмена", style=disnake.ButtonStyle.secondary)
    async def cancel_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_message("❌ Удаление отката отменено.", ephemeral=True)
        await inter.message.delete()

async def update_participants_message(channel, list_data):
    """Обновляет сообщение со списком участников и кнопками в канале списка"""
    if not list_data:
        return
    
    data = load_data(list_data["guild_id"])
    if list_data.get("message_id"):
        try:
            message = await channel.fetch_message(list_data["message_id"])
            embed = disnake.Embed(
                title=f"📋 {list_data['name']}",
                description=await generate_participants_list(list_data),
                color=0x2b2d31
            )
            embed.set_footer(text=f"ID: {list_data['id']} | Регистрация через администратора")
            
            # Создаем новое View каждый раз
            view = MainView(list_data["id"], list_data["guild_id"])
            await message.edit(embed=embed, view=view)
            return
        except:
            pass
    
    # Создаём новое сообщение
    embed = disnake.Embed(
        title=f"📋 {list_data['name']}",
        description=await generate_participants_list(list_data),
        color=0x2b2d31
    )
    embed.set_footer(text=f"ID: {list_data['id']} | Регистрация через администратора")
    
    # Создаем новое View
    view = MainView(list_data["id"], list_data["guild_id"])
    message = await channel.send(embed=embed, view=view)
    
    list_data["message_id"] = message.id
    data["lists"][list_data["id"]] = list_data
    save_data(list_data["guild_id"], data)

async def generate_participants_list(list_data):
    if not list_data or not list_data["participants"]:
        return "*Список участников пуст*"
    
    participants = list_data["participants"]
    sorted_participants = sorted(
        participants.items(), 
        key=lambda x: x[1]["registered_at"]
    )
    
    lines = []
    for user_id, info in sorted_participants:
        status = "✅" if info["has_rollback"] else "❌"
        mention = f"<@{user_id}>"
        lines.append(f"{status} {mention}")
    
    return "\n".join(lines)

class MainView(disnake.ui.View):
    def __init__(self, list_id, guild_id):
        super().__init__(timeout=None)
        self.list_id = list_id
        self.guild_id = guild_id
    
    @disnake.ui.button(label="Отправить откат", style=disnake.ButtonStyle.primary)  # БЕЗ custom_id
    async def rollback_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        list_data = get_list(self.list_id, self.guild_id)
        if not list_data:
            await inter.response.send_message("❌ Список не найден!", ephemeral=True)
            return
            
        user_id = str(inter.author.id)
        if user_id not in list_data["participants"]:
            await inter.response.send_message(
                "❌ Вы не зарегистрированы в этом списке! Обратитесь к администратору.",
                ephemeral=True
            )
            return
        
        # Проверяем, есть ли уже откат у пользователя
        has_existing_rollback = list_data["participants"][user_id]["has_rollback"]
        
        if has_existing_rollback:
            # Создаем отдельный класс для кнопок выбора
            class ChoiceView(disnake.ui.View):
                def __init__(self, list_id, guild_id):
                    super().__init__(timeout=60)
                    self.list_id = list_id
                    self.guild_id = guild_id
                
                @disnake.ui.button(label="Заменить откат", style=disnake.ButtonStyle.primary)
                async def replace_button(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
                    await interaction.response.send_modal(RollbackModal(self.list_id, self.guild_id, has_existing_rollback=True))
                
                @disnake.ui.button(label="Удалить откат", style=disnake.ButtonStyle.danger)
                async def delete_button(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
                    delete_view = DeleteRollbackView(self.list_id, self.guild_id)
                    await interaction.response.send_message(
                        "❓ Вы уверены, что хотите удалить свой откат?",
                        view=delete_view,
                        ephemeral=True
                    )
                
                @disnake.ui.button(label="Отмена", style=disnake.ButtonStyle.secondary)
                async def cancel_button(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
                    await interaction.response.send_message("❌ Действие отменено.", ephemeral=True)
            
            choice_view = ChoiceView(self.list_id, self.guild_id)
            
            await inter.response.send_message(
                "📝 У вас уже есть отправленный откат. Что вы хотите сделать?",
                view=choice_view,
                ephemeral=True
            )
        else:
            # Если отката нет, просто отправляем модальное окно
            await inter.response.send_modal(RollbackModal(self.list_id, self.guild_id, has_existing_rollback=False))
    
    @disnake.ui.button(label="Обновить список", style=disnake.ButtonStyle.secondary)  # Убрал custom_id
    async def refresh_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        list_data = get_list(self.list_id, self.guild_id)
        if not list_data:
            await inter.followup.send("❌ Список не найден!", ephemeral=True)
            return
            
        # Обновляем оба сообщения:
        # 1. Список с кнопками - в канале списка
        channel = bot.get_channel(list_data["channel_id"])
        if channel:
            await update_participants_message(channel, list_data)
        # 2. Статус откатов - в статическом канале
        await update_status_message(list_data)
        await inter.edit_original_response(content="✅ Оба списка обновлены!")

@bot.event
async def on_ready():
    print(f'Bot {bot.user} готов к работе!')
    print(f'Подключен к {len(bot.guilds)} серверам')
    print("Поддерживаемые серверы:")
    for guild_id, config in SERVER_CONFIGS.items():
        print(f"- Сервер {guild_id}: {config['data_file']}")
    
    # Убрал добавление persistent views - теперь View создаются при каждом обновлении
    print("✅ Бот запущен и готов к работе!")

@bot.slash_command(description="Создать новый список откатов")
async def create_list(inter: disnake.ApplicationCommandInteraction):
    if not is_admin(inter.author):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    await inter.response.send_modal(CreateListModal(inter.guild.id))

@bot.slash_command(description="Регистрировать пользователей в списке")
async def register_user(
    inter: disnake.ApplicationCommandInteraction,
    list_id: str = commands.Param(description="ID списка"),
    users: str = commands.Param(description="Пользователи через @ или ID через пробел")
):
    if not is_admin(inter.author):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    list_data = get_list(list_id, inter.guild.id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
    # Парсинг пользователей из строки
    user_mentions = re.findall(r'<@!?(\d+)>', users)
    user_ids = re.findall(r'\b(\d{17,19})\b', users)
    
    all_user_ids = list(set(user_mentions + user_ids))
    
    if not all_user_ids:
        await inter.response.send_message("❌ Не найдено ни одного валидного пользователя!", ephemeral=True)
        return
    
    registered_users = []
    already_registered = []
    
    for user_id in all_user_ids:
        try:
            # Получаем участника сервера для использования серверного никнейма
            member = inter.guild.get_member(int(user_id))
            if not member:
                # Если не нашли на сервере, пытаемся получить глобального пользователя
                member = await bot.fetch_user(int(user_id))
            
            server_nickname = member.display_name
            
            if user_id in list_data["participants"]:
                already_registered.append(server_nickname)
            else:
                list_data["participants"][user_id] = {
                    "display_name": server_nickname,
                    "has_rollback": False,
                    "registered_at": datetime.now().isoformat()
                }
                registered_users.append(server_nickname)
        except:
            continue
    
    if registered_users or already_registered:
        data = load_data(inter.guild.id)
        data["lists"][list_id] = list_data
        save_data(inter.guild.id, data)
        
        response = []
        if registered_users:
            response.append(f"✅ Зарегистрированы: {', '.join(registered_users)}")
        if already_registered:
            response.append(f"ℹ️ Уже были зарегистрированы: {', '.join(already_registered)}")
        
        await inter.response.send_message("\n".join(response), ephemeral=True)
        
        # Обновляем оба сообщения:
        # 1. Список с кнопками - в канале списка
        channel = bot.get_channel(list_data["channel_id"])
        if channel:
            await update_participants_message(channel, list_data)
        # 2. Статус откатов - в статическом канале
        await update_status_message(list_data)
    else:
        await inter.response.send_message("❌ Не удалось зарегистрировать ни одного пользователя!", ephemeral=True)

@bot.slash_command(description="Показать список откатов")
async def show_list(
    inter: disnake.ApplicationCommandInteraction,
    list_id: str = commands.Param(description="ID списка")
):
    list_data = get_list(list_id, inter.guild.id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
    await inter.response.defer()
    
    # Создаем временное сообщение в текущем канале
    embed = disnake.Embed(
        title=f"📋 {list_data['name']}",
        description=await generate_participants_list(list_data),
        color=0x2b2d31
    )
    embed.set_footer(text=f"ID: {list_data['id']} | Регистрация через администратора")
    
    await inter.edit_original_response(
        content=f"✅ Список '{list_data['name']}' отображен!",
        embed=embed,
        view=MainView(list_data["id"], inter.guild.id)
    )

@bot.slash_command(description="Удалить пользователя из списка")
async def remove_user(
    inter: disnake.ApplicationCommandInteraction,
    list_id: str = commands.Param(description="ID списка"),
    user: disnake.User = commands.Param(description="Пользователь для удаления")
):
    if not is_admin(inter.author):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    list_data = get_list(list_id, inter.guild.id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
    user_id = str(user.id)
    if user_id not in list_data["participants"]:
        await inter.response.send_message("❌ Пользователь не зарегистрирован в этом списке!", ephemeral=True)
        return
    
    # Получаем серверный никнейм
    member = inter.guild.get_member(user.id)
    server_nickname = member.display_name if member else user.display_name
    
    # Удаляем пользователя и его откат
    del list_data["participants"][user_id]
    
    # Удаляем откат пользователя, если он есть
    rollbacks_to_remove = []
    for timestamp, rollback in list_data["rollbacks"].items():
        if rollback["user_id"] == user_id:
            rollbacks_to_remove.append(timestamp)
    
    for timestamp in rollbacks_to_remove:
        del list_data["rollbacks"][timestamp]
    
    data = load_data(inter.guild.id)
    data["lists"][list_id] = list_data
    save_data(inter.guild.id, data)
    
    await inter.response.send_message(f"✅ Пользователь {server_nickname} удален из списка '{list_data['name']}'!", ephemeral=True)
    
    # Обновляем оба сообщения:
    # 1. Список с кнопками - в канале списка
    channel = bot.get_channel(list_data["channel_id"])
    if channel:
        await update_participants_message(channel, list_data)
    # 2. Статус откатов - в статическом канале
    await update_status_message(list_data)

@bot.slash_command(description="Удалить весь список")
async def delete_list(
    inter: disnake.ApplicationCommandInteraction,
    list_id: str = commands.Param(description="ID списка для удаления")
):
    if not is_admin(inter.author):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    list_data = get_list(list_id, inter.guild.id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
    data = load_data(inter.guild.id)
    del data["lists"][list_id]
    save_data(inter.guild.id, data)
    
    await inter.response.send_message(f"✅ Список '{list_data['name']}' (ID: {list_id}) полностью удален!", ephemeral=True)

@bot.slash_command(description="Сбросить откаты всех участников")
async def reset_rollbacks(
    inter: disnake.ApplicationCommandInteraction,
    list_id: str = commands.Param(description="ID списка")
):
    if not is_admin(inter.author):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    list_data = get_list(list_id, inter.guild.id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
    # Сбрасываем статус откатов у всех участников
    for user_id in list_data["participants"]:
        list_data["participants"][user_id]["has_rollback"] = False
    
    # Очищаем все откаты
    list_data["rollbacks"] = {}
    
    data = load_data(inter.guild.id)
    data["lists"][list_id] = list_data
    save_data(inter.guild.id, data)
    
    await inter.response.send_message(f"✅ Все откаты в списке '{list_data['name']}' сброшены!", ephemeral=True)
    
    # Обновляем оба сообщения:
    # 1. Список с кнопками - в канале списка
    channel = bot.get_channel(list_data["channel_id"])
    if channel:
        await update_participants_message(channel, list_data)
    # 2. Статус откатов - в статическом канале
    await update_status_message(list_data)

@bot.slash_command(description="Посмотреть все списки")
async def list_all(inter: disnake.ApplicationCommandInteraction):
    if not is_admin(inter.author):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    data = load_data(inter.guild.id)
    if not data["lists"]:
        await inter.response.send_message("📋 Списков пока нет!", ephemeral=True)
        return
    
    embed = disnake.Embed(title="📋 Все списки", color=0x2b2d31)
    
    for list_id, list_data in data["lists"].items():
        participants_count = len(list_data["participants"])
        rollbacks_count = sum(1 for p in list_data["participants"].values() if p["has_rollback"])
        
        embed.add_field(
            name=f"{list_data['name']} (ID: {list_id})",
            value=f"Участников: {participants_count}\nОткатов: {rollbacks_count}",
            inline=True
        )
    
    await inter.response.send_message(embed=embed, ephemeral=True)

if __name__ == "__main__":
    # Сначала пробуем прочитать из .env файла
    token = None
    try:
        if os.path.exists('.env'):
            print("✅ Файл .env найден, читаем токен...")
            with open('.env', 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('DISCORD_BOT_TOKEN='):
                        token = line.split('=', 1)[1].strip()
                        print(f"Токен из .env: {token[:20]}...")  # Показываем только первые 20 символов
                        break
    except Exception as e:
        print(f"Ошибка при чтении .env: {e}")
    
    # Если не нашли в .env, пробуем переменные окружения
    if not token:
        token = os.getenv("DISCORD_BOT_TOKEN")
        if token:
            print("✅ Токен найден в переменных окружения")
    
    if not token:
        print("❌ DISCORD_BOT_TOKEN не найден!")
        print("Проверьте что в файле .env есть строка: DISCORD_BOT_TOKEN=ваш_токен")
        input("Нажмите Enter для выхода...")
    else:
        # Проверяем длину токена (обычно 59-72 символа)
        if len(token) < 50:
            print(f"❌ Токен слишком короткий: {len(token)} символов")
            print("Возможно, в токене есть лишние символы или ошибки")
            input("Нажмите Enter для выхода...")
        else:
            try:
                print("🔄 Запуск бота...")
                bot.run(token)
            except disnake.errors.PrivilegedIntentsRequired:
                print("❌ ОШИБКА: Включите привилегированные интенты!")
                print("1. Перейдите на https://discord.com/developers/applications/")
                print("2. Выберите вашего бота")
                print("3. В разделе Bot включите:")
                print("   - SERVER MEMBERS INTENT")
                print("   - MESSAGE CONTENT INTENT")
                input("Нажмите Enter для выхода...")
            except disnake.errors.LoginFailure:
                print("❌ ОШИБКА: Неверный токен бота!")
                print("Проверьте правильность токена в файле .env")
                input("Нажмите Enter для выхода...")
            except Exception as e:
                print(f"❌ Критическая ошибка при запуске бота: {e}")
                print(f"Тип ошибки: {type(e).__name__}")
                input("Нажмите Enter для выхода...")