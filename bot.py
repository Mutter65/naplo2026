import discord
from discord.ext import commands
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import requests
from dotenv import load_dotenv
from flask import Flask, request
from threading import Thread
import asyncio
import io
import re
import time
import traceback

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# ---------- FORTNITE STATUS ----------
FORTNITE_CHANNEL_ID = int(os.getenv("FORTNITE_CHANNEL_ID", "0"))

FORTNITE_STATUS_URL = "https://status.epicgames.com/api/v2/summary.json"
FORTNITE_CHECK_INTERVAL = 600

fortnite_last_state = None

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
    except Exception:
        pass

    return []


def load_txt(filename):
    try:
        r = requests.get(GITHUB_BASE + filename, timeout=10)

        if r.status_code == 200:
            return [x.strip() for x in r.text.splitlines() if x.strip()]

    except Exception:
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
    return [
        lines[i]
        for i in range(1, len(lines), 2)
        if lines[i].isdigit()
    ]


# ---------- JOG ----------
def is_server_allowed(guild_id):
    return str(guild_id) in extract_ids_from_lines(
        load_txt("serverid.txt")
    )


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
    except Exception:
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

        except Exception:
            continue

    return count


def get_user_limit_info(user_id):
    limit = get_daily_limit()
    current = count_user_today(user_id)

    return current, limit, max(0, limit - current)


# ---------- BOT ----------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ---------- CHECK ----------
def check_access(interaction=None, ctx=None):

    if interaction:

        if not interaction.guild:
            return False, "❌ Ez a parancs csak szerveren használható!"

        if not is_server_allowed(interaction.guild.id):
            return False, "❌ Ez a szerver nincs engedélyezve!"

        if not is_user_allowed(interaction.user):
            return False, "❌ Nincs jogosultságod!"

    elif ctx:

        if not ctx.guild:
            return False, "❌ Ez a parancs csak szerveren használható!"

        if not is_server_allowed(ctx.guild.id):
            return False, "❌ Ez a szerver nincs engedélyezve!"

        if not is_user_allowed(ctx.author):
            return False, "❌ Nincs jogosultságod!"

    return True, None


# ---------- SCHEDULE ----------
async def schedule_message(
    channel,
    send_time,
    message,
    user_id,
    repeat="once",
    target_type="user"
):

    while True:

        if send_time.tzinfo is None:
            send_time = send_time.replace(
                tzinfo=ZoneInfo("UTC")
            )

        delay = (
            send_time -
            datetime.now(ZoneInfo("UTC"))
        ).total_seconds()

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

        local = send_time.astimezone(
            ZoneInfo("Europe/Budapest")
        )

        repeat_text = {
            "once": "Egyszeri",
            "daily": "Napi",
            "weekly": "Heti"
        }.get(repeat, repeat)

        embed.add_field(
            name="👤 Kérte",
            value=mention,
            inline=False
        )

        embed.add_field(
            name="📅 Dátum",
            value=local.strftime("%Y.%m.%d"),
            inline=True
        )

        embed.add_field(
            name="⏰ Idő",
            value=local.strftime("%H:%M"),
            inline=True
        )

        embed.set_footer(
            text=f"🔁 {repeat_text} értesítés"
        )

        await channel.send(
            content=mention,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                everyone=True,
                users=True
            )
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
        return [
            line
            for line in data
            if line.startswith(str(guild_id))
        ]

    return [
        line
        for line in data
        if (
            line.startswith(str(guild_id))
            and f"|{user_id}|" in line
        )
    ]


# ==========================================================
# MODALS
# ==========================================================

class NotificationModal(
    discord.ui.Modal,
    title="Értesítés"
):

    def __init__(self):
        super().__init__()

        self.target_type = "user"

    date = discord.ui.TextInput(
        label="📅 Dátum (2026.04.03)"
    )

    time = discord.ui.TextInput(
        label="⏰ Idő (20:55)"
    )

    message = discord.ui.TextInput(
        label="📝 Üzenet"
    )

    async def on_submit(self, interaction):

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:
            return await interaction.response.send_message(
                msg,
                ephemeral=True
            )

        try:

            dt_local = datetime.strptime(
                f"{self.date.value} {self.time.value}",
                "%Y.%m.%d %H:%M"
            )

        except ValueError:

            return await interaction.response.send_message(
                "❌ Hibás dátum vagy idő formátum.",
                ephemeral=True
            )

        dt_local = dt_local.replace(
            tzinfo=ZoneInfo("Europe/Budapest")
        )

        dt = dt_local.astimezone(
            ZoneInfo("UTC")
        )

        save_to_memory(
            f"{interaction.guild.id}|"
            f"{interaction.channel.id}|"
            f"{interaction.user.id}|"
            f"{dt.isoformat()}|"
            f"{self.message.value}|once"
        )

        asyncio.create_task(
            schedule_message(
                interaction.channel,
                dt,
                self.message.value,
                interaction.user.id,
                "once",
                self.target_type
            )
        )

        await interaction.response.send_message(
            "✅ Mentve!",
            ephemeral=True
        )


class RepeatModal(discord.ui.Modal):

    def __init__(self, repeat):

        super().__init__(
            title="Ismétlődő értesítés"
        )

        self.repeat = repeat

        self.date = discord.ui.TextInput(
            label="📅 Dátum (2026.04.03)"
        )

        self.time = discord.ui.TextInput(
            label="⏰ Idő (20:55)"
        )

        self.message = discord.ui.TextInput(
            label="📝 Üzenet"
        )

        self.add_item(self.date)
        self.add_item(self.time)
        self.add_item(self.message)

    async def on_submit(self, interaction):

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:
            return await interaction.response.send_message(
                msg,
                ephemeral=True
            )

        try:

            dt_local = datetime.strptime(
                f"{self.date.value} {self.time.value}",
                "%Y.%m.%d %H:%M"
            )

        except ValueError:

            return await interaction.response.send_message(
                "❌ Hibás dátum vagy idő formátum.",
                ephemeral=True
            )

        dt_local = dt_local.replace(
            tzinfo=ZoneInfo("Europe/Budapest")
        )

        dt = dt_local.astimezone(
            ZoneInfo("UTC")
        )

        save_to_memory(
            f"{interaction.guild.id}|"
            f"{interaction.channel.id}|"
            f"{interaction.user.id}|"
            f"{dt.isoformat()}|"
            f"{self.message.value}|"
            f"{self.repeat}"
        )

        asyncio.create_task(
            schedule_message(
                interaction.channel,
                dt,
                self.message.value,
                interaction.user.id,
                self.repeat
            )
        )

        await interaction.response.send_message(
            "✅ Mentve!",
            ephemeral=True
        )


# ==========================================================
# SELECT / VIEWS
# ==========================================================

