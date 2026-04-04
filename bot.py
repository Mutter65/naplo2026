import discord
from discord.ext import commands
from datetime import datetime, timedelta
import os
import requests
from dotenv import load_dotenv
from flask import Flask, request
from threading import Thread
import asyncio

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
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

def extract_ids_from_lines(lines):
    return [lines[i] for i in range(1, len(lines), 2)]

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

# ---------- SCHEDULE ----------
async def schedule_message(channel, send_time, message, user_id, repeat="once"):
    while True:
        delay = (send_time - datetime.utcnow()).total_seconds()
        if delay <= 0:
            delay = 1

        await asyncio.sleep(delay)

        mention = f"<@{user_id}>"

        embed = discord.Embed(
            title="📌 Emlékeztető",
            description=f"**🔴 {message.upper()}**",
            color=discord.Color.red()
        )

        local = send_time + timedelta(hours=2)

        repeat_text = {"once": "Egyszeri", "daily": "Napi", "weekly": "Heti"}[repeat]

        embed.add_field(name="👤 Kérte", value=mention, inline=False)
        embed.add_field(name="📅 Dátum", value=local.strftime("%Y.%m.%d"), inline=True)
        embed.add_field(name="⏰ Idő", value=local.strftime("%H:%M"), inline=True)
        embed.set_footer(text=f"🔁 {repeat_text} értesítés")

        await channel.send(content=mention, embed=embed)

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

# ---------- MODAL ----------
class NotificationModal(discord.ui.Modal, title="Értesítés"):
    date = discord.ui.TextInput(label="📅 Dátum (2026.04.03)")
    time = discord.ui.TextInput(label="⏰ Idő (20:55)")
    message = discord.ui.TextInput(label="📝 Üzenet")

    async def on_submit(self, interaction: discord.Interaction):

        limit = get_daily_limit()
        current = count_user_today(interaction.user.id)

        if current >= limit:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Limit elérve",
                    description=f"{limit} / {limit}",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )

        dt = datetime.strptime(f"{self.date.value} {self.time.value}", "%Y.%m.%d %H:%M")
        dt -= timedelta(hours=2)

        save_to_memory(f"{interaction.guild.id}|{interaction.channel.id}|{interaction.user.id}|{dt.isoformat()}|{self.message.value}|once")

        asyncio.create_task(schedule_message(interaction.channel, dt, self.message.value, interaction.user.id, "once"))

        current, limit, remaining = get_user_limit_info(interaction.user.id)

        embed = discord.Embed(title="✅ Mentve", color=discord.Color.green())
        embed.add_field(name="📊 Limit", value=f"{current}/{limit} | Maradék: {remaining}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------- SELECT REPEAT ----------
class RepeatSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Ismétlés típusa",
            options=[
                discord.SelectOption(label="Napi", value="daily"),
                discord.SelectOption(label="Heti", value="weekly")
            ]
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RepeatModal(self.values[0]))

class RepeatView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(RepeatSelect())

class RepeatModal(discord.ui.Modal):
    def __init__(self, repeat):
        super().__init__(title="Ismétlődő értesítés")
        self.repeat = repeat

        self.date = discord.ui.TextInput(label="📅 Dátum")
        self.time = discord.ui.TextInput(label="⏰ Idő")
        self.message = discord.ui.TextInput(label="📝 Üzenet")

        self.add_item(self.date)
        self.add_item(self.time)
        self.add_item(self.message)

    async def on_submit(self, interaction: discord.Interaction):

        limit = get_daily_limit()
        current = count_user_today(interaction.user.id)

        if current >= limit:
            return await interaction.response.send_message("❌ Limit!", ephemeral=True)

        dt = datetime.strptime(f"{self.date.value} {self.time.value}", "%Y.%m.%d %H:%M")
        dt -= timedelta(hours=2)

        save_to_memory(f"{interaction.guild.id}|{interaction.channel.id}|{interaction.user.id}|{dt.isoformat()}|{self.message.value}|{self.repeat}")

        asyncio.create_task(schedule_message(interaction.channel, dt, self.message.value, interaction.user.id, self.repeat))

        await interaction.response.send_message("✅ Mentve!", ephemeral=True)

