import discord
from discord.ext import commands
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

# აქ ჩაწერე დაბანილი მომხმარებლების ID
BANNED_USERS = [1234567890]

# ─── DATABASE SETUP ───────────────────────────────────────────────────────────
try:
    MONGO_URL = os.getenv('MONGO_URL')
    cluster = MongoClient(MONGO_URL, tlsCAFile=certifi.where())
    db = cluster["belis_scrims"]
    collection = db["storage"]
    logger.info("MongoDB connected.")
except Exception as e:
    logger.error(f"MongoDB Connection Error: {e}")

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
VIP_SLOT_EMOJI   = "<:TDE_vip_black_idp:1503689111901311126>"
CONFIRM_DISPLAY  = "<:confirmed2:1503857123359064154>"
WAIT_DISPLAY     = "<a:loading_loading_loading:1503689198249574542>"

# Reaction IDs (მხოლოდ ID-ები შედარებისთვის)
REACT_CONFIRM_ID = 1503686337415479337  # Red_Verified
REACT_CANCEL_ID  = 1503686325226831943  # verify_red_cross
REACT_WAIT_EMOJI = "<:WAITLISTSF:1503687118302482562>"

YES_EMOJI      = "<:yes_yes:1503890574858518568>"
WATCH_CHANNEL  = 1485959324978249831
WATCH_USER     = 1435624557779095572

ALLOWED_REG_ROLES = {1255216304831594616, 1255216501305376850}

SCRIMS = {
    "scrim_22": {
        "name": "22:00 SCRIMS",
        "reg_channel":  1503324709557895288,
        "slot_channel": 1503325306285588510,
        "wait_channel": 1503325883182747742,
        "role_id":      1503327762109304863,
        "wait_role_id": 1503328170311548949,
        "color": 0xFFD700,
    },
    "scrim_00": {
        "name": "00:30 SCRIMS",
        "reg_channel":  1503327037832691832,
        "slot_channel": 1503327123337904189,
        "wait_channel": 1503327364749459506,
        "role_id":      1503327805897707591,
        "wait_role_id": 1503328171884412978,
        "color": 0x5865F2,
    },
}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="%", intents=intents, help_command=None)

# მეხსიერება მესიჯების ID-სთვის
last_msg_ids = {}

# ─── DATABASE FUNCTIONS ──────────────────────────────────────────────────────

