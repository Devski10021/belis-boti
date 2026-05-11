import discord
from discord.ext import commands, tasks
import os
import logging
import certifi
import asyncio
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

# ─── CONFIGURATION & LOGGING ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('BelisBot')
load_dotenv()

# ─── DATABASE SETUP ───────────────────────────────────────────────────────────
try:
    MONGO_URL = os.getenv('MONGO_URL')
    cluster = MongoClient(MONGO_URL, tlsCAFile=certifi.where())
    db = cluster["belis_scrims"]
    collection = db["storage"]
    logger.info("Successfully connected to MongoDB.")
except Exception as e:
    logger.error(f"MongoDB Connection Error: {e}")

# ─── CONSTANTS & STYLING ─────────────────────────────────────────────────────
VIP_EMOJI = "<:diamond:1390948554956341301>"
CONFIRM_EMOJI = "✅"
CANCEL_EMOJI = "❌"
EMPTY_SLOT = "▫️"
FILLED_SLOT = "🔷"
ADMIN_SLOT = "🛡️"

SCRIMS = {
    "scrim_22": {
        "name": "PREMIUM 22:00 SCRIMS",
        "reg_channel": 1503324709557895288,
        "slot_channel": 1503325306285588510,
        "wait_channel": 1503325883182747742,
        "role_id": 1503327762109304863,
        "wait_role_id": 1503328170311548949,
        "color": 0xFFD700 
    },
    "scrim_00": {
        "name": "ELITE 00:30 SCRIMS",
        "reg_channel": 1503327037832691832,
        "slot_channel": 1503327123337904189,
        "wait_channel": 1503327364749459506,
        "role_id": 1503327805897707591,
        "wait_role_id": 1503328171884412978,
        "color": 0x00BFFF 
    }
}

# ─── BOT INITIALIZATION ───────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="%", intents=intents, help_command=None)
last_msg_ids = {}

# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────
def get_data(key):
    res = collection.find_one({"_id": key})
    if not res:
        return {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"}
    return res

def save_data(key, data):
    collection.update_one({"_id": key}, {"$set": data}, upsert=True)

async def apply_roles(member, scrim_key, action):
    if not member or not isinstance(member, discord.Member): return
    cfg = SCRIMS[scrim_key]
    r_main = member.guild.get_role(cfg["role_id"])
    r_wait = member.guild.get_role(cfg["wait_role_id"])
    
    try:
        if action == "main":
            if r_wait: await member.remove_roles(r_wait)
            if r_main: await member.add_roles(r_main)
        elif action == "wait":
            if r_main: await member.remove_roles(r_main)
            if r_wait: await member.add_roles(r_wait)
        elif action == "none":
            if r_main: await member.remove_roles(r_main)
            if r_wait: await member.remove_roles(r_wait)
    except Exception as e:
        logger.warning(f"Role change failed for {member.name}: {e}")

# ─── EMBED BUILDERS ──────────────────────────────────────────────────────────
def create_main_embed(scrim_key, data, guild):
    cfg = SCRIMS[scrim_key]
    teams = data.get("teams", [])
    vips = data.get("vips", {})
    
    status_icon = "🟢" if data.get("status") == "OPEN" else "🔴"
    embed = discord.Embed(
        title=f"🏆 {cfg['name']}",
        description=(
            f"**{status_icon} Status:** `{data.get('status', 'OPEN')}`\n"
            f"**👥 Slots:** `{len(teams) + len(vips) + 1}/25` (Admin Incl.)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=cfg["color"],
        timestamp=datetime.utcnow()
    )

    def get_slot_text(slot_num, team_list):
        idx = slot_num - 2 
        if idx < len(team_list):
            t = team_list[idx]
            status = CONFIRM_EMOJI if t.get("confirmed") else "⏳"
            # Mentions ლურჯად რომ გამოჩნდეს
            return f"{status} **Slot {slot_num:02d}:** {t['name']} `[{t['tag']}]`\n└ <@{t['manager_id']}>"
        return f"{EMPTY_SLOT} **Slot {slot_num:02d}:** *Available*"

    # Column 1: Slots 1-13
    col1 = [f"{ADMIN_SLOT} **Slot 01:** `ELITE HOST`"]
    for i in range(2, 14):
        col1.append(get_slot_text(i, teams))

    # Column 2: Slots 14-25
    col2 = []
    for i in range(14, 24):
        col2.append(get_slot_text(i, teams))
    
    # VIP Slots
    for i in ["24", "25"]:
        v = vips.get(i)
        if v:
            col2.append(f"{VIP_EMOJI} **Slot {i}:** {v['name']} `[{v['tag']}]` \n└ <@{v['manager_id']}>")
        else:
            col2.append(f"🔹 **Slot {i}:** *VIP Reservation*")

    embed.add_field(name="󠂪", value="\n".join(col1), inline=True)
    embed.add_field(name="󠂪", value="\n".join(col2), inline=True)
    
    embed.set_author(name="Belis Scrim Management", icon_url=bot.user.avatar.url if bot.user.avatar else None)
    embed.set_footer(text="React ✅ to confirm or ❌ to leave • Auto-update active")
    return embed

def create_wait_embed(scrim_key, data):
    cfg = SCRIMS[scrim_key]
    wl = data.get("waitlist", [])
    embed = discord.Embed(
        title=f"📋 Waitlist — {cfg['name']}",
        color=0x34495e,
        description="When a slot opens, the first team here moves up automatically."
    )
    
    if wl:
        desc = ""
        for i, t in enumerate(wl):
            desc += f"`#{i+1:02d}` **{t['name']}** `[{t['tag']}]` — <@{t['manager_id']}>\n"
        embed.description = desc
    else:
        embed.description = "```diff\n- No teams in waitlist\n```"
    return embed

# ─── UPDATE LOGIC ─────────────────────────────────────────────────────────────
async def refresh_displays(scrim_key, guild):
    cfg = SCRIMS[scrim_key]
    data = get_data(scrim_key)
    
    # Slot Channel
    slot_ch = bot.get_channel(cfg["slot_channel"])
    if slot_ch:
        try:
            await slot_ch.purge(limit=15, check=lambda m: m.author == bot.user)
            emb = create_main_embed(scrim_key, data, guild)
            msg = await slot_ch.send(embed=emb)
            last_msg_ids[scrim_key] = msg.id
            await msg.add_reaction(CONFIRM_EMOJI)
            await msg.add_reaction(CANCEL_EMOJI)
        except Exception as e: logger.error(f"Slot Refresh error: {e}")

    # Waitlist Channel
    wait_ch = bot.get_channel(cfg["wait_channel"])
    if wait_ch:
        try:
            await wait_ch.purge(limit=15, check=lambda m: m.author == bot.user)
            await wait_ch.send(embed=create_wait_embed(scrim_key, data))
        except Exception as e: logger.error(f"Wait Refresh error: {e}")

# ─── CORE EVENTS ──────────────────────────────────────────────────────────────
@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id: return
    
    for key, cfg in SCRIMS.items():
        if payload.message_id == last_msg_ids.get(key):
            guild = bot.get_guild(payload.guild_id)
            user = guild.get_member(payload.user_id)
            data = get_data(key)
            
            user_team_idx = next((i for i, t in enumerate(data["teams"]) if t["manager_id"] == payload.user_id), None)
            is_admin = user.guild_permissions.administrator
            
            msg = await bot.get_channel(payload.channel_id).fetch_message(payload.message_id)
            
            if user_team_idx is None and not is_admin:
                await msg.remove_reaction(payload.emoji, user)
                return

            changed = False
            if str(payload.emoji) == CONFIRM_EMOJI:
                if user_team_idx is not None:
                    if not data["teams"][user_team_idx]["confirmed"]:
                        data["teams"][user_team_idx]["confirmed"] = True
                        changed = True
                elif is_admin:
                    for t in data["teams"]:
                        if not t["confirmed"]:
                            t["confirmed"] = True
                            changed = True
                            break

            elif str(payload.emoji) == CANCEL_EMOJI:
                if user_team_idx is not None:
                    data["teams"].pop(user_team_idx)
                    await apply_roles(user, key, "none")
                    changed = True
                    if data["waitlist"]:
                        promo = data["waitlist"].pop(0)
                        data["teams"].append(promo)
                        p_member = guild.get_member(promo["manager_id"])
                        if p_member: await apply_roles(p_member, key, "main")
                
                await msg.remove_reaction(payload.emoji, user)

            if changed:
                save_data(key, data)
                await refresh_displays(key, guild)

# ─── COMMANDS ─────────────────────────────────────────────────────────────────
@bot.command(name="register", aliases=["reg"])
async def register(ctx, clan_name: str, clan_tag: str, manager: discord.Member = None):
    """Usage: %register "Clan Name" TAG [@Manager]"""
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id == v["reg_channel"]), None)
    if not key: return

    data = get_data(key)
    if data["status"] != "OPEN":
        return await ctx.send("❌ Registration is currently **CLOSED**.")

    target_manager = manager if manager else ctx.author

    if any(t["manager_id"] == target_manager.id for t in data["teams"]) or \
       any(t["manager_id"] == target_manager.id for t in data["waitlist"]):
        return await ctx.send(f"❌ {target_manager.display_name} is already registered.")

    new_team = {
        "name": clan_name, "tag": clan_tag.upper(),
        "manager_id": target_manager.id, "confirmed": False,
        "time": datetime.utcnow().isoformat()
    }

    if len(data["teams"]) < 22:
        data["teams"].append(new_team)
        await apply_roles(target_manager, key, "main")
        msg = f"✅ **{clan_name}** is registered for <@{target_manager.id}>!"
    else:
        data["waitlist"].append(new_team)
        await apply_roles(target_manager, key, "wait")
        msg = f"📋 **{clan_name}** added to Waitlist for <@{target_manager.id}>!"

    save_data(key, data)
    await refresh_displays(key, ctx.guild)
    await ctx.send(msg)