class RepeatSelect(discord.ui.Select):

    def __init__(self):

        super().__init__(
            placeholder="Ismétlés típusa",
            options=[
                discord.SelectOption(
                    label="Napi",
                    value="daily"
                ),
                discord.SelectOption(
                    label="Heti",
                    value="weekly"
                )
            ]
        )

    async def callback(self, interaction):

        await interaction.response.send_modal(
            RepeatModal(self.values[0])
        )


class RepeatView(discord.ui.View):

    def __init__(self):

        super().__init__()

        self.add_item(
            RepeatSelect()
        )

    async def interaction_check(self, interaction):

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:

            await interaction.response.send_message(
                msg,
                ephemeral=True
            )

            return False

        return True


class DeleteSelect(discord.ui.Select):

    def __init__(self, data):

        self.data = data

        options = []

        for i, line in enumerate(data[:25]):

            try:

                parts = line.split("|")

                _, _, _, time_str, msg, repeat = parts

                dt = datetime.fromisoformat(
                    time_str
                )

                if dt.tzinfo is None:
                    dt = dt.replace(
                        tzinfo=ZoneInfo("UTC")
                    )

                dt = dt.astimezone(
                    ZoneInfo("Europe/Budapest")
                )

                options.append(
                    discord.SelectOption(
                        label=(
                            f"{dt.strftime('%m.%d %H:%M')}"
                            f" • {repeat}"
                        ),
                        description=msg[:50],
                        value=str(i)
                    )
                )

            except Exception:
                continue

        if not options:

            options.append(
                discord.SelectOption(
                    label="Nincs törölhető adat",
                    value="none"
                )
            )

        super().__init__(
            placeholder="Törlendő kiválasztása",
            options=options
        )

    async def callback(self, interaction):

        if self.values[0] == "none":

            return await interaction.response.send_message(
                "📭 Nincs törölhető adat.",
                ephemeral=True
            )

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:

            return await interaction.response.send_message(
                msg,
                ephemeral=True
            )

        all_data = load_memory()

        selected = self.data[
            int(self.values[0])
        ]

        if selected in all_data:
            all_data.remove(selected)

        with open(
            MEMORY_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            for line in all_data:
                f.write(line + "\n")

        await interaction.response.send_message(
            "🗑️ Törölve!",
            ephemeral=True
        )


class DeleteView(discord.ui.View):

    def __init__(self, data):

        super().__init__()

        self.add_item(
            DeleteSelect(data)
        )

    async def interaction_check(self, interaction):

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:

            await interaction.response.send_message(
                msg,
                ephemeral=True
            )

            return False

        return True


# ==========================================================
# YOUTUBE
# ==========================================================

class YoutubeSelect(discord.ui.Select):

    def __init__(self):

        users = load_youtube_users()

        options = [
            discord.SelectOption(
                label=name,
                value=filename
            )
            for name, filename in users[:25]
        ]

        if not options:

            options.append(
                discord.SelectOption(
                    label="Nincs YouTube csatorna",
                    value="none"
                )
            )

        super().__init__(
            custom_id="youtube_select",
            placeholder="Válassz YouTube csatornát",
            options=options
        )

    async def callback(self, interaction):

        filename = self.values[0]

        if filename == "none":

            return await interaction.response.send_message(
                "❌ Nincs beállított YouTube csatorna.",
                ephemeral=True
            )

        data = load_txt(
            f"{filename}.txt"
        )

        if not data:

            return await interaction.response.send_message(
                "❌ Nem található adat.",
                ephemeral=True
            )

        embed = discord.Embed(
            title=f"📺 {filename}",
            description="\n".join(data)[:4096],
            color=discord.Color.red()
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


class YoutubeView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        self.add_item(
            YoutubeSelect()
        )


# ==========================================================
# TWITCH
# ==========================================================

class TwitchSelect(discord.ui.Select):

    def __init__(self):

        users = load_twitch_users()

        options = [
            discord.SelectOption(
                label=name,
                value=username
            )
            for name, username in users[:25]
        ]

        if not options:

            options.append(
                discord.SelectOption(
                    label="Nincs Twitch csatorna",
                    value="none"
                )
            )

        super().__init__(
            custom_id="twitch_select",
            placeholder="Válassz Twitch csatornát",
            options=options
        )

    async def callback(self, interaction):

        username = self.values[0]

        if username == "none":

            return await interaction.response.send_message(
                "❌ Nincs beállított Twitch csatorna.",
                ephemeral=True
            )

        data = load_txt(
            f"{username}.txt"
        )

        if not data:

            return await interaction.response.send_message(
                "❌ Nem található adat.",
                ephemeral=True
            )

        embed = discord.Embed(
            title=f"🎮 {username}",
            description="\n".join(data)[:4096],
            color=discord.Color.purple()
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


class TwitchView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        self.add_item(
            TwitchSelect()
        )


# ==========================================================
# NOTIFY CHOICE
# ==========================================================

class NotifyChoiceView(discord.ui.View):

    @discord.ui.button(
        label="Saját magam",
        style=discord.ButtonStyle.green
    )
    async def me(
        self,
        interaction,
        button
    ):

        modal = NotificationModal()

        modal.target_type = "user"

        await interaction.response.send_modal(
            modal
        )

    @discord.ui.button(
        label="@everyone",
        style=discord.ButtonStyle.red
    )
    async def everyone(
        self,
        interaction,
        button
    ):

        modal = NotificationModal()

        modal.target_type = "everyone"

        await interaction.response.send_modal(
            modal
        )


# ==========================================================
# MENU
# ==========================================================

class MenuView(discord.ui.View):

    async def interaction_check(self, interaction):

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:

            await interaction.response.send_message(
                msg,
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="Értesítés",
        style=discord.ButtonStyle.green
    )
    async def notify(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "Kit pingeljen az értesítés?",
            view=NotifyChoiceView(),
            ephemeral=True
        )

    @discord.ui.button(
        label="Ismétlődő",
        style=discord.ButtonStyle.blurple
    )
    async def repeat(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "Válassz:",
            view=RepeatView(),
            ephemeral=True
        )

    @discord.ui.button(
        label="Törlés",
        style=discord.ButtonStyle.red
    )
    async def delete(
        self,
        interaction,
        button
    ):

        data = get_user_data(
            interaction.guild.id,
            interaction.user.id
        )

        if not data:

            return await interaction.response.send_message(
                "📭 Nincs adat",
                ephemeral=True
            )

        await interaction.response.send_message(
            "Válassz:",
            view=DeleteView(data),
            ephemeral=True
        )

    @discord.ui.button(
        label="Lista",
        style=discord.ButtonStyle.gray
    )
    async def list_btn(
        self,
        interaction,
        button
    ):

        data = get_user_data(
            interaction.guild.id,
            interaction.user.id
        )

        if not data:

            return await interaction.response.send_message(
                "📭 Üres",
                ephemeral=True
            )

        embed = discord.Embed(
            title="📋 Lista",
            color=discord.Color.green()
        )

        for i, line in enumerate(data[:10]):

            try:

                parts = line.split("|")

                _, _, _, time_str, msg, repeat = parts

                dt = datetime.fromisoformat(
                    time_str
                )

                if dt.tzinfo is None:
                    dt = dt.replace(
                        tzinfo=ZoneInfo("UTC")
                    )

                dt = dt.astimezone(
                    ZoneInfo("Europe/Budapest")
                )

                embed.add_field(
                    name=(
                        f"{i}. "
                        f"{dt.strftime('%m.%d %H:%M')}"
                    ),
                    value=f"{repeat} | {msg}",
                    inline=False
                )

            except Exception:
                continue

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


# ==========================================================
# JEGYZET
# ==========================================================

class JegyzetModal(
    discord.ui.Modal,
    title="📝 Új TXT"
):

    cim = discord.ui.TextInput(
        label="Jegyzet címe:",
        placeholder="Írd be a jegyzet címét...",
        required=True,
        max_length=100
    )

    jegyzet = discord.ui.TextInput(
        label="Jegyzet szövege",
        placeholder="Írd ide a szöveget...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=4000
    )

    async def on_submit(self, interaction):

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:

            return await interaction.response.send_message(
                msg,
                ephemeral=True
            )

        cim = str(
            self.cim.value
        ).strip()

        text_content = str(
            self.jegyzet.value
        ).strip()

        if not cim:

            return await interaction.response.send_message(
                "❌ A jegyzet címe nem lehet üres.",
                ephemeral=True
            )

        if not text_content:

            return await interaction.response.send_message(
                "❌ A TXT nem lehet üres.",
                ephemeral=True
            )

        sender_name = (
            interaction.user.display_name
        )

        now = datetime.now(
            ZoneInfo("Europe/Budapest")
        )

        filename = (
            f"txt_"
            f"{now.strftime('%Y%m%d_%H%M%S')}_"
            f"{interaction.user.id}.txt"
        )

        txt_file = discord.File(
            io.BytesIO(
                text_content.encode("utf-8")
            ),
            filename=filename
        )

        thread_name = (
            f"📝 {cim} • {sender_name}"
        )[:100]

        embed = discord.Embed(
            title=f"📝 {cim}",
            description=(
                "✨ **Új privát TXT érkezett**"
            ),
            color=discord.Color.blurple(),
            timestamp=now
        )

        preview = (
            text_content
            if len(text_content) <= 900
            else text_content[:900] + "…"
        )

        embed.add_field(
            name="💭 Tartalom",
            value=(
                f"```text\n"
                f"{preview}\n"
                f"```"
            ),
            inline=False
        )

        embed.add_field(
            name="📄 TXT fájl",
            value=(
                "⬇️ **A TXT csatolmányként "
                "letölthető.**"
            ),
            inline=False
        )

        embed.add_field(
            name="👤 Küldő",
            value=interaction.user.mention,
            inline=True
        )

        embed.add_field(
            name="🕐 Időpont",
            value=now.strftime(
                "%Y.%m.%d. %H:%M:%S"
            ),
            inline=True
        )

        embed.set_footer(
            text=(
                "🔒 Privát TXT • Csak az "
                "engedélyezett személyek látják"
            )
        )

        try:

            channel = interaction.channel

            if not isinstance(
                channel,
                discord.TextChannel
            ):

                return await interaction.response.send_message(
                    "❌ A !txt parancsot normál "
                    "szöveges csatornában kell használni.",
                    ephemeral=True
                )

            thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=60
            )

            await thread.add_user(
                interaction.user
            )

            for user_id in TXT_PRIVATE_USER_IDS:

                if user_id == interaction.user.id:
                    continue

                try:

                    user = bot.get_user(
                        user_id
                    )

                    if user is None:

                        user = await bot.fetch_user(
                            user_id
                        )

                    await thread.add_user(
                        user
                    )

                except Exception as e:

                    print(
                        f"⚠️ TXT felhasználó hozzáadási "
                        f"hiba ({user_id}): "
                        f"{type(e).__name__}: {e}",
                        flush=True
                    )

            header_embed = discord.Embed(
                title=f"📌 {cim}",
                description=(
                    f"**👤 {sender_name}**"
                ),
                color=discord.Color.blurple()
            )

            await thread.send(
                embed=header_embed
            )

            sent_message = await thread.send(
                embed=embed,
                file=txt_file
            )

            if sent_message.attachments:

                file_url = (
                    sent_message.attachments[0].url
                )

                link_embed = discord.Embed(
                    title="📎 TXT fájl",
                    description=(
                        f"🔗 **[TXT megnyitása / "
                        f"letöltése]({file_url})**"
                    ),
                    color=discord.Color.dark_blue()
                )

                link_embed.set_footer(
                    text="A TXT fájl UTF-8 kódolású."
                )

                await thread.send(
                    embed=link_embed
                )

            await interaction.response.send_message(
                "✅ A jegyzet elkészült és privát "
                "gondolatmenetben elmentve.",
                ephemeral=True
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ Nem sikerült létrehozni "
                "a privát TXT-szálat. "
                "Ellenőrizd a bot privát thread "
                "jogosultságait.",
                ephemeral=True
            )

        except Exception as e:

            print(
                f"❌ TXT privát thread hiba: "
                f"{type(e).__name__}: {e}",
                flush=True
            )

            await interaction.response.send_message(
                "❌ Hiba történt a privát TXT-szál "
                "létrehozásakor.",
                ephemeral=True
            )


class JegyzetView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=600
        )

    @discord.ui.button(
        label="Mentés",
        emoji="💾",
        style=discord.ButtonStyle.success
    )
    async def mentes(
        self,
        interaction,
        button
    ):

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:

            return await interaction.response.send_message(
                msg,
                ephemeral=True
            )

        await interaction.response.send_modal(
            JegyzetModal()
        )


def build_jegyzet_panel():

    embed = discord.Embed(
        title="📝 TXT",
        description=(
            "**Készíts egy privát TXT-t!**\n\n"
            "Nyomd meg a **💾 Mentés** gombot, "
            "írd be a szöveget, majd a bot "
            "automatikusan létrehoz egy "
            "**privát TXT-szálat**.\n\n"
            "⬇️ A mentés után a TXT fájl "
            "letölthető lesz az üzenetből."
        ),
        color=discord.Color.blurple()
    )

    embed.set_footer(
        text="A TXT maximum 4000 karakter lehet."
    )

    return embed


# ==========================================================
# SPAR / DM CALCULATOR
# ==========================================================

class SparModal(
    discord.ui.Modal,
    title="SPAR számítás"
):

    ertek = discord.ui.TextInput(
        label="Érték (HUF)",
        placeholder="Pl. 3000",
        required=True,
        max_length=12
    )

    kedvezmeny = discord.ui.TextInput(
        label="Kedvezmény (%)",
        placeholder="Pl. 20",
        required=False,
        max_length=6
    )

    async def on_submit(self, interaction):

        try:

            eredeti = float(
                str(self.ertek.value)
                .replace(",", ".")
                .replace(" ", "")
            )

            kedvezmeny = (
                float(
                    str(self.kedvezmeny.value)
                    .replace(",", ".")
                    .replace(" ", "")
                )
                if str(
                    self.kedvezmeny.value
                ).strip()
                else 0
            )

            if (
                eredeti < 0
                or not 0 <= kedvezmeny <= 100
            ):
                raise ValueError

            megtakaritas = (
                eredeti * kedvezmeny / 100
            )

            kedvezmenyes = (
                eredeti - megtakaritas
            )

            embed = discord.Embed(
                title="🛒 SPAR",
                description="**Kedvezmény számítása**",
                color=discord.Color.red()
            )

            embed.add_field(
                name="💰 Eredeti ára",
                value=(
                    f"**{eredeti:,.0f} HUF**"
                    .replace(",", " ")
                ),
                inline=False
            )

            embed.add_field(
                name="🏷️ Kedvezményes ár",
                value=(
                    f"**{kedvezmenyes:,.0f} HUF**"
                    .replace(",", " ")
                ),
                inline=False
            )

            embed.add_field(
                name="💵 Ennyit spórolsz",
                value=(
                    f"**{megtakaritas:,.0f} HUF**"
                    .replace(",", " ")
                ),
                inline=False
            )

            embed.set_footer(
                text=f"SPAR • {kedvezmeny:g}% kedvezmény"
            )

            await interaction.response.send_message(
                embed=embed,
                ephemeral=True
            )

        except ValueError:

            await interaction.response.send_message(
                "❌ Kérlek, érvényes számokat adj meg! "
                "A kedvezmény 0–100% között lehet.",
                ephemeral=True
            )


class DmModal(
    discord.ui.Modal,
    title="dm számítás"
):

    ertek = discord.ui.TextInput(
        label="Érték (HUF)",
        placeholder="Pl. 3000",
        required=True,
        max_length=12
    )

    pont_szorzo = discord.ui.TextInput(
        label="Pont szorzó (ha van!)",
        placeholder="Pl. 20",
        required=False,
        max_length=8
    )

    async def on_submit(self, interaction):

        try:

            eredeti = float(
                str(self.ertek.value)
                .replace(",", ".")
                .replace(" ", "")
            )

            szorzo_text = (
                str(
                    self.pont_szorzo.value
                ).strip()
            )

            szorzo = (
                float(
                    szorzo_text
                    .replace(",", ".")
                    .replace(" ", "")
                )
                if szorzo_text
                else 1
            )

            if eredeti < 0 or szorzo < 0:
                raise ValueError

            alap_pont = eredeti / 300

            pont = int(
                alap_pont * szorzo
            )

            sporolas = pont * 3

            embed = discord.Embed(
                title="🛍️ DM",
                description="**Pontszámítás**",
                color=discord.Color.purple()
            )

            embed.add_field(
                name="💰 Eredeti ára",
                value=(
                    f"**{eredeti:,.0f} HUF**"
                    .replace(",", " ")
                ),
                inline=False
            )

            embed.add_field(
                name="⭐ Ennyi pontértéket kapsz vissza",
                value=(
                    f"**{pont:,.0f} Pont**"
                    .replace(",", " ")
                ),
                inline=False
            )

            embed.add_field(
                name="💵 Ennyit spórolsz",
                value=(
                    f"**{sporolas:,.0f} HUF**"
                    .replace(",", " ")
                ),
                inline=False
            )

            embed.set_footer(
                text=(
                    f"DM • {szorzo:g}× pontszorzó • "
                    "300 HUF = 1 alap pont • "
                    "1 pont = 3 Ft"
                )
            )

            await interaction.response.send_message(
                embed=embed,
                ephemeral=True
            )

        except ValueError:

            await interaction.response.send_message(
                "❌ Kérlek, érvényes számokat adj meg!",
                ephemeral=True
            )


class SparDmView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=300
        )

    @discord.ui.button(
        label="SPAR számítás",
        emoji="🛒",
        style=discord.ButtonStyle.danger
    )
    async def spar(
        self,
        interaction,
        button
    ):

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:

            return await interaction.response.send_message(
                msg,
                ephemeral=True
            )

        await interaction.response.send_modal(
            SparModal()
        )

    @discord.ui.button(
        label="dm számítás",
        emoji="🛍️",
        style=discord.ButtonStyle.primary
    )
    async def dm(
        self,
        interaction,
        button
    ):

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:

            return await interaction.response.send_message(
                msg,
                ephemeral=True
            )

        await interaction.response.send_modal(
            DmModal()
        )