def get_data(key: str) -> dict:
    res = collection.find_one({"_id": key})
    if not res:
        return {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"}
    return res

def save_data(key: str, data: dict):
    collection.update_one({"_id": key}, {"$set": data}, upsert=True)

# ─── ROLES LOGIC ─────────────────────────────────────────────────────────────

async def apply_roles(member: discord.Member, scrim_key: str, action: str):
    if not member or not isinstance(member, discord.Member): return
    cfg = SCRIMS[scrim_key]
    r_main = member.guild.get_role(cfg["role_id"])
    r_wait = member.guild.get_role(cfg["wait_role_id"])
    
    try:
        if action == "main":
            if r_wait and r_wait in member.roles: await member.remove_roles(r_wait)
            if r_main and r_main not in member.roles: await member.add_roles(r_main)
        elif action == "wait":
            if r_main and r_main in member.roles: await member.remove_roles(r_main)
            if r_wait and r_wait not in member.roles: await member.add_roles(r_wait)
        elif action == "none":
            if r_main and r_main in member.roles: await member.remove_roles(r_main)
            if r_wait and r_wait in member.roles: await member.remove_roles(r_wait)
    except Exception as e:
        logger.warning(f"Role error: {e}")

# ─── EMBED BUILDERS ──────────────────────────────────────────────────────────

def build_slot_embed(scrim_key: str, data: dict) -> discord.Embed:
    cfg = SCRIMS[scrim_key]
    teams, vips = data.get("teams", []), data.get("vips", {})
    
    total_filled = len(teams) + len(vips)
    confirmed_count = sum(1 for t in teams if t.get("confirmed")) + sum(1 for v in vips.values() if v.get("confirmed"))
    unconfirmed = total_filled - confirmed_count

    bar_on = round((len(teams) / 22) * 20) if len(teams) > 0 else 0
    bar = "▰" * bar_on + "▱" * (20 - bar_on)
    pct = round((len(teams) / 22) * 100)

    embed = discord.Embed(color=cfg["color"], timestamp=datetime.utcnow())
    embed.set_author(name=f"🏆  {cfg['name']}")
    embed.description = (
        f"🟢 **OPEN** ╎ **{total_filled + 1}/25** Slots ╎ "
        f"{CONFIRM_DISPLAY} **{confirmed_count}** ╎ "
        f"{WAIT_DISPLAY} **{unconfirmed}**\n```{bar}  {pct}%```"
    )

    left, right = [], []
    left.append("🛡️ `01` **ELITE HOST**")
    
    for i in range(2, 24):
        idx = i - 2
        line = f"◻️ `{i:02d}` *Empty*"
        if idx < len(teams):
            t = teams[idx]
            icon = CONFIRM_DISPLAY if t.get("confirmed") else WAIT_DISPLAY
            line = f"{icon} `{i:02d}` **{t['name']}**\n└ <@{t['manager_id']}>"
        
        if i <= 13: left.append(line)
        else: right.append(line)

    right.append("─────────────")
    for s in ["24", "25"]:
        v = vips.get(s)
        if v:
            icon = CONFIRM_DISPLAY if v.get("confirmed") else WAIT_DISPLAY
            right.append(f"{icon} {VIP_SLOT_EMOJI} `{s}` **{v['name']}**\n└ <@{v['manager_id']}>")
        else:
            right.append(f"{VIP_SLOT_EMOJI} `{s}` *VIP Reserved*")

    embed.add_field(name="◈ 01–13", value="\n".join(left), inline=True)
    embed.add_field(name="◈ 14–25", value="\n".join(right), inline=True)
    return embed

def build_wait_embed(scrim_key: str, data: dict) -> discord.Embed:
    cfg = SCRIMS[scrim_key]
    wl = data.get("waitlist", [])
    embed = discord.Embed(title=f"📋 {cfg['name']} - WAITLIST", color=0x2B2D31, timestamp=datetime.utcnow())
    if wl:
        lines = [f"{WAIT_DISPLAY} `#{i+1:02d}` **{t['name']}**\n└ <@{t['manager_id']}>" for i, t in enumerate(wl)]
        embed.description = "\n".join(lines)
    else:
        embed.description = "```\nWaitlist is empty\n```"
    return embed

# ─── REFRESH LOGIC (FIXED) ───────────────────────────────────────────────────

async def refresh_displays(scrim_key: str, guild: discord.Guild):
    cfg = SCRIMS[scrim_key]
    data = get_data(scrim_key)
    
    # 1. Slot Channel Update
    slot_ch = bot.get_channel(cfg["slot_channel"])
    if slot_ch:
        embed = build_slot_embed(scrim_key, data)
        target_msg = None
        
        # ვეძებთ ბოლო მესიჯს თუ მეხსიერებაში არაა
        if scrim_key not in last_msg_ids:
            async for m in slot_ch.history(limit=20):
                if m.author == bot.user and m.embeds and cfg["name"] in m.embeds[0].author.name:
                    target_msg = m
                    last_msg_ids[scrim_key] = m.id
                    break
        else:
            try: target_msg = await slot_ch.fetch_message(last_msg_ids[scrim_key])
            except: target_msg = None

        if target_msg:
            await target_msg.edit(embed=embed)
        else:
            await slot_ch.purge(limit=5, check=lambda m: m.author == bot.user)
            new_msg = await slot_ch.send(embed=embed)
            last_msg_ids[scrim_key] = new_msg.id
            await new_msg.add_reaction(f"<:Red_Verified:{REACT_CONFIRM_ID}>")
            await new_msg.add_reaction(f"<:verify_red_cross:{REACT_CANCEL_ID}>")

    # 2. Waitlist Channel Update
    wait_ch = bot.get_channel(cfg["wait_channel"])
    if wait_ch:
        w_embed = build_wait_embed(scrim_key, data)
        w_key = f"{scrim_key}_wait"
        target_w = None

        if w_key not in last_msg_ids:
            async for m in wait_ch.history(limit=20):
                if m.author == bot.user and m.embeds and cfg["name"] in m.embeds[0].title:
                    target_w = m
                    last_msg_ids[w_key] = m.id
                    break
        else:
            try: target_w = await wait_ch.fetch_message(last_msg_ids[w_key])
            except: target_w = None

        if target_w: await target_w.edit(embed=w_embed)
        else:
            new_w = await wait_ch.send(embed=w_embed)
            last_msg_ids[w_key] = new_w.id

# ─── EVENTS ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    logger.info(f"✅ BelisBot online as {bot.user}")

@bot.event
async def on_message(message):
    if message.channel.id == WATCH_CHANNEL and WATCH_USER in [m.id for m in message.mentions]:
        await message.add_reaction(YES_EMOJI)
        await message.channel.send(f"{YES_EMOJI} ხო ძმა რა ხდება")
    await bot.process_commands(message)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id: return
    
    scrim_key = next((k for k, v in SCRIMS.items() if v["slot_channel"] == payload.channel_id), None)
    if not scrim_key or payload.message_id != last_msg_ids.get(scrim_key): return

    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)
    data = get_data(scrim_key)
    changed = False

    try:
        ch = bot.get_channel(payload.channel_id)
        m = await ch.fetch_message(payload.message_id)
        await m.remove_reaction(payload.emoji, member)
    except: pass

    # CONFIRM
    if payload.emoji.id == REACT_CONFIRM_ID:
        for t in data["teams"]:
            if t["manager_id"] == member.id and not t["confirmed"]:
                t["confirmed"] = True
                changed = True
        for s in ["24", "25"]:
            if s in data["vips"] and data["vips"][s]["manager_id"] == member.id:
                data["vips"][s]["confirmed"] = True
                changed = True

    # CANCEL
    elif payload.emoji.id == REACT_CANCEL_ID:
        for i, t in enumerate(data["teams"]):
            if t["manager_id"] == member.id:
                data["teams"].pop(i)
                await apply_roles(member, scrim_key, "none")
                changed = True
                if data["waitlist"]:
                    promoted = data["waitlist"].pop(0)
                    data["teams"].append(promoted)
                    p_mem = guild.get_member(promoted["manager_id"])
                    await apply_roles(p_mem, scrim_key, "main")
                break
        if not changed:
            for s in ["24", "25"]:
                if s in data["vips"] and data["vips"][s]["manager_id"] == member.id:
                    del data["vips"][s]
                    await apply_roles(member, scrim_key, "none")
                    changed = True
                    break

    if changed:
        save_data(scrim_key, data)
        await refresh_displays(scrim_key, guild)

