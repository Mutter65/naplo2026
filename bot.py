import discord
from discord.ext import commands
from datetime import datetime
import os
import requests
from dotenv import load_dotenv
from flask import Flask, request
from threading import Thread
import asyncio
from discord.ui import View, Button, Modal, TextInput

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("❌ A DISCORD_TOKEN nincs beállítva!")

GITHUB_BASE = "https://raw.githubusercontent.com/DarkyBotII/DarkyBotII/main/"
MEMORY_FILE = "memory.txt"

# ---------- FILE ----------
def save_to_memory(line):
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return []
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

# ---------- TXT ----------
def load_txt(filename):
    try:
        url = GITHUB_BASE + filename
        print("📥 LETÖLTÉS:", url)

        r = requests.get(url)
        print("📡 STATUS:", r.status_code)

        if r.status_code == 200:
            lines = [x.strip() for x in r.text.splitlines() if x.strip()]
            print("📄 TARTALOM:", lines)
            return lines
        else:
            print("❌ Nem sikerült betölteni:", filename)

    except Exception as e:
        print("❌ TXT HIBA:", e)

    return []

# ---------- ÚJ SEGÉD ----------
def extract_ids_from_lines(lines):
    # páratlan indexű sorok (1, 3, 5...)
    return [lines[i] for i in range(1, len(lines), 2)]

# ---------- JOGOSULTSÁG ----------
def is_server_allowed(guild_id):
    lines = load_txt("serverid.txt")

    if not lines:
        print("❌ Üres serverid.txt")
        return False

    ids = extract_ids_from_lines(lines)

    allowed = str(guild_id) in ids
    print(f"🔎 SERVER CHECK: {guild_id} -> {allowed}")
    return allowed

def is_user_allowed(member):
    user_lines = load_txt("userid.txt")
    role_names = load_txt("rangid.txt")

    user_ids = extract_ids_from_lines(user_lines)

    print("👤 USER:", member.id)
    print("🎭 USER ROLES:", [role.name for role in member.roles])
    print("📄 TXT ROLES:", role_names)

    # USER ID check
    if str(member.id) in user_ids:
        print("✅ USER ID MATCH")
        return True

    # ROLE check
    for role in member.roles:
        if role.name in role_names:
            print("✅ ROLE MATCH:", role.name)
            return True

    print("❌ USER NEM ENGEDÉLYEZETT")
    return False

# ---------- BOT ----------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    case_insensitive=True
)

# ---------- DEBUG ----------
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    print(f"📩 Üzenet: {message.content} | {message.author}")
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    print("❌ HIBA:", error)
    await ctx.send(f"❌ Hiba történt: {error}")

# ---------- IDŐZÍTÉS ----------
async def schedule_message(channel, send_time, message):
    delay = (send_time - datetime.utcnow()).total_seconds()

    if delay <= 0:
        print("⏰ Régi időpont, kihagyva")
        return

    print(f"⏳ Ütemezve: {delay} mp")
    await asyncio.sleep(delay)

    try:
        await channel.send(f"📢 Emlékeztető:\n{message}")
    except Exception as e:
        print("❌ Küldési hiba:", e)

# ---------- MODAL ----------
class NotificationModal(Modal, title="Értesítés"):
    date = TextInput(label="Dátum (YYYY-MM-DD)")
    time = TextInput(label="Idő (HH:MM)")
    message = TextInput(label="Üzenet", style=discord.TextStyle.long)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_server_allowed(interaction.guild.id):
            return await interaction.response.send_message("❌ Szerver nincs engedélyezve!", ephemeral=True)

        if not is_user_allowed(interaction.user):
            return await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)

        try:
            dt = datetime.strptime(f"{self.date.value} {self.time.value}", "%Y-%m-%d %H:%M")

            channel = discord.utils.get(interaction.guild.text_channels, name="üzenetek")
            if not channel:
                return await interaction.response.send_message("❌ Nincs #üzenetek csatorna!", ephemeral=True)

            line = f"{interaction.guild.id}|{channel.id}|{dt.isoformat()}|{self.message.value}"
            save_to_memory(line)

            asyncio.create_task(schedule_message(channel, dt, self.message.value))

            await interaction.response.send_message("✅ Mentve!", ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"❌ Hiba: {e}", ephemeral=True)

# ---------- GOMBOK ----------
class MenuView(View):
    @discord.ui.button(label="ÉRTESÍTÉS", style=discord.ButtonStyle.green)
    async def notify(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(NotificationModal())

    @discord.ui.button(label="BOLT", style=discord.ButtonStyle.blurple)
    async def shop(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("🛒 Bolt még nincs kész!", ephemeral=True)

# ---------- PARANCSOK ----------
@bot.command()
async def n(ctx):
    if not is_server_allowed(ctx.guild.id):
        return await ctx.send("❌ Ez a szerver nincs engedélyezve!")

    if not is_user_allowed(ctx.author):
        return await ctx.send("❌ Nincs jogosultságod!")

    await ctx.send("Válassz:", view=MenuView())

@bot.command(name="dbinfo")
async def dbinfo(ctx):
    info_lines = load_txt("info.txt")

    if not info_lines:
        return await ctx.send("❌ info.txt nem található vagy üres!")

    embed = discord.Embed(
        title="📘 Információ",
        description="\n".join(info_lines),
        color=discord.Color.blue()
    )

    await ctx.send(embed=embed)

@bot.command()
async def test(ctx):
    await ctx.send("✅ Működök!")

# ---------- READY ----------
@bot.event
async def on_ready():
    print("✅ Bot elindult:", bot.user)

    for line in load_memory():
        try:
            guild_id, channel_id, time_str, msg = line.split("|", 3)
            channel = bot.get_channel(int(channel_id))

            if channel:
                dt = datetime.fromisoformat(time_str)
                asyncio.create_task(schedule_message(channel, dt, msg))

        except Exception as e:
            print("❌ Hiba betöltés:", e)

# ---------- WEBSERVER ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "OK"

@app.route("/memory")
def memory():
    key = request.args.get("key")

    if key != "titkos123":
        return "Tiltva", 403

    if not os.path.exists(MEMORY_FILE):
        return "Nincs adat"

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return f"<pre>{f.read()}</pre>"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

keep_alive()

# ---------- RUN ----------
bot.run(DISCORD_TOKEN)