def build_spar_dm_panel():

    embed = discord.Embed(
        title="🧮 SPAR • DM",
        description=(
            "**Válaszd ki, mit szeretnél "
            "kiszámolni.**"
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🛒 SPAR",
        value=(
            "Érték (HUF) + Kedvezmény (%)"
        ),
        inline=False
    )

    embed.add_field(
        name="🛍️ DM",
        value=(
            "Érték (HUF) + Pont szorzó "
            "(ha van!)"
        ),
        inline=False
    )

    embed.set_footer(
        text=(
            "A gomb megnyomása után "
            "megadhatod az értékeket."
        )
    )

    return embed


# ==========================================================
# FOXPOST
# ==========================================================

FOXPOST_TARGET_USER_ID = 419451608485593089

TXT_PRIVATE_USER_IDS = {
    419451608485593089,
    815969322346348606
}


class FoxModal(
    discord.ui.Modal,
    title="📦 Foxpost adatok"
):

    nev = discord.ui.TextInput(
        label="Név",
        placeholder="Add meg a nevet",
        required=True,
        max_length=100
    )

    email = discord.ui.TextInput(
        label="E-mail",
        placeholder="Add meg az e-mail címet",
        required=True,
        max_length=200
    )

    mobil = discord.ui.TextInput(
        label="Mobil",
        placeholder="Pl. +36 30 123 4567",
        required=True,
        max_length=30
    )

    szekreny = discord.ui.TextInput(
        label="Foxpost szekrény címe",
        placeholder="Add meg a Foxpost szekrény címét",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=300
    )

    async def on_submit(self, interaction):

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:

            return await interaction.response.send_message(
                msg,
                ephemeral=True
            )

        sender_name = (
            interaction.user.display_name
        )

        embed = discord.Embed(
            title=f"**{sender_name}**",
            description=(
                "📦 **Foxpost adatok érkeztek**"
            ),
            color=discord.Color.orange()
        )

        embed.add_field(
            name="👤 Név",
            value=str(
                self.nev.value
            ).strip(),
            inline=False
        )

        embed.add_field(
            name="📧 E-mail",
            value=str(
                self.email.value
            ).strip(),
            inline=False
        )

        embed.add_field(
            name="📱 Mobil",
            value=str(
                self.mobil.value
            ).strip(),
            inline=False
        )

        embed.add_field(
            name="📍 Foxpost szekrény címe",
            value=str(
                self.szekreny.value
            ).strip(),
            inline=False
        )

        embed.set_footer(
            text=(
                f"Beküldte: "
                f"{interaction.user.display_name}"
            )
        )

        try:

            target_user = bot.get_user(
                FOXPOST_TARGET_USER_ID
            )

            if target_user is None:

                target_user = await bot.fetch_user(
                    FOXPOST_TARGET_USER_ID
                )

        except Exception as e:

            print(
                f"❌ Foxpost célfelhasználó hiba: "
                f"{type(e).__name__}: {e}",
                flush=True
            )

            return await interaction.response.send_message(
                "❌ Nem sikerült elérni "
                "a megadott Discord-felhasználót.",
                ephemeral=True
            )

        try:

            await target_user.send(
                embed=embed
            )

        except Exception as e:

            print(
                f"⚠️ Foxpost DM küldési hiba: "
                f"{type(e).__name__}: {e}",
                flush=True
            )

        try:

            channel = interaction.channel

            if not isinstance(
                channel,
                discord.TextChannel
            ):

                return await interaction.response.send_message(
                    "❌ A !fox parancsot normál "
                    "szöveges csatornában kell használni.",
                    ephemeral=True
                )

            thread = await channel.create_thread(
                name=(
                    f"📦 Foxpost • "
                    f"{target_user.display_name}"
                ),
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=60
            )

            await thread.add_user(
                target_user
            )

            await thread.send(
                embed=embed
            )

            await interaction.response.send_message(
                "✅ Foxpost adatok elküldve!\n"
                f"📩 DM elküldve: "
                f"{target_user.mention}\n"
                f"🔒 Privát szál létrehozva: "
                f"**{thread.name}**\n"
                "⏱️ A szál 1 óra inaktivitás "
                "után automatikusan archiválódik.",
                ephemeral=True
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ Nem sikerült létrehozni "
                "a privát szálat. "
                "A botnak szüksége van a "
                "megfelelő jogosultságokra.",
                ephemeral=True
            )

        except Exception as e:

            print(
                f"❌ Foxpost privát thread hiba: "
                f"{type(e).__name__}: {e}",
                flush=True
            )

            await interaction.response.send_message(
                "❌ Hiba történt a privát "
                "Foxpost szál létrehozásakor.",
                ephemeral=True
            )


class FoxView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=600
        )

    @discord.ui.button(
        label="Adatok megadása",
        emoji="📦",
        style=discord.ButtonStyle.primary
    )
    async def adatok(
        self,
        interaction,
        button
    ):

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:

            return await interaction.response.send_message(
                msg,
                ephemeral=True
            )

        await interaction.response.send_modal(
            FoxModal()
        )


