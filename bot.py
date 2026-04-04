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
    raise ValueError("❌ A DISCORD_TOKEN nincs beállítva!")

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

    print("🌐 GitHub memory betöltés...")

    try:
        r = requests.get(GITHUB_BASE + "memory.txt", timeout=10)
        if r.status_code == 200:
            return [line.strip() for line in r.text.splitlines() if line.strip()]
    except Exception as e:
        print("GitHub hiba:", e)

    return []

# ---------- TXT ----------
def load_txt(filename):
    try:
        url = GITHUB_BASE + filename
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return [x.strip() for x in r.text.splitlines() if x.strip()]
    except Exception as e:
        print("TXT hiba:", e)
    return []

def extract_ids_from_lines(lines):
    return [lines[i] for i in range(1, len(lines), 2)]

# ---------- JOGOSULTSÁG ----------
def is_server_allowed(guild_id):
    return str(guild_id) in extract_ids_from_lines(load_txt("serverid.txt"))

def is_user_allowed(member):
    user_ids = extract_ids_from_lines(load_txt("userid.txt"))
    roles = load_txt("rangid.txt")

    if str(member.id) in user_ids:
        return True

    return any(r.name in roles for r in member.roles)

# ---------- BOT ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- IDŐZÍTÉS ----------
async def schedule_message(channel, send_time, message, user_id, repeat="once"):
    while True:
        delay = (send_time - datetime.utcnow()).total_seconds()
        if delay <= 0:
            delay = 1

        await asyncio.sleep(delay)

        user_mention = f"<@{user_id}>"

        embed = discord.Embed(
            title="📌 Emlékeztető",
            description=f"**🔴 {message.upper()}**",
            color=discord.Color.red()
        )

        local_time = send_time + timedelta(hours=2)

        embed.add_field(name="👤 Kérte", value=user_mention, inline=False)
        embed.add_field(name="📅 Dátum", value=local_time.strftime("%Y.%m.%d"), inline=True)
        embed.add_field(name="⏰ Idő", value=local_time.strftime("%H:%M"), inline=True)
        embed.set_footer(text=f"Ismétlés: {repeat}")

        await channel.send(content=user_mention, embed=embed)

        if repeat == "once":
            break
        elif repeat == "daily":
            send_time += timedelta(days=1)
        elif repeat == "weekly":
            send_time += timedelta(weeks=1)

# ---------- MODALOK ----------
class NotificationModal(discord.ui.Modal, title="Értesítés"):
    date = discord.ui.TextInput(label="Dátum (YYYY.MM.DD)")
    time = discord.ui.TextInput(label="Idő (HH:MM)")
    message = discord.ui.TextInput(label="Üzenet", style=discord.TextStyle.long)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_server_allowed(interaction.guild.id):
            return await interaction.response.send_message("❌ Szerver tiltva!", ephemeral=True)

        if not is_user_allowed(interaction.user):
            return await interaction.response.send_message("❌ Nincs jogosultság!", ephemeral=True)

        try:
            dt = datetime.strptime(f"{self.date.value} {self.time.value}", "%Y.%m.%d %H:%M")
            dt = dt - timedelta(hours=2)
        except:
            return await interaction.response.send_message("❌ Hibás formátum!", ephemeral=True)

        channel = interaction.channel

        save_to_memory(
            f"{interaction.guild.id}|{channel.id}|{interaction.user.id}|{dt.isoformat()}|{self.message.value}|once"
        )

        asyncio.create_task(
            schedule_message(channel, dt, self.message.value, interaction.user.id, "once")
        )

        await interaction.response.send_message("✅ Mentve!", ephemeral=True)

