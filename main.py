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
ALLOWED_REG_ROLES = {1255216304831594616, 1255216501305376850}

# ─── DATABASE ─────────────────────────────────────────────────────────────────
try:
    MONGO_URL = os.getenv('MONGO_URL')
    cluster = MongoClient(MONGO_URL, tlsCAFile=certifi.where())
    db = cluster["belis_scrims"]
    collection = db["storage"]
    logger.info("MongoDB connected.")
except Exception as e:
    logger.error(f"MongoDB Connection Error: {e}")

# ─── EMOJIS & CONSTANTS ───────────────────────────────────────────────────────
VIP_SLOT_EMOJI   = "<:TDE_vip_black_idp:1503689111901311126>"
CONFIRM_DISPLAY  = "<:confirmed2:1503857123359064154>"
WAIT_DISPLAY     = "<a:loading_loading_loading:1503689198249574542>"
REACT_CONFIRM    = "<:Red_Verified:1503686337415479337>"
REACT_CANCEL     = "<:verify_red_cross:1503686325226831943>"

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

last_msg_ids = {}

# ─── DATABASE HELPERS ─────────────────────────────────────────────────────────
def get_data(key):
    res = collection.find_one({"_id": key})
    return res if res else {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"}

def save_data(key, data):
    collection.update_one({"_id": key}, {"$set": data}, upsert=True)

# ─── ROLE MANAGEMENT ──────────────────────────────────────────────────────────
async def apply_roles(member, scrim_key, action):
    if not member or not isinstance(member, discord.Member): return
    cfg = SCRIMS[scrim_key]
    r_main = member.guild.get_role(cfg["role_id"])
    r_wait = member.guild.get_role(cfg["wait_role_id"])
    try:
        if action == "main":
            if r_wait and r_wait in member.roles: await member.remove_roles(r_wait)
            if r_main: await member.add_roles(r_main)
        elif action == "wait":
            if r_main and r_main in member.roles: await member.remove_roles(r_main)
            if r_wait: await member.add_roles(r_wait)
        elif action == "none":
            if r_main and r_main in member.roles: await member.remove_roles(r_main)
            if r_wait and r_wait in member.roles: await member.remove_roles(r_wait)
    except: pass

# ─── NEW COMPACT LIST BUILDER ─────────────────────────────────────────────────
def build_slot_embed(scrim_key, data, guild):
    cfg = SCRIMS[scrim_key]
    teams = data.get("teams", [])
    vips = data.get("vips", {})
    
    total_slots = len(teams) + len(vips) + 1
    
    embed = discord.Embed(color=cfg["color"], timestamp=datetime.utcnow())
    embed.set_author(name=f"🏆 {cfg['name']}")
    
    # ლისტის აწყობა
    lines = []
    lines.append("🛡️ `01` **ELITE HOST**") # Admin slot
    
    # Regular Slots (2-23)
    for i in range(2, 24):
        idx = i - 2
        if idx < len(teams):
            t = teams[idx]
            icon = CONFIRM_DISPLAY if t.get("confirmed") else WAIT_DISPLAY
            # ვიყენებთ მხოლოდ სახელს (Mention-ის გარეშე), რომ ადგილი დავზოგოთ
            m = guild.get_member(t['manager_id'])
            manager_name = m.display_name if m else f"ID:{t['manager_id']}"
            lines.append(f"{icon} `{i:02d}.` **{t['name']}** `[{t['tag']}]` ╎ {manager_name}")
        else:
            lines.append(f"◻️ `{i:02d}.` *თავისუფალია*")

    lines.append("─────────────────────")
    
    # VIP Slots (24-25)
    for i in [24, 25]:
        v = vips.get(str(i))
        if v:
            icon = CONFIRM_DISPLAY if v.get("confirmed") else WAIT_DISPLAY
            m = guild.get_member(v['manager_id'])
            m_name = m.display_name if m else "VIP"
            lines.append(f"{icon} {VIP_SLOT_EMOJI} `{i}.` **{v['name']}** ╎ {m_name}")
        else:
            lines.append(f"{VIP_SLOT_EMOJI} `{i}.` *VIP დაჯავშნულია*")

    # მთლიან ტექსტს ვსვამთ Description-ში (ასე ლიმიტს არ არღვევს)
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"სულ: {total_slots}/25 სლოტი • ✅ - დადასტურება • ❌ - გასვლა")
    return embed

def build_wait_embed(scrim_key, data, guild):
    cfg = SCRIMS[scrim_key]
    wl = data.get("waitlist", [])
    embed = discord.Embed(color=0x2B2D31, title=f"📋 {cfg['name']} - WAITLIST")
    
    if not wl:
        embed.description = "```\nვეითლისტი ცარიელია\n```"
    else:
        lines = []
        for i, t in enumerate(wl):
            icon = CONFIRM_DISPLAY if t.get("confirmed") else WAIT_DISPLAY
            lines.append(f"{icon} `#{i+1:02d}` **{t['name']}** `[{t['tag']}]`")
        embed.description = "\n".join(lines)
    return embed

