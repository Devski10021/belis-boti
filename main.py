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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('BelisBot')
load_dotenv()

# აქ ჩაწერე იმ ხალხის ID ვისაც ბანი აქვთ
BANNED_USERS = [1234567890] 

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
WAIT_EMOJI = "📋"
BAN_EMOJI = "🚫"
EMPTY_SLOT = "▫️"
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
    return res if res else {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"}

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
    except: pass

# ─── EMBED BUILDERS ──────────────────────────────────────────────────────────
def create_main_embed(scrim_key, data, guild):
    cfg = SCRIMS[scrim_key]
    teams = data.get("teams", [])
    vips = data.get("vips", {})
    status_icon = "🟢" if data.get("status") == "OPEN" else "🔴"
    embed = discord.Embed(
        title=f"🏆 {cfg['name']}",
        description=f"**{status_icon} Status:** `{data.get('status', 'OPEN')}`\n**👥 Slots:** `{len(teams) + len(vips) + 1}/25` (Admin Incl.)\n━━━━━━━━━━━━━━━━━━━━━━━━",
        color=cfg["color"],
        timestamp=datetime.utcnow()
    )

    def get_slot_text(slot_num, team_list):
        idx = slot_num - 2 
        if idx < len(team_list):
            t = team_list[idx]
            status = CONFIRM_EMOJI if t.get("confirmed") else "⏳"
            return f"{status} **Slot {slot_num:02d}:** {t['name']} `[{t['tag']}]`\n└ <@{t['manager_id']}>"
        return f"{EMPTY_SLOT} **Slot {slot_num:02d}:** *Available*"

    col1 = [f"{ADMIN_SLOT} **Slot 01:** `ELITE HOST`"]
    for i in range(2, 14): col1.append(get_slot_text(i, teams))
    col2 = []
    for i in range(14, 24): col2.append(get_slot_text(i, teams))
    for i in ["24", "25"]:
        v = vips.get(i)
        if v: col2.append(f"{CONFIRM_EMOJI} {VIP_EMOJI} **Slot {i}:** {v['name']} `[{v['tag']}]` \n└ <@{v['manager_id']}>")
        else: col2.append(f"🔹 **Slot {i}:** *VIP Reservation*")

    embed.add_field(name="󠂪", value="\n".join(col1), inline=True)
    embed.add_field(name="󠂪", value="\n".join(col2), inline=True)
    embed.set_footer(text="React ✅ to confirm or ❌ to leave")
    return embed

def create_wait_embed(scrim_key, data):
    cfg = SCRIMS[scrim_key]; wl = data.get("waitlist", [])
    embed = discord.Embed(title=f"{WAIT_EMOJI} Waitlist — {cfg['name']}", color=0x34495e)
    if wl:
        desc = ""
        for i, t in enumerate(wl):
            desc += f"{WAIT_EMOJI} `#{i+1:02d}` **{t['name']}** `[{t['tag']}]` — <@{t['manager_id']}>\n"
        embed.description = desc
    else: embed.description = "```diff\n- No teams in waitlist\n```"
    return embed

async def refresh_displays(scrim_key, guild):
    cfg = SCRIMS[scrim_key]; data = get_data(scrim_key)
    slot_ch = bot.get_channel(cfg["slot_channel"])
    if slot_ch:
        await slot_ch.purge(limit=5, check=lambda m: m.author == bot.user)
        msg = await slot_ch.send(embed=create_main_embed(scrim_key, data, guild))
        last_msg_ids[scrim_key] = msg.id
        await msg.add_reaction(CONFIRM_EMOJI); await msg.add_reaction(CANCEL_EMOJI)
    wait_ch = bot.get_channel(cfg["wait_channel"])
    if wait_ch:
        await wait_ch.purge(limit=5, check=lambda m: m.author == bot.user)
        await wait_ch.send(embed=create_wait_embed(scrim_key, data))

# ─── CORE EVENTS ──────────────────────────────────────────────────────────────
@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id: return
    for key, cfg in SCRIMS.items():
        if payload.message_id == last_msg_ids.get(key):
            guild = bot.get_guild(payload.guild_id); user = guild.get_member(payload.user_id); data = get_data(key)
            user_team_idx = next((i for i, t in enumerate(data["teams"]) if t["manager_id"] == payload.user_id), None)
            vip_slot = next((k for k, v in data["vips"].items() if v["manager_id"] == payload.user_id), None)
            is_admin = user.guild_permissions.administrator
            
            msg = await bot.get_channel(payload.channel_id).fetch_message(payload.message_id)
            changed = False

            if str(payload.emoji) == CONFIRM_EMOJI:
                if user_team_idx is not None:
                    if not data["teams"][user_team_idx]["confirmed"]: data["teams"][user_team_idx]["confirmed"] = True; changed = True
                elif vip_slot:
                    if not data["vips"][vip_slot].get("confirmed"): data["vips"][vip_slot]["confirmed"] = True; changed = True
                elif is_admin:
                    for t in data["teams"]:
                        if not t["confirmed"]: t["confirmed"] = True; changed = True; break

            elif str(payload.emoji) == CANCEL_EMOJI:
                if user_team_idx is not None:
                    data["teams"].pop(user_team_idx)
                    await apply_roles(user, key, "none")
                    changed = True
                    if data["waitlist"]:
                        promo = data["waitlist"].pop(0)
                        promo["confirmed"] = True
                        data["teams"].append(promo)
                        p_member = guild.get_member(promo["manager_id"])
                        if p_member: await apply_roles(p_member, key, "main")
                elif vip_slot:
                    del data["vips"][vip_slot]
                    await apply_roles(user, key, "none")
                    changed = True
                else: await msg.remove_reaction(payload.emoji, user)

            if changed: save_data(key, data); await refresh_displays(key, guild)

# ─── COMMANDS ─────────────────────────────────────────────────────────────────
@bot.command(name="register", aliases=["reg"])
async def register(ctx, clan_name: str, clan_tag: str, manager: discord.Member = None):
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id == v["reg_channel"]), None)
    if not key: return
    target_manager = manager if manager else ctx.author
    if target_manager.id in BANNED_USERS: return await ctx.send(f"{BAN_EMOJI} ბანი გაქვს!")
    data = get_data(key)
    if any(t["manager_id"] == target_manager.id for t in data["teams"] + data["waitlist"]): return await ctx.send("Already in!")
    
    # ავტომატური ✅
    new_team = {"name": clan_name, "tag": clan_tag.upper(), "manager_id": target_manager.id, "confirmed": True}
    
    if len(data["teams"]) < 22:
        data["teams"].append(new_team); await apply_roles(target_manager, key, "main")
        msg = f"{CONFIRM_EMOJI} **{clan_name}** In!"
    else:
        data["waitlist"].append(new_team); await apply_roles(target_manager, key, "wait")
        msg = f"{WAIT_EMOJI} **{clan_name}** Waitlist!"
    
    save_data(key, data); await refresh_displays(key, ctx.guild); await ctx.send(msg)

