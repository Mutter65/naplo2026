import discord
from discord.ext import commands
from datetime import datetime, timedelta
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

GITHUB_BASE = "https://raw.githubusercontent.com/Mutter65/naplo2026/main/"
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
        r = requests.get(url)

        if r.status_code == 200:
            return [x.strip() for x in r.text.splitlines() if x.strip()]
    except:
        pass

    return []

# ---------- SEGÉD ----------
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
async def schedule_message(channel, send_time, message):
    delay = (send_time - datetime.utcnow()).total_seconds()

    if delay <= 0:
        print("⏰ Régi időpont")
        return

    print(f"⏳ Ütemezve: {delay} mp")
    await asyncio.sleep(delay)

    embed = discord.Embed(
        title="📌 Emlékeztető",
        description=message,
        color=discord.Color.yellow()
    )

    # visszaalakítás magyar időre (+2 óra)
    local_time = send_time + timedelta(hours=2)

    embed.add_field(name="📅 Dátum", value=local_time.strftime("%Y.%m.%d"), inline=True)
    embed.add_field(name="⏰ Idő", value=local_time.strftime("%H:%M"), inline=True)
    embed.set_footer(text="Falra tűzve 🧷")

    await channel.send(embed=embed)

# ---------- MODAL ----------
class NotificationModal(Modal, title="Értesítés"):
    date = TextInput(label="Dátum (YYYY.MM.DD)")
    time = TextInput(label="Idő (HH:MM)")
    message = TextInput(label="Üzenet", style=discord.TextStyle.long)

    async def on_submit(self, interaction: discord.Interaction):

        if not is_server_allowed(interaction.guild.id):
            return await interaction.response.send_message("❌ Szerver nincs engedélyezve!", ephemeral=True)

        if not is_user_allowed(interaction.user):
            return await interaction.response.send_message("❌ Nincs jogosultságod!", ephemeral=True)

        date_input = self.date.value.strip()
        time_input = self.time.value.strip()

        try:
            dt = datetime.strptime(f"{date_input} {time_input}", "%Y.%m.%d %H:%M")

            # magyar idő → UTC
            dt = dt - timedelta(hours=2)

        except:
            return await interaction.response.send_message(
                "❌ Hibás formátum!\n\n📅 Dátum: 2026.04.03\n⏰ Idő: 20:55",
                ephemeral=True
            )

        channel = interaction.channel

        save_to_memory(f"{interaction.guild.id}|{channel.id}|{dt.isoformat()}|{self.message.value}")

        asyncio.create_task(schedule_message(channel, dt, self.message.value))

        await interaction.response.send_message("✅ Mentve!", ephemeral=True)

# ---------- GOMB ----------
class MenuView(View):
    @discord.ui.button(label="ÉRTESÍTÉS", style=discord.ButtonStyle.green)
    async def notify(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(NotificationModal())

# ---------- PARANCSOK ----------
@bot.command()
async def n(ctx):
    if not is_server_allowed(ctx.guild.id):
        return await ctx.send("❌ Szerver tiltva!")

    if not is_user_allowed(ctx.author):
        return await ctx.send("❌ Nincs jogosultság!")

    await ctx.send("Válassz:", view=MenuView())

@bot.command()
async def dbinfo(ctx):
    data = load_txt("info.txt")

    if not data:
        return await ctx.send("❌ info.txt nem található!")

    embed = discord.Embed(
        title="📘 Információ",
        description="\n".join(data),
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
        except:
            pass

# ---------- WEB ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "OK"

@app.route("/memory")
def memory():
    if request.args.get("key") != "titkos123":
        return "Tiltva", 403

    if not os.path.exists(MEMORY_FILE):
        return "Nincs adat"

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return f"<pre>{f.read()}</pre>"

Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000))), daemon=True).start()

# ---------- RUN ----------
bot.run(DISCORD_TOKEN)

