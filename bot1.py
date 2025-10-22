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
import asyncpg
import asyncio

intents = disnake.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

SERVER_CONFIGS = {
    1429544000188317831: {
        "static_channel_id": 1429831404379705474,
        "admin_role_ids": [1310673963000528949, 1223589384452833290, 1429544345463296000],
    },
    1003525677640851496: {
        "static_channel_id": 1429128623776075916,
        "admin_ids": [1381084245321056438, 427922282959077386, 300627668460634124, 773983223595139083, 415145467702280192],
    }
}

class Database:
    def __init__(self):
        self.pool = None
    
    async def get_database_url(self):
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            return database_url
        database_url = os.getenv('POSTGRES_URL')
        if database_url:
            return database_url
        database_url = os.getenv('POSTGRESQL_URL')
        if database_url:
            return database_url
        return None
    
    async def connect(self):
        database_url = await self.get_database_url()
        if not database_url:
            raise Exception("DATABASE_URL не найден!")
        
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        
        try:
            self.pool = await asyncpg.create_pool(
                database_url,
                min_size=1,
                max_size=10,
                command_timeout=60
            )
            await self.init_tables()
            print("✅ Подключение к базе данных установлено")
        except Exception as e:
            print(f"❌ Ошибка подключения к базе: {e}")
            raise
    
    async def init_tables(self):
        try:
            await self.pool.execute('''
                CREATE TABLE IF NOT EXISTS lists (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    channel_id BIGINT NOT NULL,
                    static_channel_id BIGINT NOT NULL,
                    created_by TEXT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    message_id BIGINT,
                    status_message_id BIGINT
                )
            ''')
            
            await self.pool.execute('''
                CREATE TABLE IF NOT EXISTS participants (
                    user_id TEXT NOT NULL,
                    list_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    has_rollback BOOLEAN DEFAULT FALSE,
                    registered_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (user_id, list_id),
                    FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE
                )
            ''')
            
            await self.pool.execute('''
                CREATE TABLE IF NOT EXISTS rollbacks (
                    timestamp TIMESTAMP DEFAULT NOW(),
                    user_id TEXT NOT NULL,
                    list_id TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    PRIMARY KEY (user_id, list_id),
                    FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE
                )
            ''')
            
            print("✅ Таблицы инициализированы")
        except Exception as e:
            print(f"❌ Ошибка инициализации таблиц: {e}")
            raise

db = Database()

active_lists = {}

def get_server_config(guild_id):
    return SERVER_CONFIGS.get(guild_id)

def is_admin(member):
    if not member:
        return False
    
    config = get_server_config(member.guild.id)
    if not config:
        return False
    
    if member.guild.id == 1429544000188317831:
        try:
            member_role_ids = [role.id for role in member.roles]
            return any(role_id in config["admin_role_ids"] for role_id in member_role_ids)
        except:
            return False
    elif member.guild.id == 1003525677640851496:
        try:
            return member.id in config["admin_ids"]
        except:
            return False
    
    return False

def generate_list_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))

async def create_new_list(list_id, list_name, channel_id, created_by, guild_id):
    config = get_server_config(guild_id)
    static_channel_id = config["static_channel_id"] if config else channel_id
    
    await db.pool.execute('''
        INSERT INTO lists (id, name, channel_id, static_channel_id, created_by, guild_id)
        VALUES ($1, $2, $3, $4, $5, $6)
    ''', list_id, list_name, channel_id, static_channel_id, created_by, guild_id)
    
    list_data = {
        "id": list_id,
        "name": list_name,
        "channel_id": channel_id,
        "static_channel_id": static_channel_id,
        "created_by": created_by,
        "guild_id": guild_id,
        "participants": {},
        "rollbacks": {}
    }
    
    active_lists[list_id] = list_data
    
    return list_data