@bot.command()
@commands.has_permissions(administrator=True)
async def reset(ctx):
    """სრულად ასუფთავებს მიმდინარე სკრიმს"""
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]), None)
    if not key:
        return await ctx.send("❌ გამოიყენე ეს ბრძანება რეგისტრაციის ან სლოტების არხში!")
    
    empty_data = {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"}
    save_data(key, empty_data)
    await refresh_displays(key, ctx.guild)
    await ctx.send(f"🔄 **{SCRIMS[key]['name']}** სრულად გასუფთავდა!")

@bot.command()
@commands.has_permissions(administrator=True)
async def open(ctx):
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id == v["reg_channel"]), None)
    if not key: return
    data = get_data(key); data["status"] = "OPEN"; save_data(key, data)
    await refresh_displays(key, ctx.guild)
    await ctx.send("🔓 Registration is now **OPEN**.")

@bot.command()
@commands.has_permissions(administrator=True)
async def close(ctx):
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id == v["reg_channel"]), None)
    if not key: return
    data = get_data(key); data["status"] = "CLOSED"; save_data(key, data)
    await refresh_displays(key, ctx.guild)
    await ctx.send("🔒 Registration is now **CLOSED**.")

# ─── ON READY ─────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"""
    ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
    ┃  SYSTEM: {bot.user.name} IS ONLINE      ┃
    ┃  STATUS: READY TO MANAGE SCRIMS          ┃
    ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
    """)
    logger.info(f"Connected as {bot.user}")

bot.run(os.getenv('DISCORD_TOKEN'))
