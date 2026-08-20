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

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RepeatModal(self.values[0]))

class RepeatView(discord.ui.View):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        ok, msg = check_access(interaction=interaction)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return False
        return True

    def __init__(self):
        super().__init__()
        self.add_item(RepeatSelect())

class DeleteSelect(discord.ui.Select):
    def __init__(self, data):
        self.data = data

        options = []
        for i, line in enumerate(data[:25]):
            parts = line.split("|")
            _, _, _, time_str, msg, repeat = parts

            dt = datetime.fromisoformat(time_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            dt = dt.astimezone(ZoneInfo("Europe/Budapest"))

            options.append(discord.SelectOption(
                label=f"{dt.strftime('%m.%d %H:%M')} • {repeat}",
                description=msg[:50],
                value=str(i)
            ))

        super().__init__(placeholder="Törlendő kiválasztása", options=options)

    async def callback(self, interaction: discord.Interaction):
        ok, msg = check_access(interaction=interaction)
        if not ok:
            return await interaction.response.send_message(msg, ephemeral=True)

        all_data = load_memory()
        selected = self.data[int(self.values[0])]
        all_data.remove(selected)

        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            for line in all_data:
                f.write(line + "\n")

        await interaction.response.send_message("🗑️ Törölve!", ephemeral=True)

class DeleteView(discord.ui.View):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        ok, msg = check_access(interaction=interaction)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return False
        return True

    def __init__(self, data):
        super().__init__()
        self.add_item(DeleteSelect(data))



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

        super().__init__(
            custom_id="youtube_select",
            placeholder="Válassz YouTube csatornát",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):

        filename = self.values[0]

        data = load_txt(f"{filename}.txt")

        if not data:
            return await interaction.response.send_message(
                "❌ Nem található adat.",
                ephemeral=True
            )

        embed = discord.Embed(
            title=f"📺 {filename}",
            description="\n".join(data),
            color=discord.Color.red()
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )




class TwitchSelect(discord.ui.Select):

    def __init__(self):

        users = load_twitch_users()

        options = [
            discord.SelectOption(
                label=name,
                value=filename
            )
            for name, filename in users[:25]
        ]

        super().__init__(
            custom_id="twitch_select",
            placeholder="Válassz Twitch csatornát",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):

        filename = self.values[0]

        data = load_txt(f"{filename}.txt")

        if not data:
            return await interaction.response.send_message(
                "❌ Nem található adat.",
                ephemeral=True
            )

        embed = discord.Embed(
            title=f"🎮 {filename}",
            description="\n".join(data),
            color=discord.Color.purple()
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )





class YoutubeView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(YoutubeSelect())




class TwitchView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TwitchSelect())





class NotifyChoiceView(discord.ui.View):

    @discord.ui.button(label="Saját magam", style=discord.ButtonStyle.green)
    async def me(self, interaction, button):
        modal = NotificationModal()
        modal.target_type = "user"
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="@everyone", style=discord.ButtonStyle.red)
    async def everyone(self, interaction, button):
        modal = NotificationModal()
        modal.target_type = "everyone"
        await interaction.response.send_modal(modal)


