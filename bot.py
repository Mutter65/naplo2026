import discord
from discord.ext import commands
from datetime import datetime
import os
import requests
from dotenv import load_dotenv
from flask import Flask, request
from threading import Thread
import asyncio

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GITHUB_BASE = "https://raw.githubusercontent.com/Mutter65/naplo2026/main/"
COPY_FILE = "copy.txt"

# ---------- COPY FILE ----------
def load_copy_data():
    if not os.path.exists(COPY_FILE):
        return []
    with open(COPY_FILE, "r") as f:
        return [line.strip() for line in f if line.strip()]

def save_copy_pair(guild_id, src, dst):
    with open(COPY_FILE, "a") as f:
        f.write(f"{guild_id}|{src}|{dst}\n")

def delete_copy_pair(line):
    data = load_copy_data()
    if line in data:
        data.remove(line)
    with open(COPY_FILE, "w") as f:
        for l in data:
            f.write(l + "\n")

def get_guild_pairs(guild_id):
    return [l for l in load_copy_data() if l.startswith(str(guild_id))]

# ---------- GITHUB LOAD ----------
def load_copy_from_github():
    try:
        r = requests.get(GITHUB_BASE + "copy.txt", timeout=10)
        if r.status_code == 200:
            with open(COPY_FILE, "w", encoding="utf-8") as f:
                f.write(r.text)
            print("✅ copy.txt betöltve GitHub-ról")
    except:
        print("❌ GitHub hiba")

# ---------- ADMIN ----------
def is_admin(user_id):
    try:
        r = requests.get(GITHUB_BASE + "admin.txt", timeout=10)
        if r.status_code == 200:
            data = [x.strip() for x in r.text.splitlines() if x.strip()]
            return str(user_id) in data
    except:
        pass
    return False

# ---------- BOT ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- COPY SYSTEM ----------
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    for line in load_copy_data():
        try:
            guild_id, src, dst = line.split("|")

            if str(message.guild.id) != guild_id:
                continue

            if str(message.channel.id) == src:
                ch = bot.get_channel(int(dst))
                if ch:
                    await ch.send(f"**{message.author}:** {message.content}")
        except:
            continue

    await bot.process_commands(message)

# ---------- UI ----------
class CopyView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.src = None

        self.add_item(self.Source(self))
        self.add_item(self.Target(self))

    class Source(discord.ui.ChannelSelect):
        def __init__(self, parent):
            super().__init__(placeholder="Forrás", channel_types=[discord.ChannelType.text])
            self.parent = parent

        async def callback(self, interaction):
            self.parent.src = self.values[0].id
            await interaction.response.send_message("✅ Forrás kiválasztva", ephemeral=True)

    class Target(discord.ui.ChannelSelect):
        def __init__(self, parent):
            super().__init__(placeholder="Cél", channel_types=[discord.ChannelType.text])
            self.parent = parent

        async def callback(self, interaction):
            dst = self.values[0].id

            if self.parent.src == dst:
                return await interaction.response.send_message("❌ Nem lehet ugyanaz", ephemeral=True)

            save_copy_pair(interaction.guild.id, self.parent.src, dst)

            await interaction.response.send_message("✅ Mentve!", ephemeral=True)

# ---------- DELETE ----------
class DeleteCopySelect(discord.ui.Select):
    def __init__(self, guild_id):
        self.data = get_guild_pairs(guild_id)

        options = []
        for i, line in enumerate(self.data[:25]):
            _, src, dst = line.split("|")
            options.append(discord.SelectOption(
                label=f"{src} ➜ {dst}",
                value=str(i)
            ))

        super().__init__(placeholder="Törlés", options=options)

    async def callback(self, interaction):
        line = self.data[int(self.values[0])]
        delete_copy_pair(line)
        await interaction.response.send_message("🗑️ Törölve", ephemeral=True)

class DeleteCopyView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__()
        self.add_item(DeleteCopySelect(guild_id))

# ---------- MENU ----------
class CopyMenu(discord.ui.View):

    @discord.ui.button(label="Másolás", style=discord.ButtonStyle.blurple)
    async def copy(self, interaction, button):
        if not is_admin(interaction.user.id):
            return await interaction.response.send_message("❌ Nem admin", ephemeral=True)

        await interaction.response.send_message("Válassz:", view=CopyView(), ephemeral=True)

    @discord.ui.button(label="Törlés", style=discord.ButtonStyle.red)
    async def delete(self, interaction, button):
        if not is_admin(interaction.user.id):
            return await interaction.response.send_message("❌ Nem admin", ephemeral=True)

        await interaction.response.send_message("Törlés:", view=DeleteCopyView(interaction.guild.id), ephemeral=True)

    @discord.ui.button(label="Lista", style=discord.ButtonStyle.gray)
    async def list_btn(self, interaction, button):
        if not is_admin(interaction.user.id):
            return await interaction.response.send_message("❌ Nem admin", ephemeral=True)

        data = get_guild_pairs(interaction.guild.id)

        if not data:
            return await interaction.response.send_message("📭 Üres", ephemeral=True)

        embed = discord.Embed(title="📋 Lista", color=discord.Color.green())

        for line in data[:10]:
            _, src, dst = line.split("|")
            embed.add_field(name=f"{src} ➜ {dst}", value="aktív", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="ALL LIST", style=discord.ButtonStyle.green)
    async def all_list(self, interaction, button):

        if not is_admin(interaction.user.id):
            return await interaction.response.send_message("❌ Nem admin", ephemeral=True)

        data = load_copy_data()

        if not data:
            return await interaction.response.send_message("📭 Üres", ephemeral=True)

        embed = discord.Embed(title="🌍 Összes lista", color=discord.Color.gold())

        grouped = {}

        for line in data:
            try:
                gid, src, dst = line.split("|")
                grouped.setdefault(gid, []).append((src, dst))
            except:
                continue

        for gid, pairs in grouped.items():
            guild = bot.get_guild(int(gid))
            name = guild.name if guild else gid

            text = ""
            for src, dst in pairs[:5]:
                text += f"{src} ➜ {dst}\n"

            embed.add_field(name=name, value=text or "nincs", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------- COMMAND ----------
@bot.command()
async def copy(ctx):
    if not is_admin(ctx.author.id):
        return await ctx.send("❌ Nem admin!")

    await ctx.send("📋 Copy panel:", view=CopyMenu())

# ---------- READY ----------
@bot.event
async def on_ready():
    print("Bot fut:", bot.user)
    load_copy_from_github()

# ---------- WEB ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "ok"

@app.route("/copy")
def copy_web():

    if request.args.get("key") != "titkos123":
        return "no"

    data = load_copy_data()

    grouped = {}

    for line in data:
        try:
            gid, src, dst = line.split("|")
            grouped.setdefault(gid, []).append((src, dst))
        except:
            continue

    text = ""

    for gid, pairs in grouped.items():
        text += f"\n=== {gid} ===\n"
        for src, dst in pairs:
            text += f"{src} -> {dst}\n"

    return "<pre>" + text + "</pre>"

Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

# ---------- RUN ----------
while True:
    try:
        bot.run(DISCORD_TOKEN)
    except:
        import time
        time.sleep(5)
