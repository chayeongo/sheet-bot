import discord
from discord.ext import commands, tasks
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import json

# Railway 환경에서 base64 인코딩된 creds 읽기
creds_encoded = os.getenv("CREDS_JSON")
if creds_encoded:
    creds_json = base64.b64decode(creds_encoded).decode("utf-8")
    with open("creds.json", "w") as f:
        f.write(creds_json)
else:
    raise ValueError("❌ CREDS_JSON_B64 환경변수가 비어있거나 잘못되었습니다.")

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
SHEET_URL = os.getenv("SHEET_URL")

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
client = gspread.authorize(creds)
sheet = client.open_by_url(SHEET_URL).worksheet("AOO Time")

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True  # ✅ 명령어 인식에 필요함
bot = commands.Bot(command_prefix="!", intents=intents)

MAX_PER_TIME = 30
AOO_TIMES = ["UTC 13:00", "UTC 14:00"]

# Format number with comma
def format_power(value: str) -> str:
    try:
        num = int(value.replace(",", "").replace("M", ""))
        return f"{num:,}"
    except ValueError:
        return value

# Modal to input nickname and power
class RegisterModal(discord.ui.Modal, title="AOO Registration"):
    nickname = discord.ui.TextInput(label="Game Nickname", required=True)
    power = discord.ui.TextInput(label="Power (Numeric Only)", required=True)

    def __init__(self, selected_time):
        super().__init__()
        self.selected_time = selected_time

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = sheet.get_all_values()
        header, rows = data[0], data[1:]

        # Check if user already registered
        for row in rows:
            if row[1] == str(user.id) and row[6] == "Registered":
                await interaction.response.send_message("❌ You have already registered. Use !cancel to cancel.", ephemeral=True)
                return

        # Check per-time limit
        count = sum(1 for row in rows if row[4] == self.selected_time and row[6] == "Registered")
        if count >= MAX_PER_TIME:
            await interaction.response.send_message(f"❌ {self.selected_time} is full.", ephemeral=True)
            return

        next_no = len(rows) + 1
        formatted_power = format_power(self.power.value)

        new_row = [
            str(next_no),
            str(user.id),
            self.nickname.value,
            formatted_power,
            self.selected_time,
            now,
            "Registered",
            ""
        ]
        sheet.append_row(new_row)
        await interaction.response.send_message(f"✅ {self.nickname.value} registered for {self.selected_time}!", ephemeral=True)

# Time selection view
class TimeSelectView(discord.ui.View):
    @discord.ui.select(placeholder="Choose your AOO time", options=[
        discord.SelectOption(label=time, value=time) for time in AOO_TIMES
    ])
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        selected_time = select.values[0]
        await interaction.response.send_modal(RegisterModal(selected_time))

# Initial register button view
class EntryView(discord.ui.View):
    @discord.ui.button(label="Register for AOO", style=discord.ButtonStyle.primary)
    async def register(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Please select your AOO time:", view=TimeSelectView(), ephemeral=True)

# Cancel command
@bot.command(name="cancel")
async def cancel(ctx):
    user_id = str(ctx.author.id)
    data = sheet.get_all_values()
    for idx, row in enumerate(data[1:], start=2):
        if row[1] == user_id and row[6] == "Registered":
            sheet.update_cell(idx, 7, "Cancelled")
            await ctx.send("❌ Your registration has been cancelled.")
            return
    await ctx.send("⚠️ No active registration found.")

# List command
@bot.command(name="list")
async def list_participants(ctx):
    data = sheet.get_all_values()
    rows = [row for row in data[1:] if row[6] == "Registered"]
    if not rows:
        await ctx.send("📭 No participants registered yet.")
        return

    message = "📋 AOO Participants (Nickname | Power | Time):\n"
    for row in rows:
        message += f"- {row[2]} | {row[3]} | {row[4]}\n"
    await ctx.send(message)

# Auto deletion every Sunday to remove data older than 2 weeks
@tasks.loop(hours=24)
async def auto_cleanup():
    if datetime.utcnow().weekday() == 6:  # Sunday
        data = sheet.get_all_values()
        header, rows = data[0], data[1:]
        today = datetime.utcnow()
        to_keep = [header]

        for row in rows:
            try:
                reg_time = datetime.strptime(row[5], "%Y-%m-%d %H:%M:%S")
                if today - reg_time <= timedelta(days=14):
                    to_keep.append(row)
            except:
                to_keep.append(row)

        sheet.clear()
        sheet.append_rows(to_keep)
        print("🧹 Old registrations cleared.")

@bot.event
async def on_ready():
    print(f"🤖 Logged in as {bot.user}")
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.name == "📂〡aoo-registration":
                await channel.send("🛡 Click to register for Ark of Osiris time:", view=EntryView())
    auto_cleanup.start()

bot.run(TOKEN)