# ─── REFRESH LOGIC ────────────────────────────────────────────────────────────
async def refresh_displays(scrim_key, guild):
    cfg, data = SCRIMS[scrim_key], get_data(scrim_key)
    
    # Slot Channel
    slot_ch = bot.get_channel(cfg["slot_channel"])
    if slot_ch:
        embed = build_slot_embed(scrim_key, data, guild)
        msg_id = last_msg_ids.get(f"{scrim_key}_slot")
        try:
            msg = await slot_ch.fetch_message(msg_id)
            await msg.edit(embed=embed)
        except:
            await slot_ch.purge(limit=5, check=lambda m: m.author == bot.user)
            new_msg = await slot_ch.send(embed=embed)
            last_msg_ids[f"{scrim_key}_slot"] = new_msg.id
            await new_msg.add_reaction(REACT_CONFIRM)
            await new_msg.add_reaction(REACT_CANCEL)

    # Waitlist Channel
    wait_ch = bot.get_channel(cfg["wait_channel"])
    if wait_ch:
        w_embed = build_wait_embed(scrim_key, data, guild)
        w_id = last_msg_ids.get(f"{scrim_key}_wait")
        try:
            w_msg = await wait_ch.fetch_message(w_id)
            await w_msg.edit(embed=w_embed)
        except:
            await wait_ch.purge(limit=5, check=lambda m: m.author == bot.user)
            new_w = await wait_ch.send(embed=w_embed)
            last_msg_ids[f"{scrim_key}_wait"] = new_w.id

# ─── CORE EVENTS ──────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    logger.info(f"✅ {bot.user} ჩაირთო!")
    for k, v in SCRIMS.items():
        for t in ["slot", "wait"]:
            ch = bot.get_channel(v[f"{t}_channel"])
            if ch:
                async for m in ch.history(limit=50):
                    if m.author == bot.user and m.embeds:
                        last_msg_ids[f"{k}_{t}"] = m.id
                        break

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id: return
    
    for scrim_key, cfg in SCRIMS.items():
        if payload.message_id != last_msg_ids.get(f"{scrim_key}_slot"): continue
        
        guild = bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        if not member: continue

        # რეაქციის წაშლა
        try:
            channel = bot.get_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            await message.remove_reaction(payload.emoji, member)
        except: pass

        data = get_data(scrim_key)
        emoji = str(payload.emoji)
        changed = False

        # Confirm (✅)
        if emoji in REACT_CONFIRM:
            for t in data["teams"]:
                if t["manager_id"] == member.id:
                    t["confirmed"] = True
                    changed = True
            for s in ["24", "25"]:
                if data["vips"].get(s) and data["vips"][s]["manager_id"] == member.id:
                    data["vips"][s]["confirmed"] = True
                    changed = True

        # Cancel (❌)
        elif emoji in REACT_CANCEL:
            idx = next((i for i, t in enumerate(data["teams"]) if t["manager_id"] == member.id), None)
            if idx is not None:
                data["teams"].pop(idx)
                await apply_roles(member, scrim_key, "none")
                if data["waitlist"]:
                    p = data["waitlist"].pop(0)
                    p["confirmed"] = False
                    data["teams"].append(p)
                    pm = guild.get_member(p["manager_id"])
                    if pm: await apply_roles(pm, scrim_key, "main")
                changed = True
            
            for s in ["24", "25"]:
                if data["vips"].get(s) and data["vips"][s]["manager_id"] == member.id:
                    del data["vips"][s]
                    await apply_roles(member, scrim_key, "none")
                    changed = True

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
        return await ctx.send(f"⚠️ **{target.display_name}** უკვე რეგისტრირებულია!", delete_after=5)

    new_team = {"name": clan_name, "tag": clan_tag.upper(), "manager_id": target.id, "confirmed": False}
    
    if len(data["teams"]) < 22:
        data["teams"].append(new_team)
        await apply_roles(target, key, "main")
    else:
        data["waitlist"].append(new_team)
        await apply_roles(target, key, "wait")

    save_data(key, data)
    await refresh_displays(key, ctx.guild)
    await ctx.message.add_reaction("✅")

# ─── ADMIN COMMANDS ──────────────────────────────────────────────────────────
@bot.command()
@commands.has_permissions(administrator=True)
async def reset(ctx):
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]), None)
    if not key: return
    save_data(key, {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"})
    await refresh_displays(key, ctx.guild)
    await ctx.send("🔄 სკრიმი გასუფთავდა!")

bot.run(os.getenv('DISCORD_TOKEN'))
