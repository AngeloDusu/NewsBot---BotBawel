import os
import discord
from discord import app_commands
from dotenv import load_dotenv


# 1. baca variable .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")


# 2. setup bot client
class BotBawel(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        # command tree untuk slash command
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Slash Command di sync ke server ID : {GUILD_ID}")

    async def on_ready(self):
        print(f"✅ {self.user} sudah online!")


bot = BotBawel()


# 3. slash command pertama = /ping
@bot.tree.command(
    name="ping", description="Cek apakah BotBawel nyala dan berapa latensinya"
)
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(
        f"🏓 Pong! BotBawel aktif ({latency_ms} ms)"
    )


# 4. jalankan bot
if __name__ == "__main__":
    bot.run(TOKEN)