def build_fox_panel():

    embed = discord.Embed(
        title="📦 Foxpost",
        description=(
            "A **📦 Adatok megadása** gombra kattintva "
            "egy külön ablakban megadhatod a Foxpost "
            "küldéshez szükséges adatokat.\n\n"
            "**Szükséges adatok:**\n"
            "👤 Név\n"
            "📧 E-mail\n"
            "📱 Mobil\n"
            "📍 Foxpost szekrény címe"
        ),
        color=discord.Color.orange()
    )

    embed.set_footer(
        text=(
            "Az elküldött adatokat a rendszer továbbítja."
        )
    )

    return embed


# ==========================================================
# VBUCK CALCULATOR
# ==========================================================

VBUCK_PACKAGES = [
    (800, 2700),
    (2400, 6900),
    (4500, 11100),
    (12500, 27000)
]


def format_huf(value):

    value = round(
        float(value),
        1
    )

    if value.is_integer():

        return f"{int(value):,}".replace(
            ",",
            "."
        )

    return (
        f"{value:,.1f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def format_number(value):

    return f"{int(value):,}".replace(
        ",",
        "."
    )


def calculate_vbuck_package(
    item_vbucks,
    package_vbucks,
    package_price
):

    packages_needed = max(
        1,
        (
            item_vbucks
            + package_vbucks
            - 1
        )
        // package_vbucks
    )

    purchased_vbucks = (
        packages_needed
        * package_vbucks
    )

    purchased_price = (
        packages_needed
        * package_price
    )

    price_per_100 = (
        package_price
        / package_vbucks
        * 100
    )

    item_value_huf = (
        item_vbucks
        * package_price
        / package_vbucks
    )

    remaining_vbucks = (
        purchased_vbucks
        - item_vbucks
    )

    remaining_huf = (
        remaining_vbucks
        * package_price
        / package_vbucks
    )

    return (
        packages_needed,
        purchased_vbucks,
        purchased_price,
        price_per_100,
        item_value_huf,
        remaining_vbucks,
        remaining_huf
    )


class VbuckModal(
    discord.ui.Modal,
    title="V-Bucks számítás"
):

    vbucks = discord.ui.TextInput(
        label="Vbucks:",
        placeholder="Pl. 1500",
        required=True,
        max_length=10
    )

    async def on_submit(self, interaction):

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:

            return await interaction.response.send_message(
                msg,
                ephemeral=True
            )

        try:

            item_vbucks = int(
                str(
                    self.vbucks.value
                )
                .replace(".", "")
                .replace(",", "")
                .replace(" ", "")
            )

            if item_vbucks <= 0:
                raise ValueError

        except ValueError:

            return await interaction.response.send_message(
                "❌ Kérlek, adj meg egy pozitív "
                "egész V-Bucks értéket!",
                ephemeral=True
            )

        embed = discord.Embed(
            title="💳 V-Bucks kalkulátor",
            description=(
                "**Vásárolni kívánt érték:** "
                f"🔵 **{format_number(item_vbucks)} "
                f"V-Bucks**"
            ),
            color=discord.Color.blue()
        )

        for (
            package_vbucks,
            package_price
        ) in VBUCK_PACKAGES:

            (
                packages_needed,
                purchased_vbucks,
                purchased_price,
                price_per_100,
                item_value_huf,
                remaining_vbucks,
                remaining_huf
            ) = calculate_vbuck_package(
                item_vbucks,
                package_vbucks,
                package_price
            )

            text = (
                f"**{format_number(package_vbucks)} "
                f"V-Bucks / "
                f"{format_huf(package_price)} HUF** "
                f"- **100 V-Bucks / "
                f"{format_huf(price_per_100)} HUF**\n"
                "--------------------------\n"
            )

            if packages_needed > 1:

                text += (
                    f"**Vásárlás:** "
                    f"{format_number(package_vbucks)} "
                    f"V-Bucks / "
                    f"{format_huf(package_price)} HUF "
                    f"[x{packages_needed}] = "
                    f"{format_number(purchased_vbucks)} "
                    f"V-Bucks / "
                    f"{format_huf(purchased_price)} HUF\n"
                )

            else:

                text += (
                    f"**Vásárlás:** "
                    f"{format_number(package_vbucks)} "
                    f"V-Bucks / "
                    f"{format_huf(package_price)} HUF\n"
                )

            text += (
                f"**Item értéke:** "
                f"{format_number(item_vbucks)} "
                f"V-Bucks / "
                f"{format_huf(item_value_huf)} HUF\n"
                f"**Marad:** "
                f"{format_number(remaining_vbucks)} "
                f"V-Bucks / "
                f"{format_huf(remaining_huf)} HUF"
            )

            embed.add_field(
                name=(
                    f"💰 "
                    f"{format_number(package_vbucks)} "
                    f"V-Bucks csomag"
                ),
                value=text,
                inline=False
            )

        embed.set_footer(
            text=(
                "V-Bucks kalkulátor • "
                "Mind a 4 csomag összehasonlítva"
            )
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


class VbuckView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=600
        )

    @discord.ui.button(
        label="V-Bucks számítás",
        emoji="💳",
        style=discord.ButtonStyle.primary
    )
    async def vbuck(
        self,
        interaction,
        button
    ):

        ok, msg = check_access(
            interaction=interaction
        )

        if not ok:

            return await interaction.response.send_message(
                msg,
                ephemeral=True
            )

        await interaction.response.send_modal(
            VbuckModal()
        )


def build_vbuck_panel():

    embed = discord.Embed(
        title="💳 V-Bucks kalkulátor",
        description=(
            "**Számold ki, melyik V-Bucks "
            "csomaggal jársz a legjobban!**\n\n"
            "Nyomd meg a **💳 V-Bucks számítás** "
            "gombot, majd add meg, hány V-Bucks "
            "értékű Itemet szeretnél vásárolni."
        ),
        color=discord.Color.blue()
    )

    embed.add_field(
        name="🔵 Vbucks:",
        value=(
            "Írd be a kívánt V-Bucks értéket."
        ),
        inline=False
    )

    embed.add_field(
        name="📦 Elérhető csomagok",
        value=(
            "🟢 **800 V-Bucks — 2.700 HUF**\n"
            "🔵 **2.400 V-Bucks — 6.900 HUF**\n"
            "🟣 **4.500 V-Bucks — 11.100 HUF**\n"
            "🟠 **12.500 V-Bucks — 27.000 HUF**"
        ),
        inline=False
    )

    embed.set_footer(
        text=(
            "A kalkulátor mind a 4 csomagot "
            "összehasonlítja."
        )
    )

    return embed


# ==========================================================
# COMMANDS
# ==========================================================

@bot.command()
async def n(ctx):

    ok, msg = check_access(
        ctx=ctx
    )

    if not ok:
        return await ctx.send(msg)

    current, limit, remaining = (
        get_user_limit_info(
            ctx.author.id
        )
    )

    embed = discord.Embed(
        title="📌 Központ",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="📊 Limit",
        value=(
            f"{current}/{limit} | "
            f"{remaining} maradt"
        )
    )

    await ctx.send(
        embed=embed,
        view=MenuView()
    )


@bot.command(name="txt")
async def txt(ctx):

    ok, msg = check_access(
        ctx=ctx
    )

    if not ok:
        return await ctx.send(msg)

    await ctx.send(
        embed=build_jegyzet_panel(),
        view=JegyzetView()
    )


@bot.command(name="fox")
async def fox(ctx):

    ok, msg = check_access(
        ctx=ctx
    )

    if not ok:
        return await ctx.send(msg)

    await ctx.send(
        embed=build_fox_panel(),
        view=FoxView()
    )


@bot.command(name="dm")
async def dm(ctx):

    ok, msg = check_access(
        ctx=ctx
    )

    if not ok:
        return await ctx.send(msg)

    await ctx.send(
        embed=build_spar_dm_panel(),
        view=SparDmView()
    )


# ==========================================================
# !VBUCK PARANCS
# ==========================================================

@bot.command(name="vbuck")
async def vbuck(ctx):

    ok, msg = check_access(
        ctx=ctx
    )

    if not ok:
        return await ctx.send(msg)

    await ctx.send(
        embed=build_vbuck_panel(),
        view=VbuckView()
    )


@bot.command(name="yt")
async def yt(ctx):

    ok, msg = check_access(
        ctx=ctx
    )

    if not ok:
        return await ctx.send(msg)

    await ctx.send(
        embed=discord.Embed(
            title="📺 YouTube",
            description=(
                "Válassz egy YouTube csatornát."
            ),
            color=discord.Color.red()
        ),
        view=YoutubeView()
    )


@bot.command(name="tw")
async def tw(ctx):

    ok, msg = check_access(
        ctx=ctx
    )

    if not ok:
        return await ctx.send(msg)

    await ctx.send(
        embed=discord.Embed(
            title="🎮 Twitch",
            description=(
                "Válassz egy Twitch csatornát."
            ),
            color=discord.Color.purple()
        ),
        view=TwitchView()
    )


# ==========================================================
# AUTO MONEY / TIME
# ==========================================================

def get_rates():

    try:

        r = requests.get(
            "https://open.er-api.com/v6/latest/HUF",
            timeout=10
        )

        data = r.json()

        return {
            "HUF": 1.0,
            "USD": float(
                data["rates"]["USD"]
            ),
            "EUR": float(
                data["rates"]["EUR"]
            ),
            "GBP": float(
                data["rates"]["GBP"]
            ),
            "TRY": float(
                data["rates"]["TRY"]
            )
        }

    except Exception as e:

        print(
            "Árfolyam hiba:",
            e
        )

        return None


async def handle_money(message):

    rates = get_rates()

    if not rates:
        return

    patterns = [

        (
            r'€\s?(\d+(?:\.\d+)?)',
            'EUR'
        ),

        (
            r'\$\s?(\d+(?:\.\d+)?)',
            'USD'
        ),

        (
            r'£\s?(\d+(?:\.\d+)?)',
            'GBP'
        ),

        (
            r'(\d+(?:\.\d+)?)\s?TRY',
            'TRY'
        ),

        (
            r'(\d+(?:\.\d+)?)\s?HUF',
            'HUF'
        )

    ]

    for pattern, currency in patterns:

        match = re.search(
            pattern,
            message.content,
            re.I
        )

        if not match:
            continue

        amount = float(
            match.group(1)
        )

        if currency == "HUF":

            huf = amount

        else:

            huf = (
                amount
                / rates[currency]
            )

        usd = (
            huf
            * rates["USD"]
        )

        eur = (
            huf
            * rates["EUR"]
        )

        gbp = (
            huf
            * rates["GBP"]
        )

        try_amount = (
            huf
            * rates["TRY"]
        )

        await message.reply(
            f"💰 Ez az összeg:\n"
            f"🇭🇺 {round(huf):,.0f} HUF\n"
            f"🇺🇸 ${usd:.2f}\n"
            f"🇪🇺 €{eur:.2f}\n"
            f"🇬🇧 £{gbp:.2f}\n"
            f"🇹🇷 ₺{try_amount:.2f} TRY"
        )

        return


async def handle_time(message):

    patterns = {

        "CEST":
            "Europe/Budapest",

        "CET":
            "Europe/Budapest",

        "PT":
            "America/Los_Angeles",

        "ET":
            "America/New_York",

        "UTC":
            "UTC",

        "GMT":
            "UTC"

    }

    match = re.search(
        r'(CEST|CET|PT|ET|UTC|GMT)\s+'
        r'(\d{1,2}):(\d{2})(AM|PM)',
        message.content,
        re.I
    )

    if not match:
        return

    tz_name = (
        match.group(1)
        .upper()
    )

    hour = int(
        match.group(2)
    )

    minute = int(
        match.group(3)
    )

    ampm = (
        match.group(4)
        .upper()
    )

    if (
        ampm == "PM"
        and hour != 12
    ):
        hour += 12

    if (
        ampm == "AM"
        and hour == 12
    ):
        hour = 0

    now = datetime.now()

    source = datetime(
        now.year,
        now.month,
        now.day,
        hour,
        minute,
        tzinfo=ZoneInfo(
            patterns[tz_name]
        )
    )

    hu = source.astimezone(
        ZoneInfo("Europe/Budapest")
    )

    txt_value = hu.strftime(
        "%H:%M"
    )

    if hu.date() > source.date():
        txt_value += " (másnap)"

    await message.reply(
        f"🇭🇺 Magyar idő szerint: "
        f"{txt_value}"
    )


@bot.event
async def on_message(message):

    if message.author.bot:
        return

    perms = message.channel.permissions_for(
        message.guild.me
        if message.guild
        else bot.user
    )

    if perms.send_messages:

        await handle_money(
            message
        )

        await handle_time(
            message
        )

    await bot.process_commands(
        message
    )


# ==========================================================
# FORTNITE STATUS MONITOR
# ==========================================================

def _get_fortnite_status():

    try:

        response = requests.get(
            FORTNITE_STATUS_URL,
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        components = data.get(
            "components",
            []
        )

        fortnite_components = [

            c
            for c in components

            if "fortnite"
            in c.get(
                "name",
                ""
            ).lower()

        ]

        if not fortnite_components:

            active_items = []

            for item in (
                data.get(
                    "incidents",
                    []
                )
                +
                data.get(
                    "scheduled_maintenances",
                    []
                )
            ):

                blob = (

                    item.get(
                        "name",
                        ""
                    )
                    + " "
                    +
                    " ".join(

                        u.get(
                            "body",
                            ""
                        )

                        for u
                        in item.get(
                            "incident_updates",
                            []
                        )

                    )

                ).lower()

                if "fortnite" in blob:

                    active_items.append(
                        item
                    )

            if active_items:

                return {

                    "state":
                        "offline",

                    "label":
                        "LEÁLLÁS / KARBANTARTÁS",

                    "indicator":
                        data.get(
                            "status",
                            {}
                        ).get(
                            "indicator",
                            "major"
                        ),

                    "description":
                        data.get(
                            "status",
                            {}
                        ).get(
                            "description",
                            "Probléma észlelve"
                        ),

                    "components":
                        [],

                    "items":
                        active_items,

                    "updated_at":
                        data.get(
                            "page",
                            {}
                        ).get(
                            "updated_at"
                        )

                }

            return {

                "state":
                    "online",

                "label":
                    "ONLINE",

                "indicator":
                    data.get(
                        "status",
                        {}
                    ).get(
                        "indicator",
                        "none"
                    ),

                "description":
                    data.get(
                        "status",
                        {}
                    ).get(
                        "description",
                        "All Systems Operational"
                    ),

                "components":
                    [],

                "items":
                    [],

                "updated_at":
                    data.get(
                        "page",
                        {}
                    ).get(
                        "updated_at"
                    )

            }

        bad_statuses = {

            "major_outage",

            "partial_outage",

            "degraded_performance",

            "under_maintenance"

        }

        bad = [

            c

            for c
            in fortnite_components

            if c.get(
                "status"
            )
            in bad_statuses

        ]

        return {

            "state":
                "offline"
                if bad
                else "online",

            "label":
                "LEÁLLÁS / PROBLÉMA"
                if bad
                else "ONLINE",

            "indicator":
                data.get(
                    "status",
                    {}
                ).get(
                    "indicator",
                    "none"
                ),

            "description":
                data.get(
                    "status",
                    {}
                ).get(
                    "description",
                    "Nincs probléma"
                ),

            "components":
                fortnite_components,

            "items":
                [],

            "updated_at":
                data.get(
                    "page",
                    {}
                ).get(
                    "updated_at"
                )

        }

    except Exception as e:

        print(
            "Fortnite státusz hiba:",
            e
        )

        return None


def _format_epic_time(value):

    if not value:
        return "—"

    try:

        dt = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00"
            )
        )

        return dt.astimezone(
            ZoneInfo("Europe/Budapest")
        ).strftime(
            "%Y.%m.%d. %H:%M"
        )

    except Exception:

        return value