class RepeatModal(discord.ui.Modal, title="Ismétlődő értesítés"):
    date = discord.ui.TextInput(label="Dátum (YYYY.MM.DD)")
    time = discord.ui.TextInput(label="Idő (HH:MM)")
    message = discord.ui.TextInput(label="Üzenet")
    repeat = discord.ui.TextInput(label="Ismétlés (daily / weekly)")

    async def on_submit(self, interaction: discord.Interaction):
        if not is_user_allowed(interaction.user):
            return await interaction.response.send_message("❌ Nincs jogosultság!", ephemeral=True)

        try:
            dt = datetime.strptime(f"{self.date.value} {self.time.value}", "%Y.%m.%d %H:%M")
            dt = dt - timedelta(hours=2)
        except:
            return await interaction.response.send_message("❌ Hibás dátum!", ephemeral=True)

        repeat_type = self.repeat.value.lower()

        if repeat_type not in ["daily", "weekly"]:
            return await interaction.response.send_message("❌ Csak daily vagy weekly!", ephemeral=True)

        channel = interaction.channel

        save_to_memory(
            f"{interaction.guild.id}|{channel.id}|{interaction.user.id}|{dt.isoformat()}|{self.message.value}|{repeat_type}"
        )

        asyncio.create_task(
            schedule_message(channel, dt, self.message.value, interaction.user.id, repeat_type)
        )

        await interaction.response.send_message("✅ Ismétlődő mentve!", ephemeral=True)

class DeleteModal(discord.ui.Modal, title="Törlés"):
    index = discord.ui.TextInput(label="Sorszám")

    async def on_submit(self, interaction: discord.Interaction):
        all_data = load_memory()
        guild_data = [line for line in all_data if line.startswith(str(interaction.guild.id))]

        try:
            i = int(self.index.value)
            removed = guild_data[i]
        except:
            return await interaction.response.send_message("❌ Hibás szám!", ephemeral=True)

        all_data.remove(removed)

        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            for line in all_data:
                f.write(line + "\n")

        await interaction.response.send_message("🗑️ Törölve!", ephemeral=True)

# ---------- GOMBOK ----------
class MenuView(discord.ui.View):

    @discord.ui.button(label="Értesítés", style=discord.ButtonStyle.green)
    async def notify(self, interaction, button):
        await interaction.response.send_modal(NotificationModal())

    @discord.ui.button(label="Ismétlődő", style=discord.ButtonStyle.blurple)
    async def repeat(self, interaction, button):
        await interaction.response.send_modal(RepeatModal())

    @discord.ui.button(label="Törlés", style=discord.ButtonStyle.red)
    async def delete(self, interaction, button):
        await interaction.response.send_modal(DeleteModal())

    @discord.ui.button(label="Lista", style=discord.ButtonStyle.gray)
    async def list_btn(self, interaction, button):
        data = [line for line in load_memory() if line.startswith(str(interaction.guild.id))]

        if not data:
            return await interaction.response.send_message("📭 Üres", ephemeral=True)

        lines = []
        for i, line in enumerate(data):
            parts = line.split("|")
            if len(parts) < 6:
                continue

            guild_id, channel_id, user_id, time_str, msg, repeat = parts
            dt = datetime.fromisoformat(time_str) + timedelta(hours=2)

            lines.append(f"**{i}** | {dt.strftime('%m.%d %H:%M')} | {repeat} | {msg}")

        await interaction.response.send_message("\n".join(lines[:20]), ephemeral=True)

# ---------- PARANCS ----------
@bot.command()
async def n(ctx):
    if not is_server_allowed(ctx.guild.id):
        return await ctx.send("❌ Szerver tiltva!")

    if not is_user_allowed(ctx.author):
        return await ctx.send("❌ Nincs jogosultság!")

    await ctx.send("Válassz:", view=MenuView())

# ---------- READY ----------
@bot.event
async def on_ready():
    print("✅ Bot elindult:", bot.user)

    for line in load_memory():
        try:
            guild_id, channel_id, user_id, time_str, msg, repeat = line.split("|", 5)

            channel = bot.get_channel(int(channel_id))
            if not channel:
                continue

            dt = datetime.fromisoformat(time_str)

            asyncio.create_task(
                schedule_message(channel, dt, msg, int(user_id), repeat)
            )

        except Exception as e:
            print("Memory hiba:", e)

# ---------- WEB ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive", 200

@app.route("/status")
def status():
    return "online" if bot.is_ready() else "starting"

@app.route("/memory")
def memory():
    if request.args.get("key") != "titkos123":
        return "Tiltva", 403

    if not os.path.exists(MEMORY_FILE):
        return "Nincs adat"

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return f"<pre>{f.read()}</pre>"

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

Thread(target=run_web).start()

# ---------- RUN ----------
while True:
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print("❌ Crash:", e)
        import time
        time.sleep(5)
