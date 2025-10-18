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
DATA_FILE = "rollback_data.json"
STATIC_CHANNEL_ID = 1429128623776075916
ADMIN_IDS = [
    1381084245321056438,  
    427922282959077386,  
    300627668460634124,  
    773983223595139083,  
    415145467702280192   
]

def generate_list_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"lists": {}, "settings": {}}
def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
def is_admin(user_id):
    try:
        user_id_int = int(user_id)
        return user_id_int in ADMIN_IDS
    except (ValueError, TypeError):
        return False
def create_new_list(list_id, list_name, channel_id, created_by):
    data = load_data()
    data["lists"][list_id] = {
        "id": list_id,
        "name": list_name,
        "channel_id": channel_id,
        "created_by": created_by,
        "created_at": datetime.now().isoformat(),
        "participants": {},
        "rollbacks": {},
        "message_id": None,
        "status_message_id": None
    }
    save_data(data)
    return data["lists"][list_id]
def get_list(list_id):
    data = load_data()
    return data["lists"].get(list_id)
async def update_status_message(list_data):
    try:
        channel_id = list_data["channel_id"]
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
                        rollback_preview = user_rollback['text'][:150]
                        if len(user_rollback['text']) > 150:
                            rollback_preview += "..."
                        message_content += f"  └ 📝 {rollback_preview}\n"
                message_content += "\n"
        
        status_message_id = list_data.get("status_message_id")
        data = load_data()
        
        if status_message_id:
            try:
                status_message = await channel.fetch_message(status_message_id)
                await status_message.edit(content=message_content)
                return
            except:
                pass
        
        new_message = await channel.send(message_content)
        list_data["status_message_id"] = new_message.id
        data["lists"][list_data["id"]] = list_data
        save_data(data)
        
    except Exception as e:
        print(f"Ошибка при обновлении статуса списка {list_data['id']}: {e}")