def _build_fortnite_embed(status):

    if status["state"] == "online":

        color = discord.Color.green()

        icon = "🟢"

        status_text = "ONLINE"

        description = (
            "A Fortnite szerverei "
            "jelenleg elérhetők."
        )

    else:

        color = discord.Color.red()

        icon = "🔴"

        status_text = status["label"]

        description = (
            "Az Epic Games státuszrendszere "
            "problémát vagy karbantartást jelez."
        )

    embed = discord.Embed(

        title=(
            "🎮 Fortnite szerverállapot"
        ),

        description=(
            f"{icon} "
            f"**{status_text}**\n\n"
            f"{description}"
        ),

        color=color,

        timestamp=datetime.now(
            ZoneInfo("UTC")
        )

    )

    if status.get("components"):

        component_lines = []

        for component in (
            status["components"][:8]
        ):

            state = component.get(
                "status",
                "unknown"
            )

            state_icon = (
                "🟢"
                if state == "operational"
                else "🔴"
            )

            component_lines.append(

                f"{state_icon} "
                f"**{component.get('name', 'Ismeretlen')}** "
                f"— `{state}`"

            )

        embed.add_field(

            name=(
                "📡 Fortnite szolgáltatások"
            ),

            value="\n".join(
                component_lines
            ),

            inline=False

        )

    active_items = status.get(
        "items",
        []
    )

    if active_items:

        item = active_items[0]

        embed.add_field(

            name="🔧 Aktuális esemény",

            value=(
                f"**{item.get('name', 'Fortnite esemény')}**"
            ),

            inline=False

        )

        scheduled_for = item.get(
            "scheduled_for"
        )

        scheduled_until = item.get(
            "scheduled_until"
        )

        if (
            scheduled_for
            or scheduled_until
        ):

            embed.add_field(

                name="🕐 Időpont",

                value=(

                    f"Kezdés: "
                    f"**{_format_epic_time(scheduled_for)}**\n"

                    f"Várható vége: "
                    f"**{_format_epic_time(scheduled_until)}**"

                ),

                inline=False

            )

        updates = item.get(
            "incident_updates",
            []
        )

        if updates:

            latest = updates[-1]

            body = (
                latest.get(
                    "body",
                    ""
                ).strip()
            )

            if body:

                embed.add_field(

                    name="📢 Epic frissítés",

                    value=body[:1024],

                    inline=False

                )

    embed.add_field(

        name="🔄 Epic állapot",

        value=status.get(
            "description",
            "Ismeretlen"
        ),

        inline=True

    )

    embed.add_field(

        name="🕐 Utolsó ellenőrzés",

        value=(
            f"<t:"
            f"{int(datetime.now(ZoneInfo('UTC')).timestamp())}"
            f":R>"
        ),

        inline=True

    )

    return embed


