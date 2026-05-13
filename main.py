import discord
from discord.ext import commands
import os
import logging
import certifi
import asyncio
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('BelisBot')
load_dotenv()

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

REACT_CONFIRM_ID = 1503686337415479337 
REACT_CANCEL_ID  = 1503686325226831943 
YES_EMOJI        = "<:yes_yes:1503890574858518568>"
WATCH_CHANNEL    = 1485959324978249831
WATCH_USER       = 1435624557779095572

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

# ლოკალური ქეში მესიჯებისთვის
last_msg_ids = {}

# ─── DATABASE FUNCTIONS ──────────────────────────────────────────────────────
def get_data(key: str) -> dict:
    res = collection.find_one({"_id": key})
    return res if res else {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"}

def save_data(key: str, data: dict):
    collection.update_one({"_id": key}, {"$set": data}, upsert=True)

# ─── ROLE LOGIC ──────────────────────────────────────────────────────────────
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
    except: pass

# ─── EMBED BUILDERS ──────────────────────────────────────────────────────────
def build_slot_embed(scrim_key: str, data: dict) -> discord.Embed:
    cfg = SCRIMS[scrim_key]
    teams, vips = data.get("teams", []), data.get("vips", {})
    total = len(teams) + len(vips)
    conf = sum(1 for t in teams if t.get("confirmed")) + sum(1 for v in vips.values() if v.get("confirmed"))
    
    bar_on = round((len(teams) / 22) * 20) if len(teams) > 0 else 0
    bar = "▰" * bar_on + "▱" * (20 - bar_on)

    embed = discord.Embed(color=cfg["color"], timestamp=datetime.utcnow())
    embed.set_author(name=f"🏆  {cfg['name']}")
    embed.description = f"🟢 **OPEN** ╎ **{total + 1}/25** Slots\n```{bar}```"

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
        else: right.append(f"{VIP_SLOT_EMOJI} `{s}` *VIP Reserved*")

    embed.add_field(name="◈ 01–13", value="\n".join(left), inline=True)
    embed.add_field(name="◈ 14–25", value="\n".join(right), inline=True)
    embed.set_footer(text=f"ID: {scrim_key}") # აქ ვმალავთ სკრიმის აიდის საპოვნელად
    return embed

# ─── REFRESH LOGIC (SMART FIX) ────────────────────────────────────────────────
async def refresh_displays(scrim_key: str, guild: discord.Guild):
    cfg = SCRIMS[scrim_key]
    data = get_data(scrim_key)
    slot_ch = bot.get_channel(cfg["slot_channel"])
    if not slot_ch: return

    embed = build_slot_embed(scrim_key, data)
    target_msg = None

    # 1. ჯერ ვამოწმებთ ქეშს
    if scrim_key in last_msg_ids:
        try: target_msg = await slot_ch.fetch_message(last_msg_ids[scrim_key])
        except: target_msg = None

    # 2. თუ ქეშში არაა, ვეძებთ ჩანელში ფუტერის ID-ით
    if not target_msg:
        async for m in slot_ch.history(limit=30):
            if m.author == bot.user and m.embeds:
                if m.embeds[0].footer.text == f"ID: {scrim_key}":
                    target_msg = m
                    last_msg_ids[scrim_key] = m.id
                    break

    # 3. თუ იპოვა - დააედითოს, თუ არა - ახალი
    if target_msg:
        await target_msg.edit(embed=embed)
    else:
        # ძველი მესეჯების გასუფთავება დუბლირების თავიდან ასაცილებლად
        async for m in slot_ch.history(limit=20):
            if m.author == bot.user and m.embeds and m.embeds[0].footer.text == f"ID: {scrim_key}":
                await m.delete()
        
        new_msg = await slot_ch.send(embed=embed)
        last_msg_ids[scrim_key] = new_msg.id
        await new_msg.add_reaction(f"<:Red_Verified:{REACT_CONFIRM_ID}>")
        await new_msg.add_reaction(f"<:verify_red_cross:{REACT_CANCEL_ID}>")

    # ვეითლისტის განახლება
    wait_ch = bot.get_channel(cfg["wait_channel"])
    if wait_ch:
        wl = data.get("waitlist", [])
        w_embed = discord.Embed(title=f"📋 {cfg['name']} - WAITLIST", color=0x2B2D31)
        w_embed.description = "\n".join([f"`#{i+1}` <@{t['manager_id']}>" for i, t in enumerate(wl)]) if wl else "Empty"
        w_embed.set_footer(text=f"WAIT_ID: {scrim_key}")

        target_w = None
        async for m in wait_ch.history(limit=20):
            if m.author == bot.user and m.embeds and m.embeds[0].footer.text == f"WAIT_ID: {scrim_key}":
                target_w = m
                break
        
        if target_w: await target_w.edit(embed=w_embed)
        else: await wait_ch.send(embed=w_embed)

# ─── EVENTS & COMMANDS ───────────────────────────────────────────────────────
@bot.event
async def on_ready():
    logger.info(f"✅ BelisBot ჩაირთო: {bot.user}")

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id: return
    guild = bot.get_guild(payload.guild_id)
    ch = bot.get_channel(payload.channel_id)
    msg = await ch.fetch_message(payload.message_id)
    
    if not msg.embeds or "ID: " not in msg.embeds[0].footer.text: return
    scrim_key = msg.embeds[0].footer.text.replace("ID: ", "")
    
    member = guild.get_member(payload.user_id)
    data = get_data(scrim_key)
    changed = False

    try: await msg.remove_reaction(payload.emoji, member)
    except: pass

    if payload.emoji.id == REACT_CONFIRM_ID:
        for t in data["teams"]:
            if t["manager_id"] == member.id: t["confirmed"] = True; changed = True
        for s, v in data["vips"].items():
            if v["manager_id"] == member.id: v["confirmed"] = True; changed = True

    elif payload.emoji.id == REACT_CANCEL_ID:
        for i, t in enumerate(data["teams"]):
            if t["manager_id"] == member.id:
                data["teams"].pop(i)
                await apply_roles(member, scrim_key, "none")
                if data["waitlist"]:
                    p = data["waitlist"].pop(0)
                    data["teams"].append(p)
                    pm = guild.get_member(p["manager_id"])
                    await apply_roles(pm, scrim_key, "main")
                changed = True; break
        if not changed:
            for s in ["24", "25"]:
                if s in data["vips"] and data["vips"][s]["manager_id"] == member.id:
                    del data["vips"][s]; await apply_roles(member, scrim_key, "none"); changed = True; break

    if changed:
        save_data(scrim_key, data)
        await refresh_displays(scrim_key, guild)

@bot.command(name="register", aliases=["reg"])
async def register(ctx, clan_name: str, clan_tag: str, manager: discord.Member = None):
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id == v["reg_channel"]), None)
    if not key: return
    target = manager or ctx.author
    data = get_data(key)

    if any(t["manager_id"] == target.id for t in data["teams"] + data["waitlist"]):
        return await ctx.send(f"⚠️ {target.mention} უკვე ხარ სიაში!", delete_after=5)

    new_team = {"name": clan_name, "tag": clan_tag.upper(), "manager_id": target.id, "confirmed": False}
    if len(data["teams"]) < 22:
        data["teams"].append(new_team); await apply_roles(target, key, "main")
    else:
        data["waitlist"].append(new_team); await apply_roles(target, key, "wait")

    save_data(key, data)
    await refresh_displays(key, ctx.guild)
    await ctx.message.add_reaction("✅")

@bot.command()
@commands.has_permissions(administrator=True)
async def reset(ctx):
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]), None)
    if key:
        save_data(key, {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"})
        await refresh_displays(key, ctx.guild)
        await ctx.send(f"🔄 {key} გასუფთავდა!")

bot.run(os.getenv('DISCORD_TOKEN'))