# ---------- DELETE ----------
class DeleteSelect(discord.ui.Select):
    def __init__(self, data):
        self.data = data

        options = []
        for i, line in enumerate(data[:25]):
            parts = line.split("|")
            _, _, _, time_str, msg, repeat = parts

            dt = datetime.fromisoformat(time_str) + timedelta(hours=2)

            options.append(discord.SelectOption(
                label=f"{dt.strftime('%m.%d %H:%M')} • {repeat}",
                description=msg[:50],
                value=str(i)
            ))

        super().__init__(placeholder="Törlendő kiválasztása", options=options)

    async def callback(self, interaction: discord.Interaction):
        all_data = load_memory()
        selected = self.data[int(self.values[0])]

        all_data.remove(selected)

        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            for line in all_data:
                f.write(line + "\n")

        await interaction.response.send_message("🗑️ Törölve!", ephemeral=True)

class DeleteView(discord.ui.View):
    def __init__(self, data):
        super().__init__()
        self.add_item(DeleteSelect(data))

# ---------- MENU ----------
class MenuView(discord.ui.View):

    @discord.ui.button(label="Értesítés", style=discord.ButtonStyle.green)
    async def notify(self, interaction, button):
        await interaction.response.send_modal(NotificationModal())

    @discord.ui.button(label="Ismétlődő", style=discord.ButtonStyle.blurple)
    async def repeat(self, interaction, button):
        await interaction.response.send_message("Válassz:", view=RepeatView(), ephemeral=True)

    @discord.ui.button(label="Törlés", style=discord.ButtonStyle.red)
    async def delete(self, interaction, button):
        data = get_user_data(interaction.guild.id, interaction.user.id)
        if not data:
            return await interaction.response.send_message("Nincs adat", ephemeral=True)

        await interaction.response.send_message("Válassz:", view=DeleteView(data), ephemeral=True)

    @discord.ui.button(label="Lista", style=discord.ButtonStyle.gray)
    async def list_btn(self, interaction, button):

        data = get_user_data(interaction.guild.id, interaction.user.id)

        if not data:
            return await interaction.response.send_message("📭 Üres", ephemeral=True)

        embed = discord.Embed(title="📋 Lista", color=discord.Color.green())

        for i, line in enumerate(data[:10]):
            parts = line.split("|")
            _, _, _, time_str, msg, repeat = parts

            dt = datetime.fromisoformat(time_str) + timedelta(hours=2)

            embed.add_field(
                name=f"{i}. {dt.strftime('%m.%d %H:%M')}",
                value=f"{repeat} | {msg}",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------- COMMAND ----------
@bot.command()
async def n(ctx):
    current, limit, remaining = get_user_limit_info(ctx.author.id)

    embed = discord.Embed(title="📌 Központ", color=discord.Color.blurple())
    embed.add_field(name="📊 Limit", value=f"{current}/{limit} | {remaining} maradt")

    await ctx.send(embed=embed, view=MenuView())

# ---------- READY ----------
@bot.event
async def on_ready():
    print("Bot fut:", bot.user)

    for line in load_memory():
        try:
            guild_id, channel_id, user_id, time_str, msg, repeat = line.split("|", 5)
            channel = bot.get_channel(int(channel_id))
            dt = datetime.fromisoformat(time_str)

            asyncio.create_task(schedule_message(channel, dt, msg, int(user_id), repeat))
        except:
            continue

# ---------- WEB ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "ok"

@app.route("/memory")
def mem():
    if request.args.get("key") != "titkos123":
        return "no"
    return "<pre>" + open(MEMORY_FILE).read() + "</pre>"

Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

# ---------- RUN ----------
while True:
    try:
        bot.run(DISCORD_TOKEN)
    except:
        import time
        time.sleep(5)
