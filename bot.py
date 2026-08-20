import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import requests
from dotenv import load_dotenv
from flask import Flask, request
from threading import Thread
import asyncio

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# ---------- FORTNITE STATUS ----------
# A Discord csatorna ID-ja, ahová a Fortnite státusz embed kerül.
# .env fájlban: FORTNITE_CHANNEL_ID=123456789012345678
FORTNITE_CHANNEL_ID = int(os.getenv("FORTNITE_CHANNEL_ID", "0"))

FORTNITE_STATUS_URL = "https://status.epicgames.com/api/v2/summary.json"
FORTNITE_CHECK_INTERVAL = 300  # 5 perc

fortnite_last_state = None
fortnite_status_message_id = None
if not DISCORD_TOKEN:
    raise ValueError("❌ DISCORD_TOKEN nincs beállítva!")

GITHUB_BASE = "https://raw.githubusercontent.com/Mutter65/naplo2026/main/"
MEMORY_FILE = "memory.txt"

# ---------- FILE ----------
def save_to_memory(line):
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]

    try:
        r = requests.get(GITHUB_BASE + "memory.txt", timeout=10)
        if r.status_code == 200:
            return [line.strip() for line in r.text.splitlines() if line.strip()]
    except:
        pass

    return []

# ---------- TXT ----------
def load_txt(filename):
    try:
        r = requests.get(GITHUB_BASE + filename, timeout=10)
        if r.status_code == 200:
            return [x.strip() for x in r.text.splitlines() if x.strip()]
    except:
        pass
    return []

# ---------- YOUTUBE ----------
def load_youtube_users():
    data = load_txt("ytuser.txt")

    users = []

    for line in data:
        if "|" in line:
            name, filename = line.split("|", 1)
            users.append((name.strip(), filename.strip()))

    return users

# ---------- TWITCH ----------
def load_twitch_users():
    data = load_txt("twuser.txt")

    users = []

    for line in data:
        if "|" in line:
            name, username = line.split("|", 1)
            users.append((name.strip(), username.strip()))

    return users




def extract_ids_from_lines(lines):
    return [lines[i] for i in range(1, len(lines), 2) if lines[i].isdigit()]


# ---------- JOG ----------
def is_server_allowed(guild_id):
    return str(guild_id) in extract_ids_from_lines(load_txt("serverid.txt"))

def is_user_allowed(member):
    user_ids = extract_ids_from_lines(load_txt("userid.txt"))
    roles = load_txt("rangid.txt")

    if str(member.id) in user_ids:
        return True

    return any(r.name in roles for r in member.roles)

def is_admin(user_id):
    return str(user_id) in load_txt("admin.txt")

# ---------- LIMIT ----------
def get_daily_limit():
    data = load_txt("limit.txt")
    try:
        return int(data[0])
    except:
        return 10

def count_user_today(user_id):
    today = datetime.utcnow().date()
    count = 0

    for line in load_memory():
        try:
            parts = line.split("|")
            _, _, uid, time_str, _, _ = parts
            dt = datetime.fromisoformat(time_str)

            if str(user_id) == uid and dt.date() == today:
                count += 1
        except:
            continue

    return count

def get_user_limit_info(user_id):
    limit = get_daily_limit()
    current = count_user_today(user_id)
    return current, limit, max(0, limit - current)

# ---------- BOT ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- CHECK ----------
def check_access(interaction=None, ctx=None):
    if interaction:
        if not is_server_allowed(interaction.guild.id):
            return False, "❌ Ez a szerver nincs engedélyezve!"
        if not is_user_allowed(interaction.user):
            return False, "❌ Nincs jogosultságod!"
    elif ctx:
        if not is_server_allowed(ctx.guild.id):
            return False, "❌ Ez a szerver nincs engedélyezve!"
        if not is_user_allowed(ctx.author):
            return False, "❌ Nincs jogosultságod!"
    return True, None