async def get_list(list_id, guild_id, update_active=True):
    row = await db.pool.fetchrow('''
        SELECT * FROM lists WHERE id = $1 AND guild_id = $2
    ''', list_id, guild_id)
    
    if not row:
        if list_id in active_lists:
            del active_lists[list_id]
        return None
    
    participants_rows = await db.pool.fetch('''
        SELECT * FROM participants WHERE list_id = $1
    ''', list_id)
    
    participants = {}
    for p in participants_rows:
        participants[p['user_id']] = {
            "display_name": p['display_name'],
            "has_rollback": p['has_rollback'],
            "registered_at": p['registered_at'].isoformat()
        }
    
    rollbacks_rows = await db.pool.fetch('''
        SELECT * FROM rollbacks WHERE list_id = $1
    ''', list_id)
    
    rollbacks = {}
    for r in rollbacks_rows:
        rollbacks[r['timestamp'].isoformat()] = {
            "user_id": r['user_id'],
            "user_name": r['user_name'],
            "text": r['text'],
            "timestamp": r['timestamp'].isoformat()
        }
    
    list_data = {
        "id": row['id'],
        "name": row['name'],
        "channel_id": row['channel_id'],
        "static_channel_id": row['static_channel_id'],
        "created_by": row['created_by'],
        "guild_id": row['guild_id'],
        "created_at": row['created_at'].isoformat(),
        "message_id": row['message_id'],
        "status_message_id": row['status_message_id'],
        "participants": participants,
        "rollbacks": rollbacks
    }
    
    if update_active:
        active_lists[list_id] = list_data
    
    return list_data

async def remove_user_rollback(list_data, user_id):
    await db.pool.execute('''
        DELETE FROM rollbacks WHERE list_id = $1 AND user_id = $2
    ''', list_data["id"], user_id)
    
    await db.pool.execute('''
        UPDATE participants SET has_rollback = FALSE 
        WHERE list_id = $1 AND user_id = $2
    ''', list_data["id"], user_id)
    
    return True

def clean_rollback_text(text):
    if not text:
        return ""
    
    clean_text = re.sub(r'<[^>]+>', '', text)
    clean_text = re.sub(r'\s+', ' ', clean_text)
    clean_text = clean_text.strip()
    
    return clean_text

async def update_status_message(list_data):
    try:
        config = get_server_config(list_data["guild_id"])
        if not config:
            return
            
        channel_id = config["static_channel_id"]
        channel = bot.get_channel(channel_id)
        if not channel:
            return
        
        list_data = await get_list(list_data["id"], list_data["guild_id"], update_active=True)
        if not list_data:
            return
        
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
        
        status_message_id = list_data.get("status_message_id")
        
        if status_message_id:
            try:
                status_message = await channel.fetch_message(status_message_id)
                await status_message.edit(content=message_content)
                return
            except:
                pass
        
        new_message = await channel.send(message_content)
        
        await db.pool.execute('''
            UPDATE lists SET status_message_id = $1 WHERE id = $2
        ''', new_message.id, list_data["id"])
        
    except Exception as e:
        print(f"Ошибка при обновлении статуса списка {list_data['id']}: {e}")

async def update_participants_message(channel, list_data):
    if not list_data:
        return
    
    list_data = await get_list(list_data["id"], list_data["guild_id"], update_active=True)
    if not list_data:
        return
    
    if list_data.get("message_id"):
        try:
            message = await channel.fetch_message(list_data["message_id"])
            embed = disnake.Embed(
                title=f"📋 {list_data['name']}",
                description=await generate_participants_list(list_data),
                color=0x2b2d31
            )
            embed.set_footer(text=f"ID: {list_data['id']} | Регистрация через администратора")
            
            view = MainView(list_data["id"], list_data["guild_id"])
            await message.edit(embed=embed, view=view)
            return
        except:
            pass
    
    embed = disnake.Embed(
        title=f"📋 {list_data['name']}",
        description=await generate_participants_list(list_data),
        color=0x2b2d31
    )
    embed.set_footer(text=f"ID: {list_data['id']} | Регистрация через администратора")
    
    view = MainView(list_data["id"], list_data["guild_id"])
    message = await channel.send(embed=embed, view=view)
    
    await db.pool.execute('''
        UPDATE lists SET message_id = $1 WHERE id = $2
    ''', message.id, list_data["id"])

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

