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
    raise ValueError("A DISCORD_TOKEN nincs beállítva!")

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
        r = requests.get(GITHUB_BASE + filename)
        if r.status_code == 200:
            return [x.strip() for x in r.text.splitlines() if x.strip()]
    except:
        pass
    return []

# ---------- SEGÉD (ID + NÉV FELDOLGOZÁS) ----------
def extract_id(line):
    parts = line.split(maxsplit=1)
    return parts[0] if parts else None

# ---------- JOGOSULTSÁG ----------
def is_server_allowed(guild_id):
    lines = load_txt("serverid.txt")

    for line in lines:
        if extract_id(line) == str(guild_id):
            return True

    return False


def is_user_allowed(member):
    lines = load_txt("userid.txt")

    for line in lines:
        if extract_id(line) == str(member.id):
            return True

    for role in member.roles:
        if role.name in load_txt("rangid.txt"):
            return True

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

# ---------- ERROR DEBUG ----------
@bot.event
async def on_command_error(ctx, error):
    print("HIBA:", error)

# ---------- IDŐZÍTÉS ----------
async def schedule_message(channel, send_time, message):
    delay = (send_time - datetime.utcnow()).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)
    await channel.send(f"📢 Emlékeztető:\n{message}")

# ---------- MODAL ----------
class NotificationModal(Modal, title="Értesítés"):
    date = TextInput(label="Dátum (YYYY-MM-DD)")
    time = TextInput(label="Idő (HH:MM)")
    message = TextInput(label="Üzenet", style=discord.TextStyle.long)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_server_allowed(interaction.guild.id):
            return await interaction.response.send_message("Nincs engedély", ephemeral=True)

        if not is_user_allowed(interaction.user):
            return await interaction.response.send_message("Nincs jog", ephemeral=True)

        try:
            dt = datetime.strptime(f"{self.date.value} {self.time.value}", "%Y-%m-%d %H:%M")

            channel = discord.utils.get(interaction.guild.text_channels, name="üzenetek")
            if not channel:
                return await interaction.response.send_message("❌ Nincs #üzenetek csatorna", ephemeral=True)

            line = f"{interaction.guild.id}|{channel.id}|{dt.isoformat()}|{self.message.value}"
            save_to_memory(line)

            asyncio.create_task(schedule_message(channel, dt, self.message.value))

            await interaction.response.send_message("✅ Mentve!", ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"Hiba: {e}", ephemeral=True)

# ---------- GOMBOK ----------
class MenuView(View):
    @discord.ui.button(label="ÉRTESÍTÉS", style=discord.ButtonStyle.green)
    async def notify(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(NotificationModal())

    @discord.ui.button(label="BOLT", style=discord.ButtonStyle.blurple)
    async def shop(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("🛒 Bolt később", ephemeral=True)

# ---------- PARANCSOK ----------
@bot.command()
async def n(ctx):
    print("Guild:", ctx.guild.id)
    print("User:", ctx.author.id)

    if not is_server_allowed(ctx.guild.id):
        print("❌ SERVER NEM ENGEDÉLYEZETT")
        return

    if not is_user_allowed(ctx.author):
        print("❌ USER NEM ENGEDÉLYEZETT")
        return

    await ctx.send("Válassz:", view=MenuView())


@bot.command()
async def p(ctx):
    if not is_server_allowed(ctx.guild.id):
        return
    if not is_user_allowed(ctx.author):
        return

    info_lines = load_txt("info.txt")

    if not info_lines:
        return await ctx.send("❌ info.txt nem található!")

    embed = discord.Embed(
        title="📘 Információ",
        description="\n".join(info_lines),
        color=discord.Color.blue()
    )

    await ctx.send(embed=embed)


# ---------- TESZT PARANCS ----------
@bot.command()
async def test(ctx):
    await ctx.send("✅ Működök!")


# ---------- READY ----------
@bot.event
async def on_ready():
    print("Bot elindult:", bot.user)

    for line in load_memory():
        try:
            guild_id, channel_id, time_str, msg = line.split("|", 3)
            channel = bot.get_channel(int(channel_id))

            if channel:
                dt = datetime.fromisoformat(time_str)
                asyncio.create_task(schedule_message(channel, dt, msg))

        except Exception as e:
            print("Hiba betöltés:", e)

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