async def check_fortnite_status():

    global fortnite_last_state

    if not FORTNITE_CHANNEL_ID:

        print(
            "Fortnite státuszfigyelő: "
            "FORTNITE_CHANNEL_ID nincs beállítva.",
            flush=True
        )

        return

    try:

        channel = bot.get_channel(
            FORTNITE_CHANNEL_ID
        )

        if channel is None:

            channel = await bot.fetch_channel(
                FORTNITE_CHANNEL_ID
            )

        status = await asyncio.to_thread(
            _get_fortnite_status
        )

        if not status:

            print(
                "Fortnite státusz: "
                "nem sikerült lekérni az Epic API-t.",
                flush=True
            )

            return

        embed = _build_fortnite_embed(
            status
        )

        embed.set_footer(

            text=(

                "Epic Games Status • Ellenőrzés: "

                f"{datetime.now("
                    f"ZoneInfo('Europe/Budapest')"
                f").strftime('%H:%M:%S')}"

            )

        )

        await channel.send(

            embed=embed,

            allowed_mentions=(
                discord.AllowedMentions.none()
            )

        )

        if (
            fortnite_last_state is not None
            and
            status["state"]
            !=
            fortnite_last_state
        ):

            if status["state"] == "offline":

                notify_embed = discord.Embed(

                    title=(
                        "🔴 Fortnite szerverek leálltak"
                    ),

                    description=(

                        "Az Epic Games státuszoldala "
                        "szerint a Fortnite jelenleg "
                        "nem érhető el vagy karbantartás "
                        "alatt áll."

                    ),

                    color=discord.Color.red()

                )

            else:

                notify_embed = discord.Embed(

                    title=(
                        "🟢 Fortnite szerverek "
                        "újra ONLINE"
                    ),

                    description=(

                        "A Fortnite szerverei ismét "
                        "elérhetőnek látszanak az "
                        "Epic Games hivatalos "
                        "státuszrendszere szerint. 🎮"

                    ),

                    color=discord.Color.green()

                )

            notify_embed.set_footer(
                text="Epic Games Status"
            )

            await channel.send(

                embed=notify_embed,

                allowed_mentions=(
                    discord.AllowedMentions.none()
                )

            )

        fortnite_last_state = (
            status["state"]
        )

        print(

            f"Fortnite ellenőrzés kész: "
            f"{status['state']} | "
            "következő ellenőrzés 10 perc múlva.",

            flush=True

        )

    except Exception as e:

        print(

            f"❌ Fortnite státuszfigyelő hiba: "
            f"{type(e).__name__}: {e}",

            flush=True

        )

        traceback.print_exc()