# ---------- SCHEDULE ----------
async def schedule_message(channel, send_time, message, user_id, repeat="once", target_type="user"):
    while True:
        delay = (send_time - datetime.now(ZoneInfo("UTC"))).total_seconds()
        if delay <= 0:
            delay = 1

        await asyncio.sleep(delay)

        if target_type == "everyone":
            mention = "@everyone"
        else:
            mention = f"<@{user_id}>"

        embed = discord.Embed(
            title="📌 Emlékeztető",
            description=f"**🔴 {message.upper()}**",
            color=discord.Color.red()
        )

        if send_time.tzinfo is None:
            send_time = send_time.replace(tzinfo=ZoneInfo("UTC"))

        local = send_time.astimezone(ZoneInfo("Europe/Budapest"))
        repeat_text = {"once": "Egyszeri", "daily": "Napi", "weekly": "Heti"}[repeat]

        embed.add_field(name="👤 Kérte", value=mention, inline=False)
        embed.add_field(name="📅 Dátum", value=local.strftime("%Y.%m.%d"), inline=True)
        embed.add_field(name="⏰ Idő", value=local.strftime("%H:%M"), inline=True)
        embed.set_footer(text=f"🔁 {repeat_text} értesítés")

        await channel.send(
            content=mention,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(everyone=True, users=True)
        )

        if repeat == "once":
            break
        elif repeat == "daily":
            send_time += timedelta(days=1)
        elif repeat == "weekly":
            send_time += timedelta(weeks=1)

# ---------- DATA ----------
def get_user_data(guild_id, user_id):
    data = load_memory()

    if is_admin(user_id):
        return [line for line in data if line.startswith(str(guild_id))]

    return [line for line in data if line.startswith(str(guild_id)) and f"|{user_id}|" in line]

# ---------- MODALS ----------
class NotificationModal(discord.ui.Modal, title="Értesítés"):
    def __init__(self):
        super().__init__()
        self.target_type = "user"

    date = discord.ui.TextInput(label="📅 Dátum (2026.04.03)")
    time = discord.ui.TextInput(label="⏰ Idő (20:55)")
    message = discord.ui.TextInput(label="📝 Üzenet")

    async def on_submit(self, interaction: discord.Interaction):
        ok, msg = check_access(interaction=interaction)
        if not ok:
            return await interaction.response.send_message(msg, ephemeral=True)

        dt_local = datetime.strptime(f"{self.date.value} {self.time.value}", "%Y.%m.%d %H:%M")
        dt_local = dt_local.replace(tzinfo=ZoneInfo("Europe/Budapest"))
        dt = dt_local.astimezone(ZoneInfo("UTC"))

        save_to_memory(f"{interaction.guild.id}|{interaction.channel.id}|{interaction.user.id}|{dt.isoformat()}|{self.message.value}|once")

        asyncio.create_task(schedule_message(interaction.channel, dt, self.message.value, interaction.user.id, "once", self.target_type))

        await interaction.response.send_message("✅ Mentve!", ephemeral=True)

class RepeatModal(discord.ui.Modal):
    def __init__(self, repeat):
        super().__init__(title="Ismétlődő értesítés")
        self.repeat = repeat

        self.date = discord.ui.TextInput(label="📅 Dátum (2026.04.03)")
        self.time = discord.ui.TextInput(label="⏰ Idő (20:55)")
        self.message = discord.ui.TextInput(label="📝 Üzenet")

        self.add_item(self.date)
        self.add_item(self.time)
        self.add_item(self.message)

    async def on_submit(self, interaction: discord.Interaction):
        ok, msg = check_access(interaction=interaction)
        if not ok:
            return await interaction.response.send_message(msg, ephemeral=True)

        dt_local = datetime.strptime(f"{self.date.value} {self.time.value}", "%Y.%m.%d %H:%M")
        dt_local = dt_local.replace(tzinfo=ZoneInfo("Europe/Budapest"))
        dt = dt_local.astimezone(ZoneInfo("UTC"))

        save_to_memory(f"{interaction.guild.id}|{interaction.channel.id}|{interaction.user.id}|{dt.isoformat()}|{self.message.value}|{self.repeat}")

        asyncio.create_task(schedule_message(interaction.channel, dt, self.message.value, interaction.user.id, self.repeat))

        await interaction.response.send_message("✅ Mentve!", ephemeral=True)

# ---------- SELECT / VIEWS ----------
class RepeatSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Ismétlés típusa",
            options=[
                discord.SelectOption(label="Napi", value="daily"),
                discord.SelectOption(label="Heti", value="weekly")
            ]
        )