class CreateListTimeModal(disnake.ui.Modal):
    def __init__(self, list_name):
        self.list_name = list_name
        components = [
            disnake.ui.TextInput(
                label="Время",
                placeholder="Укажите время (например: 18:00, 20:30)",
                custom_id="time",
                style=TextInputStyle.short,
                max_length=10,
                required=True
            )
        ]
        super().__init__(title=f"Создание списка {list_name}", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        data = load_data()
        time_value = inter.text_values["time"].strip()
        
        list_id = generate_list_id()
        while list_id in data["lists"]:
            list_id = generate_list_id()
        
        full_name = f"{self.list_name} {time_value}"
        
        channel = bot.get_channel(STATIC_CHANNEL_ID)
        if not channel:
            await inter.response.send_message(
                f"❌ Канал с ID {STATIC_CHANNEL_ID} не найден! Обратитесь к администратору.",
                ephemeral=True
            )
            return
        
        list_data = create_new_list(list_id, full_name, STATIC_CHANNEL_ID, str(inter.author.id))
        
        await inter.response.send_message(
            f"✅ Список создан!\n"
            f"ID: `{list_id}`\n"
            f"Название: {full_name}\n"
            f"Канал для файлов: {channel.mention}\n\n"
            f"Для регистрации участников используйте:\n"
            f"`/register_user list_id:{list_id} users:@участник1 @участник2`",
            ephemeral=True
        )
        await update_participants_message(inter.channel, list_data)
        await update_status_message(list_data)

class ListTypeSelectionView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
    
    @disnake.ui.button(label="MCL", style=disnake.ButtonStyle.primary, custom_id="select_mcl")
    async def mcl_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(CreateListTimeModal("MCL"))
    
    @disnake.ui.button(label="VZZ", style=disnake.ButtonStyle.primary, custom_id="select_vzz")
    async def vzz_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(CreateListTimeModal("VZZ"))
class RollbackModal(disnake.ui.Modal):
    def __init__(self, list_id):
        components = [
            disnake.ui.TextInput(
                label="Ваш откат",
                placeholder="Опишите подробно вашу идею или предложение...",
                custom_id="rollback_text",
                style=TextInputStyle.paragraph,
                max_length=2000,
                required=True
            )
        ]
        super().__init__(title="Отправить откат", components=components)
        self.list_id = list_id

    async def callback(self, inter: disnake.ModalInteraction):
        list_data = get_list(self.list_id)
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
        if list_data["participants"][user_id]["has_rollback"]:
            await inter.response.send_message(
                "❌ Вы уже отправляли откат! Каждый участник может отправить только один откат.",
                ephemeral=True
            )
            return
            
        rollback_text = inter.text_values["rollback_text"]
        timestamp = datetime.now().isoformat()
        
        server_nickname = inter.author.display_name
        list_data["participants"][user_id]["display_name"] = server_nickname
        
        list_data["rollbacks"][timestamp] = {
            "user_id": user_id,
            "user_name": server_nickname,
            "text": rollback_text,
            "timestamp": timestamp
        }
        list_data["participants"][user_id]["has_rollback"] = True
        data = load_data()
        data["lists"][self.list_id] = list_data
        save_data(data)
        await inter.response.send_message(
            f"✅ Ваш откат отправлен в список '{list_data['name']}'! Статус обновлен.", 
            ephemeral=True
        )
        await update_participants_message(inter.channel, list_data)
        await update_status_message(list_data)
async def update_participants_message(channel, list_data):
    if not list_data:
        return
    data = load_data()
    if list_data.get("message_id"):
        try:
            message = await channel.fetch_message(list_data["message_id"])
            embed = disnake.Embed(
                title=f"📋 {list_data['name']}",
                description=await generate_participants_list(list_data),
                color=0x2b2d31
            )
            embed.set_footer(text=f"ID: {list_data['id']} | Регистрация через администратора")
            await message.edit(embed=embed, view=MainView(list_data["id"]))
            return
        except:
            pass
    embed = disnake.Embed(
        title=f"📋 {list_data['name']}",
        description=await generate_participants_list(list_data),
        color=0x2b2d31
    )
    embed.set_footer(text=f"ID: {list_data['id']} | Регистрация через администратора")
    message = await channel.send(embed=embed, view=MainView(list_data["id"]))
    
    list_data["message_id"] = message.id
    data["lists"][list_data["id"]] = list_data
    save_data(data)
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
    def __init__(self, list_id):
        super().__init__(timeout=None)
        self.list_id = list_id
    
    @disnake.ui.button(label="Отправить откат", style=disnake.ButtonStyle.primary, custom_id="send_rollback")
    async def rollback_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        list_data = get_list(self.list_id)
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
        if list_data["participants"][user_id]["has_rollback"]:
            await inter.response.send_message(
                "❌ Вы уже отправляли откат! Каждый участник может отправить только один откат.",
                ephemeral=True
            )
            return
            
        await inter.response.send_modal(RollbackModal(self.list_id))
    
    @disnake.ui.button(label="Обновить список", style=disnake.ButtonStyle.secondary, custom_id="refresh_list")
    async def refresh_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        list_data = get_list(self.list_id)
        if not list_data:
            await inter.response.send_message("❌ Список не найден!", ephemeral=True)
            return
            
        await update_participants_message(inter.channel, list_data)
        await inter.edit_original_response(content="✅ Список обновлен!")

@bot.event
async def on_ready():
    print(f'Bot {bot.user} готов к работе!')
    print(f'Подключен к {len(bot.guilds)} серверам')
    for list_id in load_data().get("lists", {}):
        bot.add_view(MainView(list_id))

@bot.slash_command(description="Создать новый список откатов")
async def create_list(inter: disnake.ApplicationCommandInteraction):
    print(f"Admin check: User ID {inter.author.id}, Admin IDs: {ADMIN_IDS}, Is admin: {is_admin(inter.author.id)}")
    if not is_admin(inter.author.id):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    view = ListTypeSelectionView()
    await inter.response.send_message(
        "📋 **Выберите тип списка:**",
        view=view,
        ephemeral=True
    )

@bot.slash_command(description="Регистрировать пользователей в списке")
async def register_user(
    inter: disnake.ApplicationCommandInteraction,
    list_id: str = commands.Param(description="ID списка"),
    users: str = commands.Param(description="Пользователи через @ или ID через пробел")
):
    if not is_admin(inter.author.id):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    list_data = get_list(list_id)
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
            member = inter.guild.get_member(int(user_id))
            if not member:
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
        data = load_data()
        data["lists"][list_id] = list_data
        save_data(data)
        
        response = []
        if registered_users:
            response.append(f"✅ Зарегистрированы: {', '.join(registered_users)}")
        if already_registered:
            response.append(f"ℹ️ Уже были зарегистрированы: {', '.join(already_registered)}")
        
        await inter.response.send_message("\n".join(response), ephemeral=True)
        await update_participants_message(inter.channel, list_data)
        await update_status_message(list_data)
    else:
        await inter.response.send_message("❌ Не удалось зарегистрировать ни одного пользователя!", ephemeral=True)

@bot.slash_command(description="Показать список откатов")
async def show_list(
    inter: disnake.ApplicationCommandInteraction,
    list_id: str = commands.Param(description="ID списка")
):
    list_data = get_list(list_id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
    await inter.response.defer()
    await update_participants_message(inter.channel, list_data)
    await inter.edit_original_response(content=f"✅ Список '{list_data['name']}' отображен!")

@bot.slash_command(description="Удалить пользователя из списка")
async def remove_user(
    inter: disnake.ApplicationCommandInteraction,
    list_id: str = commands.Param(description="ID списка"),
    user: disnake.User = commands.Param(description="Пользователь для удаления")
):
    if not is_admin(inter.author.id):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    list_data = get_list(list_id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
    user_id = str(user.id)
    if user_id not in list_data["participants"]:
        await inter.response.send_message("❌ Пользователь не зарегистрирован в этом списке!", ephemeral=True)
        return
    
    member = inter.guild.get_member(user.id)
    server_nickname = member.display_name if member else user.display_name
    
    del list_data["participants"][user_id]
    
    rollbacks_to_remove = []
    for timestamp, rollback in list_data["rollbacks"].items():
        if rollback["user_id"] == user_id:
            rollbacks_to_remove.append(timestamp)
    
    for timestamp in rollbacks_to_remove:
        del list_data["rollbacks"][timestamp]
    
    data = load_data()
    data["lists"][list_id] = list_data
    save_data(data)
    
    await inter.response.send_message(f"✅ Пользователь {server_nickname} удален из списка '{list_data['name']}'!", ephemeral=True)
    await update_participants_message(inter.channel, list_data)
    await update_status_message(list_data)

@bot.slash_command(description="Удалить весь список")
async def delete_list(
    inter: disnake.ApplicationCommandInteraction,
    list_id: str = commands.Param(description="ID списка для удаления")
):
    if not is_admin(inter.author.id):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    list_data = get_list(list_id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
    data = load_data()
    del data["lists"][list_id]
    save_data(data)
    
    await inter.response.send_message(f"✅ Список '{list_data['name']}' (ID: {list_id}) полностью удален!", ephemeral=True)

@bot.slash_command(description="Сбросить откаты всех участников")
async def reset_rollbacks(
    inter: disnake.ApplicationCommandInteraction,
    list_id: str = commands.Param(description="ID списка")
):
    if not is_admin(inter.author.id):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    list_data = get_list(list_id)
    if not list_data:
        await inter.response.send_message("❌ Список с таким ID не найден!", ephemeral=True)
        return
    
    for user_id in list_data["participants"]:
        list_data["participants"][user_id]["has_rollback"] = False
    
    list_data["rollbacks"] = {}
    
    data = load_data()
    data["lists"][list_id] = list_data
    save_data(data)
    
    await inter.response.send_message(f"✅ Все откаты в списке '{list_data['name']}' сброшены!", ephemeral=True)
    await update_participants_message(inter.channel, list_data)
    await update_status_message(list_data)

@bot.slash_command(description="Посмотреть все списки")
async def list_all(inter: disnake.ApplicationCommandInteraction):
    if not is_admin(inter.author.id):
        await inter.response.send_message("❌ У вас нет прав для выполнения этой команды!", ephemeral=True)
        return
    
    data = load_data()
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
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("❌ DISCORD_BOT_TOKEN не найден в переменных окружения!")
        print("Добавьте ваш токен бота в переменные окружения или файл .env")
    else:
        bot.run(token)