async def fortnite_status_loop():

    await bot.wait_until_ready()

    await check_fortnite_status()

    while not bot.is_closed():

        print(

            "Fortnite státuszfigyelő: "
            "várakozás 10 percig...",

            flush=True

        )

        await asyncio.sleep(
            FORTNITE_CHECK_INTERVAL
        )

        print(

            "Fortnite státuszfigyelő: "
            "új ellenőrzés indul.",

            flush=True

        )

        await check_fortnite_status()


# ==========================================================
# READY
# ==========================================================

@bot.event
async def on_ready():

    bot.add_view(
        YoutubeView()
    )

    bot.add_view(
        TwitchView()
    )

    print(
        "Bot fut:",
        bot.user
    )

    global fortnite_monitor_task

    if FORTNITE_CHANNEL_ID:

        if (
            "fortnite_monitor_task"
            not in globals()
            or fortnite_monitor_task.done()
        ):

            fortnite_monitor_task = (
                asyncio.create_task(
                    fortnite_status_loop()
                )
            )

            print(

                "Fortnite státuszfigyelő "
                "elindítva (10 percenként).",

                flush=True

            )

    for line in load_memory():

        try:

            (
                guild_id,
                channel_id,
                user_id,
                time_str,
                msg,
                repeat
            ) = line.split(
                "|",
                5
            )

            if not is_server_allowed(
                int(guild_id)
            ):
                continue

            channel = bot.get_channel(
                int(channel_id)
            )

            if not channel:
                continue

            dt = datetime.fromisoformat(
                time_str
            )

            if dt.tzinfo is None:

                dt = dt.replace(
                    tzinfo=ZoneInfo("UTC")
                )

            asyncio.create_task(

                schedule_message(

                    channel,

                    dt,

                    msg,

                    int(user_id),

                    repeat

                )

            )

        except Exception:

            continue


# ==========================================================
# WEB
# ==========================================================

app = Flask(
    __name__
)


@app.route("/")
def home():

    return "ok"


@app.route("/memory")
def mem():

    if request.args.get(
        "key"
    ) != "titkos123":

        return "no"

    try:

        with open(
            MEMORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            content = f.read()

    except FileNotFoundError:

        content = ""

    return (
        "<pre>"
        + content
        + "</pre>"
    )


Thread(

    target=lambda:
        app.run(
            host="0.0.0.0",
            port=10000,
            use_reloader=False
        ),

    daemon=True

).start()


# ==========================================================
# RUN
# ==========================================================

while True:

    try:

        bot.run(
            DISCORD_TOKEN
        )

        break

    except KeyboardInterrupt:

        break

    except Exception as e:

        print(

            f"❌ A bot leállt: "
            f"{type(e).__name__}: {e}",

            flush=True

        )

        traceback.print_exc()

        time.sleep(5)
