import discord
from discord.ext import commands, tasks
from datetime import datetime
import pytz
import os
import logging
import certifi
from pymongo import MongoClient
from dotenv import load_dotenv

# ლოგირება
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# --- MongoDB დაკავშირება ---
MONGO_URL = os.getenv('MONGO_URL')
cluster = MongoClient(MONGO_URL, tlsCAFile=certifi.where())
db = cluster["belis_scrims"]
collection = db["storage"]

# --- კონფიგურაცია ---
TOTAL_SLOTS = 22 
GUILD_ID = 1502260559721005148

SCRIMS = {
    "scrim_22": {
        "name": "22:00 Scrim",
        "reg_channel": 1502263142238130257,
        "slot_channel": 1502263291093975040,
        "wait_channel": 1502263311524171907,
        "id_pass_channel": 1503316106243477504,
        "role_id": 1502324856962814042,
        "wait_role_id": 1503315546349899856,
        "deadline_h": 19, "deadline_m": 30
    },
    "scrim_00": {
        "name": "00:30 Scrim",
        "reg_channel": 1502596279748923462,
        "slot_channel": 1502596374984790207,
        "wait_channel": 1502596395259924541,
        "id_pass_channel": 1503316187377831936,
        "role_id": 1502596541280424058,
        "wait_role_id": 1503315629166694400,
        "deadline_h": 22, "deadline_m": 30
    }
}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="%", intents=intents)
last_msg_ids = {}

# --- დამხმარე ფუნქციები ---

def get_scrim_data(scrim_key):
    res = collection.find_one({"_id": scrim_key})
    if res:
        return {"teams": res.get("teams", []), "waitlist": res.get("waitlist", [])}
    return {"teams": [], "waitlist": []}

def save_scrim_data(scrim_key, data):
    collection.update_one({"_id": scrim_key}, {"$set": data}, upsert=True)

async def manage_roles(member, scrim_key, status):
    cfg = SCRIMS[scrim_key]
    main_role = member.guild.get_role(cfg["role_id"])
    wait_role = member.guild.get_role(cfg["wait_role_id"])
    
    try:
        if status == 'main':
            if wait_role and wait_role in member.roles: await member.remove_roles(wait_role)
            if main_role: await member.add_roles(main_role)
        elif status == 'wait':
            if main_role and main_role in member.roles: await member.remove_roles(main_role)
            if wait_role: await member.add_roles(wait_role)
        elif status == 'none':
            if main_role and main_role in member.roles: await member.remove_roles(main_role)
            if wait_role and wait_role in member.roles: await member.remove_roles(wait_role)
    except Exception as e:
        logger.error(f"Error managing roles for {member.display_name}: {e}")

async def update_all_displays(scrim_key):
    cfg = SCRIMS[scrim_key]
    await render_embed(cfg["slot_channel"], "TEAM LIST", scrim_key)
    await render_embed(cfg["wait_channel"], "WAITLIST", scrim_key)

async def render_embed(channel_id, title, scrim_key):
    channel = bot.get_channel(channel_id)
    if not channel: return
    try: await channel.purge(limit=15, check=lambda m: m.author == bot.user)
    except: pass

    data = get_scrim_data(scrim_key)
    cfg = SCRIMS[scrim_key]
    embed = discord.Embed(title=f"🏆 {cfg['name']} - {title} 🏆", color=0xF1C40F if title == "TEAM LIST" else 0xE67E22)
    content = "━━━━━━━━━━━━━━━━━━━━━━\n"

    if title == "TEAM LIST":
        content += "🆔 **01.** 🔒 **ADMIN / RESERVED**\n\n"
        teams = data.get("teams", [])
        for i, team in enumerate(teams, 2):
            status_icon = "✅ " if team.get('confirmed') else "⏳ "
            vip = "💎 **[VIP]** " if i >= 24 else ""
            content += f"**{i:02d}.** {status_icon}{vip}**{team['name']}** [{team['tag']}]\n└ მენეჯერი: <@{team['manager_id']}>\n\n"
        for i in range(len(teams) + 2, 26):
            lbl = "💎 VIP SLOT" if i >= 24 else "--------------------------------"
            content += f"**{i:02d}.** {lbl}\n"
    else:
        waitlist = data.get("waitlist", [])
        if not waitlist: content += "*ჯერჯერობით ცარიელია...*"
        else:
            for i, team in enumerate(waitlist, 1):
                content += f"**{i:02d}.** 📋 **{team['name']}** [{team['tag']}] - <@{team['manager_id']}>\n"

    embed.description = content + "\n━━━━━━━━━━━━━━━━━━━━━━"
    msg = await channel.send(embed=embed)
    if title == "TEAM LIST":
        last_msg_ids[scrim_key] = msg.id
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

# --- ივენთები ---

@bot.event
async def on_ready():
    logger.info(f'✅ ბოტი ჩაირთო: {bot.user.name}')
    if not check_deadline.is_running(): check_deadline.start()