class MenuView(discord.ui.View):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        ok, msg = check_access(interaction=interaction)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Értesítés", style=discord.ButtonStyle.green)
    async def notify(self, interaction, button):
        await interaction.response.send_message(
            "Kit pingeljen az értesítés?",
            view=NotifyChoiceView(),
            ephemeral=True
        )

    @discord.ui.button(label="Ismétlődő", style=discord.ButtonStyle.blurple)
    async def repeat(self, interaction, button):
        await interaction.response.send_message("Válassz:", view=RepeatView(), ephemeral=True)

    @discord.ui.button(label="Törlés", style=discord.ButtonStyle.red)
    async def delete(self, interaction, button):
        data = get_user_data(interaction.guild.id, interaction.user.id)
        if not data:
            return await interaction.response.send_message("📭 Nincs adat", ephemeral=True)

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
            dt = datetime.fromisoformat(time_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            dt = dt.astimezone(ZoneInfo("Europe/Budapest"))

            embed.add_field(
                name=f"{i}. {dt.strftime('%m.%d %H:%M')}",
                value=f"{repeat} | {msg}",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------- COMMAND ----------
@bot.command()
async def n(ctx):
    ok, msg = check_access(ctx=ctx)
    if not ok:
        return await ctx.send(msg)

    current, limit, remaining = get_user_limit_info(ctx.author.id)

    embed = discord.Embed(title="📌 Központ", color=discord.Color.blurple())
    embed.add_field(name="📊 Limit", value=f"{current}/{limit} | {remaining} maradt")

    await ctx.send(embed=embed, view=MenuView())


@bot.command(name="yt")
async def yt(ctx):
    await ctx.send(
        embed=discord.Embed(
            title="📺 YouTube",
            description="Válassz egy YouTube csatornát.",
            color=discord.Color.red()
        ),
        view=YoutubeView()
    )



@bot.command(name="tw")
async def tw(ctx):
    await ctx.send(
        embed=discord.Embed(
            title="🎮 Twitch",
            description="Válassz egy Twitch csatornát.",
            color=discord.Color.purple()
        ),
        view=TwitchView()
    )


# ---------- AUTO MONEY / TIME ----------
import re

def get_rates():
    try:
        r = requests.get(
            "https://open.er-api.com/v6/latest/HUF",
            timeout=10
        )
        data = r.json()

        return {
            "HUF": 1.0,
            "USD": float(data["rates"]["USD"]),
            "EUR": float(data["rates"]["EUR"]),
            "GBP": float(data["rates"]["GBP"])
        }
    except Exception as e:
        print("Árfolyam hiba:", e)
        return None

async def handle_money(message):
    rates = get_rates()
    if not rates:
        return

    patterns = [
        (r'€\s?(\d+(?:\.\d+)?)', 'EUR'),
        (r'\$\s?(\d+(?:\.\d+)?)', 'USD'),
        (r'£\s?(\d+(?:\.\d+)?)', 'GBP'),
        (r'(\d+(?:\.\d+)?)\s?HUF', 'HUF')
    ]

    for pattern, currency in patterns:
        match = re.search(pattern, message.content, re.I)
        if not match:
            continue

        amount = float(match.group(1))

        if currency == "HUF":
            huf = amount
        else:
            huf = amount / rates[currency]

        usd = huf * rates["USD"]
        eur = huf * rates["EUR"]
        gbp = huf * rates["GBP"]

        await message.reply(
            f"💰 Ez az összeg:\n"
            f"🇭🇺 {round(huf):,.0f} HUF\n"
            f"🇺🇸 ${usd:.2f}\n"
            f"🇪🇺 €{eur:.2f}\n"
            f"🇬🇧 £{gbp:.2f}"
        )
        return

async def handle_time(message):
    patterns = {
        "CEST": "Europe/Budapest",
        "CET": "Europe/Budapest",
        "PT": "America/Los_Angeles",
        "ET": "America/New_York",
        "UTC": "UTC",
        "GMT": "UTC"
    }

    match = re.search(
        r'(CEST|CET|PT|ET|UTC|GMT)\s+(\d{1,2}):(\d{2})(AM|PM)',
        message.content,
        re.I
    )

    if not match:
        return

    tz_name = match.group(1).upper()
    hour = int(match.group(2))
    minute = int(match.group(3))
    ampm = match.group(4).upper()

    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0

    now = datetime.now()
    source = datetime(
        now.year, now.month, now.day,
        hour, minute,
        tzinfo=ZoneInfo(patterns[tz_name])
    )

    hu = source.astimezone(ZoneInfo("Europe/Budapest"))
    txt = hu.strftime("%H:%M")

    if hu.date() > source.date():
        txt += " (másnap)"

    await message.reply(f"🇭🇺 Magyar idő szerint: {txt}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    perms = message.channel.permissions_for(message.guild.me if message.guild else bot.user)
    if perms.send_messages:
        await handle_money(message)
        await handle_time(message)

    await bot.process_commands(message)



# ---------- FORTNITE STATUS MONITOR ----------
def _get_fortnite_status():
    """Lekéri az Epic Games hivatalos Statuspage API-ját."""
    try:
        response = requests.get(FORTNITE_STATUS_URL, timeout=15)
        response.raise_for_status()
        data = response.json()

        components = data.get("components", [])
        fortnite_components = [
            c for c in components
            if "fortnite" in c.get("name", "").lower()
        ]

        # A Statuspage gyakran külön komponensekben adja meg
        # a Fortnite szolgáltatásait (pl. matchmaking, login, game services).
        if not fortnite_components:
            # Ha nincs külön Fortnite nevű komponens, az incidensek/
            # karbantartások között is megpróbáljuk felismerni.
            active_items = []
            for item in data.get("incidents", []) + data.get("scheduled_maintenances", []):
                blob = (
                    item.get("name", "") + " " +
                    " ".join(u.get("body", "") for u in item.get("incident_updates", []))
                ).lower()
                if "fortnite" in blob:
                    active_items.append(item)

            if active_items:
                return {
                    "state": "offline",
                    "label": "LEÁLLÁS / KARBANTARTÁS",
                    "indicator": data.get("status", {}).get("indicator", "major"),
                    "description": data.get("status", {}).get("description", "Probléma észlelve"),
                    "components": [],
                    "items": active_items,
                    "updated_at": data.get("page", {}).get("updated_at"),
                }

            return {
                "state": "online",
                "label": "ONLINE",
                "indicator": data.get("status", {}).get("indicator", "none"),
                "description": data.get("status", {}).get("description", "All Systems Operational"),
                "components": [],
                "items": [],
                "updated_at": data.get("page", {}).get("updated_at"),
            }

        bad_statuses = {
            "major_outage",
            "partial_outage",
            "degraded_performance",
            "under_maintenance",
        }

        bad = [c for c in fortnite_components if c.get("status") in bad_statuses]

        return {
            "state": "offline" if bad else "online",
            "label": "LEÁLLÁS / PROBLÉMA" if bad else "ONLINE",
            "indicator": data.get("status", {}).get("indicator", "none"),
            "description": data.get("status", {}).get("description", "Nincs probléma"),
            "components": fortnite_components,
            "items": [],
            "updated_at": data.get("page", {}).get("updated_at"),
        }

    except Exception as e:
        print("Fortnite státusz hiba:", e)
        return None


def _format_epic_time(value):
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("Europe/Budapest")).strftime("%Y.%m.%d. %H:%M")
    except Exception:
        return value


def _build_fortnite_embed(status):
    if status["state"] == "online":
        color = discord.Color.green()
        icon = "🟢"
        title = "Fortnite szerverállapot"
        status_text = "ONLINE"
        description = "A Fortnite szerverei jelenleg elérhetők."
    else:
        color = discord.Color.red()
        icon = "🔴"
        title = "Fortnite szerverállapot"
        status_text = status["label"]
        description = "Az Epic Games státuszrendszere problémát vagy karbantartást jelez."

    embed = discord.Embed(
        title=f"🎮 {title}",
        description=f"{icon} **{status_text}**\n\n{description}",
        color=color,
        timestamp=datetime.now(ZoneInfo("UTC"))
    )

    if status.get("components"):
        component_lines = []
        for component in status["components"][:8]:
            state = component.get("status", "unknown")
            state_icon = "🟢" if state == "operational" else "🔴"
            component_lines.append(
                f"{state_icon} **{component.get('name', 'Ismeretlen')}** — `{state}`"
            )
        embed.add_field(
            name="📡 Fortnite szolgáltatások",
            value="\n".join(component_lines),
            inline=False
        )

    active_items = status.get("items", [])
    if active_items:
        item = active_items[0]
        embed.add_field(
            name="🔧 Aktuális esemény",
            value=f"**{item.get('name', 'Fortnite esemény')}**",
            inline=False
        )

        scheduled_for = item.get("scheduled_for")
        scheduled_until = item.get("scheduled_until")
        if scheduled_for or scheduled_until:
            embed.add_field(
                name="🕐 Időpont",
                value=(
                    f"Kezdés: **{_format_epic_time(scheduled_for)}**\n"
                    f"Várható vége: **{_format_epic_time(scheduled_until)}**"
                ),
                inline=False
            )

        updates = item.get("incident_updates", [])
        if updates:
            latest = updates[-1]
            body = latest.get("body", "").strip()
            if body:
                embed.add_field(
                    name="📢 Epic frissítés",
                    value=body[:1024],
                    inline=False
                )

    embed.add_field(
        name="🔄 Epic állapot",
        value=status.get("description", "Ismeretlen"),
        inline=True
    )
    embed.add_field(
        name="🕐 Utolsó ellenőrzés",
        value=f"<t:{int(datetime.now(ZoneInfo('UTC')).timestamp())}:R>",
        inline=True
    )

    embed.set_footer(text="Epic Games Status • Automatikus ellenőrzés 5 percenként")
    return embed


@tasks.loop(seconds=FORTNITE_CHECK_INTERVAL)
async def fortnite_status_loop():
    global fortnite_last_state, fortnite_status_message_id

    if not FORTNITE_CHANNEL_ID:
        print("Fortnite státuszfigyelő: FORTNITE_CHANNEL_ID nincs beállítva.")
        return

    channel = bot.get_channel(FORTNITE_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(FORTNITE_CHANNEL_ID)
        except Exception as e:
            print("Fortnite csatorna nem található:", e)
            return

    status = await asyncio.to_thread(_get_fortnite_status)
    if not status:
        return

    embed = _build_fortnite_embed(status)

    # Egyetlen státusz üzenetet tartunk fenn és 5 percenként frissítjük.
    message = None
    if fortnite_status_message_id:
        try:
            message = await channel.fetch_message(fortnite_status_message_id)
        except Exception:
            message = None

    if message is None:
        message = await channel.send(embed=embed)
        fortnite_status_message_id = message.id
    else:
        await message.edit(embed=embed)

    # Állapotváltozáskor külön értesítés is megy.
    if fortnite_last_state is not None and status["state"] != fortnite_last_state:
        if status["state"] == "offline":
            notify_embed = discord.Embed(
                title="🔴 Fortnite szerverek leálltak",
                description="Az Epic Games státuszoldala szerint a Fortnite jelenleg nem érhető el vagy karbantartás alatt áll.",
                color=discord.Color.red()
            )
        else:
            notify_embed = discord.Embed(
                title="🟢 Fortnite szerverek újra ONLINE",
                description="A Fortnite szerverei ismét elérhetőnek látszanak az Epic Games hivatalos státuszrendszere szerint. 🎮",
                color=discord.Color.green()
            )
        notify_embed.set_footer(text="Epic Games Status")
        await channel.send(embed=notify_embed)

    fortnite_last_state = status["state"]


@fortnite_status_loop.before_loop
async def before_fortnite_status_loop():
    await bot.wait_until_ready()

# ---------- READY ----------
@bot.event
async def on_ready():
    bot.add_view(YoutubeView())
    bot.add_view(TwitchView())

    print("Bot fut:", bot.user)

    if FORTNITE_CHANNEL_ID and not fortnite_status_loop.is_running():
        fortnite_status_loop.start()
        print("Fortnite státuszfigyelő elindítva (5 perc).")

    for line in load_memory():
        try:
            guild_id, channel_id, user_id, time_str, msg, repeat = line.split("|", 5)

            if not is_server_allowed(int(guild_id)):
                continue

            channel = bot.get_channel(int(channel_id))
            if not channel:
                continue

            dt = datetime.fromisoformat(time_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
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
        break
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"❌ A bot leállt: {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        import time
        time.sleep(5)