@bot.command()
@commands.has_permissions(administrator=True)
async def edit(ctx, slot_num: int, manager: discord.Member, clan_tag: str, *, clan_name: str):
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]), None)
    if not key: return
    data = get_data(key)
    if slot_num in [24, 25]:
        data["vips"][str(slot_num)] = {"name": clan_name, "tag": clan_tag.upper(), "manager_id": manager.id, "confirmed": True}
        await apply_roles(manager, key, "main")
    elif 2 <= slot_num <= 23:
        idx = slot_num - 2
        new_team = {"name": clan_name, "tag": clan_tag.upper(), "manager_id": manager.id, "confirmed": True}
        if idx < len(data["teams"]):
            old_m = ctx.guild.get_member(data["teams"][idx]["manager_id"])
            if old_m: await apply_roles(old_m, key, "none")
            data["teams"][idx] = new_team
        else: data["teams"].append(new_team)
        await apply_roles(manager, key, "main")
    save_data(key, data); await refresh_displays(key, ctx.guild)

@bot.command()
@commands.has_permissions(administrator=True)
async def reset(ctx):
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]), None)
    if key: save_data(key, {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"}); await refresh_displays(key, ctx.guild)

@bot.event
async def on_ready(): print(f"SYSTEM: {bot.user.name} IS ONLINE")

bot.run(os.getenv('DISCORD_TOKEN'))