# ─── COMMANDS ────────────────────────────────────────────────────────────────

@bot.command(name="register", aliases=["reg"])
async def register(ctx, clan_name: str, clan_tag: str, manager: discord.Member = None):
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id == v["reg_channel"]), None)
    if not key: return

    target = manager or ctx.author
    data = get_data(key)

    if any(t["manager_id"] == target.id for t in data["teams"] + data["waitlist"]) or \
       any(v["manager_id"] == target.id for v in data["vips"].values()):
        return await ctx.send(f"⚠️ {target.display_name} უკვე რეგისტრირებული ხარ!", delete_after=5)

    new_team = {"name": clan_name, "tag": clan_tag.upper(), "manager_id": target.id, "confirmed": False}

    if len(data["teams"]) < 22:
        data["teams"].append(new_team)
        await apply_roles(target, key, "main")
        await ctx.message.add_reaction("✅")
    else:
        data["waitlist"].append(new_team)
        await apply_roles(target, key, "wait")
        await ctx.message.add_reaction("⏳")

    save_data(key, data)
    await refresh_displays(key, ctx.guild)

@bot.command()
@commands.has_permissions(administrator=True)
async def reset(ctx):
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]), None)
    if not key: return
    save_data(key, {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"})
    await refresh_displays(key, ctx.guild)
    await ctx.send("🔄 სკრიმი გასუფთავდა!", delete_after=5)

@bot.command()
@commands.has_permissions(administrator=True)
async def remove(ctx, slot_num: int):
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]), None)
    if not key: return
    data = get_data(key)
    
    if 2 <= slot_num <= 23:
        idx = slot_num - 2
        if idx < len(data["teams"]):
            removed = data["teams"].pop(idx)
            m = ctx.guild.get_member(removed["manager_id"])
            await apply_roles(m, key, "none")
            if data["waitlist"]:
                promoted = data["waitlist"].pop(0)
                data["teams"].append(promoted)
                pm = ctx.guild.get_member(promoted["manager_id"])
                await apply_roles(pm, key, "main")
            save_data(key, data)
            await refresh_displays(key, ctx.guild)
            await ctx.send(f"✅ სლოტი {slot_num} გათავისუფლდა.")

bot.run(os.getenv('DISCORD_TOKEN'))