@bot.command()
async def register(ctx, *, text: str = None):
    scrim_key = next((k for k, v in SCRIMS.items() if ctx.channel.id == v["reg_channel"]), None)
    if not scrim_key: return
    if not text: return await ctx.send("❌ ფორმატი: `%register გუნდი თეგი @მენეჯერი`", delete_after=5)

    parts = text.split()
    manager = ctx.author
    if ctx.message.mentions:
        manager = ctx.message.mentions[0]
        parts = [p for p in parts if not (p.startswith('<@') and p.endswith('>'))]

    if len(parts) < 2: return await ctx.send("❌ დაწერეთ გუნდის სახელი და თეგი!", delete_after=5)

    team_tag = parts[-1]
    team_name = " ".join(parts[:-1])
    data = get_scrim_data(scrim_key)

    if any(t['manager_id'] == manager.id for t in data["teams"] + data["waitlist"]):
        return await ctx.send(f"⚠️ {manager.display_name} უკვე რეგისტრირებულია!", delete_after=5)

    new_team = {'name': team_name, 'tag': team_tag, 'manager_id': manager.id, 'confirmed': False}
    
    if len(data["teams"]) < 22:
        data["teams"].append(new_team)
        await manage_roles(manager, scrim_key, 'main')
        await ctx.message.add_reaction("✅")
    else:
        data["waitlist"].append(new_team)
        await manage_roles(manager, scrim_key, 'wait')
        await ctx.message.add_reaction("⏳")

    save_scrim_data(scrim_key, data)
    await update_all_displays(scrim_key)

@bot.command()
@commands.has_permissions(administrator=True)
async def reset(ctx):
    scrim_key = next((k for k, v in SCRIMS.items() if ctx.channel.id == v["reg_channel"]), None)
    if not scrim_key: return

    data = get_scrim_data(scrim_key)
    for team in data["teams"] + data["waitlist"]:
        member = ctx.guild.get_member(team["manager_id"])
        if member: await manage_roles(member, scrim_key, 'none')

    save_scrim_data(scrim_key, {"teams": [], "waitlist": []})
    await update_all_displays(scrim_key)
    await ctx.send(f"✅ {SCRIMS[scrim_key]['name']} წარმატებით განულდა!", delete_after=10)

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id: return
    scrim_key = next((k for k, v in last_msg_ids.items() if payload.message_id == v), None)
    if not scrim_key: return
    
    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)
    data = get_scrim_data(scrim_key)
    updated = False

    if str(payload.emoji) == "✅":
        for t in data["teams"]:
            if t['manager_id'] == payload.user_id:
                t['confirmed'] = True
                updated = True
                break

    elif str(payload.emoji) == "❌":
        team_to_remove = next((t for t in data["teams"] if t['manager_id'] == payload.user_id), None)
        if team_to_remove:
            data["teams"].remove(team_to_remove)
            if member: await manage_roles(member, scrim_key, 'none')
            if data["waitlist"]:
                promoted = data["waitlist"].pop(0)
                data["teams"].append(promoted)
                promoted_member = guild.get_member(promoted["manager_id"])
                if promoted_member: await manage_roles(promoted_member, scrim_key, 'main')
            updated = True
        else:
            # ვეითლისტიდან წაშლა
            team_to_remove = next((t for t in data["waitlist"] if t['manager_id'] == payload.user_id), None)
            if team_to_remove:
                data["waitlist"].remove(team_to_remove)
                if member: await manage_roles(member, scrim_key, 'none')
                updated = True

    if updated:
        save_scrim_data(scrim_key, data)
        await update_all_displays(scrim_key)

@tasks.loop(minutes=1)
async def check_deadline():
    tz = pytz.timezone('Asia/Tbilisi')
    now = datetime.now(tz)
    for key, cfg in SCRIMS.items():
        if now.hour == cfg["deadline_h"] and now.minute == cfg["deadline_m"]:
            data = get_scrim_data(key)
            changed = False
            guild = bot.get_guild(GUILD_ID)
            
            # ვამოწმებთ სლოტებს: ვინც არ დაადასტურა, ვშლით
            for t in data["teams"][:]:
                if not t.get('confirmed'):
                    data["teams"].remove(t)
                    member = guild.get_member(t["manager_id"])
                    if member: await manage_roles(member, key, 'none')
                    
                    # მაშინვე ვამატებთ ვეითლისტიდან ახალს
                    if data["waitlist"]:
                        promoted = data["waitlist"].pop(0)
                        data["teams"].append(promoted)
                        promoted_member = guild.get_member(promoted["manager_id"])
                        if promoted_member: await manage_roles(promoted_member, key, 'main')
                    changed = True
            
            if changed:
                save_scrim_data(key, data)
                await update_all_displays(key)

if __name__ == "__main__":
    bot.run(os.getenv('DISCORD_TOKEN'))