@tasks.loop(seconds=30)
async def auto_update_lists():
    try:
        print(f"🔄 Авто-обновление списков... ({len(active_lists)} активных списков)")
        
        for list_id, list_data in list(active_lists.items()):
            try:
                current_list_data = await get_list(list_id, list_data["guild_id"], update_active=True)
                if not current_list_data:
                    del active_lists[list_id]
                    continue
                
                channel = bot.get_channel(current_list_data["channel_id"])
                if channel:
                    await update_participants_message(channel, current_list_data)
                
                await update_status_message(current_list_data)
                
                print(f"✅ Обновлен список: {list_id} (участников: {len(current_list_data['participants'])}, откатов: {len(current_list_data['rollbacks'])})")
                
            except Exception as e:
                print(f"❌ Ошибка при авто-обновлении списка {list_id}: {e}")
        
        print(f"✅ Авто-обновление завершено")
        
    except Exception as e:
        print(f"❌ Критическая ошибка в auto_update_lists: {e}")

@bot.event
async def on_ready():
    print(f'Bot {bot.user} готов к работе!')
    print(f'Подключен к {len(bot.guilds)} серверам')
    
    try:
        for guild in bot.guilds:
            rows = await db.pool.fetch('SELECT id FROM lists WHERE guild_id = $1', guild.id)
            for row in rows:
                list_data = await get_list(row['id'], guild.id)
                if list_data:
                    active_lists[list_data["id"]] = list_data
                    print(f"📋 Загружен активный список: {list_data['id']}")
    except Exception as e:
        print(f"❌ Ошибка при загрузке активных списков: {e}")
    
    auto_update_lists.start()
    print("✅ Авто-обновление списков запущено (каждые 30 секунд)")
    print("✅ Бот запущен и готов к работе!")

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
        time_value = inter.text_values["time"].strip()
        date_value = inter.text_values["date"].strip()
        name_value = inter.text_values["name"].strip()
        server_value = inter.text_values["event_server"].strip()
        
        list_id = generate_list_id()
        
        existing = await db.pool.fetchrow('SELECT id FROM lists WHERE id = $1', list_id)
        while existing:
            list_id = generate_list_id()
            existing = await db.pool.fetchrow('SELECT id FROM lists WHERE id = $1', list_id)
        
        full_name = f"{time_value} | {date_value} | {name_value} | {server_value}"
        
        list_data = await create_new_list(list_id, full_name, inter.channel_id, str(inter.author.id), self.guild_id)
        
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
        
        await update_participants_message(inter.channel, list_data)
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
        list_data = await get_list(self.list_id, self.guild_id)
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
        
        cleaned_text = clean_rollback_text(rollback_text)
        
        if not cleaned_text:
            await inter.response.send_message(
                "❌ Текст отката не может быть пустым! Пожалуйста, напишите ваш откат текстом, а не только ссылками.",
                ephemeral=True
            )
            return
        
        server_nickname = inter.author.display_name
        
        if self.has_existing_rollback:
            await remove_user_rollback(list_data, user_id)
        
        await db.pool.execute('''
            INSERT INTO rollbacks (user_id, list_id, user_name, text)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, list_id) 
            DO UPDATE SET user_name = $3, text = $4, timestamp = NOW()
        ''', user_id, self.list_id, server_nickname, cleaned_text)
        
        await db.pool.execute('''
            UPDATE participants SET has_rollback = TRUE, display_name = $3
            WHERE user_id = $1 AND list_id = $2
        ''', user_id, self.list_id, server_nickname)
        
        if self.has_existing_rollback:
            message = f"✅ Ваш откат в списке '{list_data['name']}' заменен на новый! Статус обновлен."
        else:
            message = f"✅ Ваш откат отправлен в список '{list_data['name']}'! Статус обновлен."
            
        await inter.response.send_message(message, ephemeral=True)
        
        channel = bot.get_channel(list_data["channel_id"])
        if channel:
            await update_participants_message(channel, list_data)
        await update_status_message(list_data)

