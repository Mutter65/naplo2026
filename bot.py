import discord
from discord.ext import commands
import os
import requests
from dotenv import load_dotenv
from flask import Flask
from threading import Thread
import time

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GITHUB_BASE = "https://raw.githubusercontent.com/Mutter65/naplo2026/main/"
COPY_FILE = "copy.txt"

# ---------- FILE ----------
def load_copy_data():
    if not os.path.exists(COPY_FILE):
        return []
    with open(COPY_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def save_copy_pair(guild_id, src, dst, mode):
    line = f"{guild_id}|{src}|{dst}|{mode}"
    data = load_copy_data()

    if line not in data:
        with open(COPY_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")

def delete_copy_pair(line):
    data = load_copy_data()
    if line in data:
        data.remove(line)
    with open(COPY_FILE, "w", encoding="utf-8") as f:
        for l in data:
            f.write(l + "\n")

def get_guild_pairs(guild_id):
    return [l for l in load_copy_data() if l.startswith(str(guild_id))]

# ---------- GITHUB ----------
def load_copy_from_github():
    try:
        r = requests.get(GITHUB_BASE + "copy.txt", timeout=10)
        if r.status_code == 200:
            with open(COPY_FILE, "w", encoding="utf-8") as f:
                f.write(r.text)
            print("✅ GitHub copy betöltve")
    except Exception as e:
        print("❌ GitHub hiba:", e)

# ---------- ADMIN ----------
def is_admin(user_id):
    try:
        r = requests.get(GITHUB_BASE + "admin.txt", timeout=10)
        if r.status_code == 200:
            admins = [line.strip() for line in r.text.splitlines()]
            return str(user_id) in admins
    except:
        pass
    return False

# ---------- BOT ----------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- COPY SYSTEM ----------
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    for line in load_copy_data():
        try:
            parts = line.split("|")

            if len(parts) == 3:
                guild_id, src, dst = parts
                mode = "all"
            else:
                guild_id, src, dst, mode = parts

            if str(message.guild.id) != guild_id:
                continue

            if str(message.channel.id) != src:
                continue

            if mode == "bot":
                continue

            ch = bot.get_channel(int(dst))
            if ch:
                await ch.send(f"**{message.author}:** {message.content}")

        except:
            continue

    await bot.process_commands(message)

# ---------- MODE SELECT ----------
class ModeSelectView(discord.ui.View):

    @discord.ui.button(label="🤖 Csak BOT", style=discord.ButtonStyle.blurple)
    async def bot_only(self, interaction, button):
        await interaction.response.defer()
        await interaction.followup.send(
            "Válassz csatornákat:",
            view=CopyView("bot"),
            ephemeral=False
        )

    @discord.ui.button(label="🌍 Minden", style=discord.ButtonStyle.green)
    async def all_messages(self, interaction, button):
        await interaction.response.defer()
        await interaction.followup.send(
            "Válassz csatornákat:",
            view=CopyView("all"),
            ephemeral=False
        )

# ---------- COPY VIEW ----------
class CopyView(discord.ui.View):
    def __init__(self, mode):
        super().__init__(timeout=120)
        self.mode = mode
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
            if not self.parent.src:
                return await interaction.response.send_message("❌ Előbb válassz forrást!", ephemeral=True)

            dst = self.values[0].id

            if self.parent.src == dst:
                return await interaction.response.send_message("❌ Nem lehet ugyanaz", ephemeral=True)

            save_copy_pair(interaction.guild.id, self.parent.src, dst, self.parent.mode)

            await interaction.response.send_message("✅ Mentve!", ephemeral=True)

# ---------- DELETE ----------
class DeleteCopySelect(discord.ui.Select):
    def __init__(self, guild_id):
        self.data = get_guild_pairs(guild_id)

        options = []
        for i, line in enumerate(self.data[:25]):
            parts = line.split("|")
            _, src, dst, mode = parts if len(parts) == 4 else (*parts, "all")

            mode_text = "🤖 BOT" if mode == "bot" else "🌍 ALL"

            options.append(discord.SelectOption(
                label=f"{src} ➜ {dst}",
                description=mode_text,
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

        await interaction.response.send_message(
            "Válassz módot:",
            view=ModeSelectView(),
            ephemeral=True
        )

    @discord.ui.button(label="Törlés", style=discord.ButtonStyle.red)
    async def delete(self, interaction, button):
        if not is_admin(interaction.user.id):
            return await interaction.response.send_message("❌ Nem admin", ephemeral=True)

        await interaction.response.send_message(
            "Törlés:",
            view=DeleteCopyView(interaction.guild.id),
            ephemeral=True
        )

    @discord.ui.button(label="Lista", style=discord.ButtonStyle.gray)
    async def list_btn(self, interaction, button):
        if not is_admin(interaction.user.id):
            return await interaction.response.send_message("❌ Nem admin", ephemeral=True)

        data = get_guild_pairs(interaction.guild.id)

        if not data:
            return await interaction.response.send_message("📭 Üres", ephemeral=True)

        embed = discord.Embed(title="📋 Lista", color=discord.Color.green())

        for line in data[:10]:
            parts = line.split("|")
            _, src, dst, mode = parts if len(parts) == 4 else (*parts, "all")
            mode_text = "🤖 BOT" if mode == "bot" else "🌍 ALL"

            embed.add_field(name=f"{src} ➜ {dst}", value=mode_text, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------- COMMAND ----------
@bot.command(aliases=["n"])
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

Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

# ---------- RUN ----------
while True:
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print("Újraindul...", e)
        time.sleep(5)