class DeleteRollbackView(disnake.ui.View):
    def __init__(self, list_id, guild_id):
        super().__init__(timeout=60)
        self.list_id = list_id
        self.guild_id = guild_id
    
    @disnake.ui.button(label="Да, удалить мой откат", style=disnake.ButtonStyle.danger)
    async def confirm_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        list_data = await get_list(self.list_id, self.guild_id)
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
        
        if await remove_user_rollback(list_data, user_id):
            await inter.response.send_message(
                f"✅ Ваш откат удален из списка '{list_data['name']}'!", 
                ephemeral=True
            )
            
            channel = bot.get_channel(list_data["channel_id"])
            if channel:
                await update_participants_message(channel, list_data)
            await update_status_message(list_data)
        else:
            await inter.response.send_message("❌ Не удалось удалить откат!", ephemeral=True)
        
        await inter.message.delete()
    
    @disnake.ui.button(label="Отмена", style=disnake.ButtonStyle.secondary)
    async def cancel_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_message("❌ Удаление отката отменено.", ephemeral=True)
        await inter.message.delete()

class MainView(disnake.ui.View):
    def __init__(self, list_id, guild_id):
        super().__init__(timeout=None)
        self.list_id = list_id
        self.guild_id = guild_id
    
    @disnake.ui.button(label="Отправить откат", style=disnake.ButtonStyle.primary)
    async def rollback_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        list_data = await get_list(self.list_id, self.guild_id)
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
        
        has_existing_rollback = list_data["participants"][user_id]["has_rollback"]
        
        if has_existing_rollback:
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
            await inter.response.send_modal(RollbackModal(self.list_id, self.guild_id, has_existing_rollback=False))
    
    @disnake.ui.button(label="Обновить список", style=disnake.ButtonStyle.secondary)
    async def refresh_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        list_data = await get_list(self.list_id, self.guild_id)
        if not list_data:
            await inter.followup.send("❌ Список не найден!", ephemeral=True)
            return
            
        channel = bot.get_channel(list_data["channel_id"])
        if channel:
            await update_participants_message(channel, list_data)
        await update_status_message(list_data)
        await inter.edit_original_response(content="✅ Оба списка обновлены!")

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
    
    list_data = await get_list(list_id, inter.guild.id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
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
            member = inter.guild.get_member(int(user_id))
            if not member:
                member = await bot.fetch_user(int(user_id))
            
            server_nickname = member.display_name
            
            existing = await db.pool.fetchrow(
                'SELECT 1 FROM participants WHERE user_id = $1 AND list_id = $2',
                user_id, list_id
            )
            
            if existing:
                already_registered.append(server_nickname)
            else:
                await db.pool.execute('''
                    INSERT INTO participants (user_id, list_id, display_name)
                    VALUES ($1, $2, $3)
                ''', user_id, list_id, server_nickname)
                registered_users.append(server_nickname)
        except:
            continue
    
    if registered_users or already_registered:
        response = []
        if registered_users:
            response.append(f"✅ Зарегистрированы: {', '.join(registered_users)}")
        if already_registered:
            response.append(f"ℹ️ Уже были зарегистрированы: {', '.join(already_registered)}")
        
        await inter.response.send_message("\n".join(response), ephemeral=True)
        
        channel = bot.get_channel(list_data["channel_id"])
        if channel:
            await update_participants_message(channel, list_data)
        await update_status_message(list_data)
    else:
        await inter.response.send_message("❌ Не удалось зарегистрировать ни одного пользователя!", ephemeral=True)

@bot.slash_command(description="Показать список откатов")
async def show_list(
    inter: disnake.ApplicationCommandInteraction,
    list_id: str = commands.Param(description="ID списка")
):
    list_data = await get_list(list_id, inter.guild.id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
    await inter.response.defer()
    
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
    
    list_data = await get_list(list_id, inter.guild.id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
    user_id = str(user.id)
    
    existing = await db.pool.fetchrow(
        'SELECT 1 FROM participants WHERE user_id = $1 AND list_id = $2',
        user_id, list_id
    )
    
    if not existing:
        await inter.response.send_message("❌ Пользователь не зарегистрирован в этом списке!", ephemeral=True)
        return
    
    member = inter.guild.get_member(user.id)
    server_nickname = member.display_name if member else user.display_name
    
    await db.pool.execute('DELETE FROM participants WHERE user_id = $1 AND list_id = $2', user_id, list_id)
    await db.pool.execute('DELETE FROM rollbacks WHERE user_id = $1 AND list_id = $2', user_id, list_id)
    
    await inter.response.send_message(f"✅ Пользователь {server_nickname} удален из списка '{list_data['name']}'!", ephemeral=True)
    
    channel = bot.get_channel(list_data["channel_id"])
    if channel:
        await update_participants_message(channel, list_data)
    await update_status_message(list_data)

@bot.slash_command(description="Удалить весь список")
async def delete_list(
    inter: disnake.ApplicationCommandInteraction,
    list_id: str = commands.Param(description="ID списка для удаления")
):
    if not is_admin(inter.author):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    list_data = await get_list(list_id, inter.guild.id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
    await db.pool.execute('DELETE FROM lists WHERE id = $1', list_id)
    
    if list_id in active_lists:
        del active_lists[list_id]
    
    await inter.response.send_message(f"✅ Список '{list_data['name']}' (ID: {list_id}) полностью удален!", ephemeral=True)

@bot.slash_command(description="Сбросить откаты всех участников")
async def reset_rollbacks(
    inter: disnake.ApplicationCommandInteraction,
    list_id: str = commands.Param(description="ID списка")
):
    if not is_admin(inter.author):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    list_data = await get_list(list_id, inter.guild.id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
    await db.pool.execute('''
        UPDATE participants SET has_rollback = FALSE WHERE list_id = $1
    ''', list_id)
    
    await db.pool.execute('DELETE FROM rollbacks WHERE list_id = $1', list_id)
    
    await inter.response.send_message(f"✅ Все откаты в списке '{list_data['name']}' сброшены!", ephemeral=True)
    
    channel = bot.get_channel(list_data["channel_id"])
    if channel:
        await update_participants_message(channel, list_data)
    await update_status_message(list_data)

@bot.slash_command(description="Посмотреть все списки")
async def list_all(inter: disnake.ApplicationCommandInteraction):
    if not is_admin(inter.author):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    rows = await db.pool.fetch('SELECT * FROM lists WHERE guild_id = $1', inter.guild.id)
    
    if not rows:
        await inter.response.send_message("📋 Списков пока нет!", ephemeral=True)
        return
    
    embed = disnake.Embed(title="📋 Все списки", color=0x2b2d31)
    
    for row in rows:
        participants_count = await db.pool.fetchval(
            'SELECT COUNT(*) FROM participants WHERE list_id = $1', row['id']
        )
        rollbacks_count = await db.pool.fetchval(
            'SELECT COUNT(*) FROM participants WHERE list_id = $1 AND has_rollback = TRUE', row['id']
        )
        
        embed.add_field(
            name=f"{row['name']} (ID: {row['id']})",
            value=f"Участников: {participants_count}\nОткатов: {rollbacks_count}",
            inline=True
        )
    
    await inter.response.send_message(embed=embed, ephemeral=True)

async def main():
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            print(f"🔄 Попытка подключения к базе данных {attempt + 1}/{max_retries}...")
            await db.connect()
            break
        except Exception as e:
            print(f"❌ Попытка {attempt + 1} не удалась: {e}")
            if attempt < max_retries - 1:
                print(f"⏳ Ждем {retry_delay} секунд перед следующей попыткой...")
                await asyncio.sleep(retry_delay)
            else:
                print("❌ Все попытки подключения провалились!")
                raise
    
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print("❌ DISCORD_BOT_TOKEN не найден!")
        exit(1)
    
    print("🚀 Запускаем бота...")
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())