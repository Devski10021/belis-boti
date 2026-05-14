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
VIP_EMOJI        = "<a:loading_loading_loading:1503689198249574542>"
VIP_SLOT_EMOJI   = "<:TDE_vip_black_idp:1503689111901311126>"
CONFIRM_DISPLAY  = "<:confirmed2:1503857123359064154>"
CANCEL_DISPLAY   = "<:verify_red_cross:1503686325226831943>"
WAIT_DISPLAY     = "<a:loading_loading_loading:1503689198249574542>"

REACT_CONFIRM = "<:Red_Verified:1503686337415479337>"
REACT_CANCEL  = "<:verify_red_cross:1503686325226831943>"
REACT_WAIT    = "<:WAITLISTSF:1503687118302482562>"

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

# მესიჯების ID-ების დროებითი საცავი
last_msg_ids: dict[str, int] = {}

# ─── DATABASE FUNCTIONS ───────────────────────────────────────────────────────

def get_data(key: str) -> dict:
    res = collection.find_one({"_id": key})
    return res if res else {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"}

def save_data(key: str, data: dict):
    collection.update_one({"_id": key}, {"$set": data}, upsert=True)

# ─── ROLE MANAGEMENT ──────────────────────────────────────────────────────────

async def apply_roles(member: discord.Member, scrim_key: str, action: str):
    if not member or not isinstance(member, discord.Member):
        return
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
    except Exception as e:
        logger.warning(f"Role error for {member.display_name}: {e}")

# ─── EMBED BUILDERS ──────────────────────────────────────────────────────────

def build_slot_embed(scrim_key: str, data: dict, guild: discord.Guild) -> discord.Embed:
    cfg   = SCRIMS[scrim_key]
    teams = data.get("teams", [])
    vips  = data.get("vips", {})

    total_filled    = len(teams) + len(vips)
    confirmed_count = (sum(1 for t in teams if t.get("confirmed"))
                     + sum(1 for v in vips.values() if v.get("confirmed")))
    unconfirmed     = total_filled - confirmed_count

    filled_regular = len(teams)
    bar_on  = round((filled_regular / 22) * 20)
    bar_off = 20 - bar_on
    bar     = "▰" * bar_on + "▱" * bar_off
    pct     = round((filled_regular / 22) * 100)

    status_open = data.get("status", "OPEN") == "OPEN"
    status_icon = "🟢" if status_open else "🔴"
    status_text = "OPEN" if status_open else "CLOSED"

    embed = discord.Embed(color=cfg["color"], timestamp=datetime.utcnow())
    embed.set_author(name=f"🏆  {cfg['name']}")
    embed.description = (
        f"{status_icon} **{status_text}** ╎  "
        f"**{total_filled + 1} / 25** სლოტი  ╎  "
        f"{CONFIRM_DISPLAY} **{confirmed_count}** დადასტ.  ╎  "
        f"{WAIT_DISPLAY} **{unconfirmed}** მოლოდ.\n"
        f"```{bar}  {pct}%```"
    )

    def slot_line(slot_num, teams_list):
        idx = slot_num - 2
        if idx < len(teams_list):
            t    = teams_list[idx]
            icon = CONFIRM_DISPLAY if t.get("confirmed") else WAIT_DISPLAY
            return f"{icon} `{slot_num:02d}` **{t['name']}** `{t['tag']}`\n└ <@{t['manager_id']}>"
        return f"◻️ `{slot_num:02d}` *— თავისუფალია —*"

    left = ["🛡️ `01` **ELITE HOST** *[ADMIN]*"]
    for s in range(2, 14):
        left.append(slot_line(s, teams))

    right = []
    for s in range(14, 24):
        right.append(slot_line(s, teams))
    right.append("─────────────")
    for slot_num in [24, 25]:
        v = vips.get(str(slot_num))
        if v:
            icon = CONFIRM_DISPLAY if v.get("confirmed") else WAIT_DISPLAY
            right.append(f"{icon} {VIP_SLOT_EMOJI} `{slot_num}` **{v['name']}** `{v['tag']}`\n└ <@{v['manager_id']}>")
        else:
            right.append(f"{VIP_SLOT_EMOJI} `{slot_num}` *VIP — დაჯავშნულია*")

    embed.add_field(name="◈ სლოტები 01–13", value="\n".join(left), inline=True)
    embed.add_field(name="◈ სლოტები 14–25", value="\n".join(right), inline=True)
    embed.set_footer(text="✅ confirm საკუთარი სლოტი  ·  ❌ cancel სლოტიდან გასვლა")
    return embed

def build_wait_embed(scrim_key: str, data: dict, guild: discord.Guild) -> discord.Embed:
    cfg = SCRIMS[scrim_key]
    wl  = data.get("waitlist", [])
    embed = discord.Embed(color=0x2B2D31, timestamp=datetime.utcnow())
    embed.set_author(name=f"📋  {cfg['name']}  —  WAITLIST")

    if wl:
        lines = []
        for i, t in enumerate(wl):
            icon = CONFIRM_DISPLAY if t.get("confirmed") else WAIT_DISPLAY
            lines.append(f"{icon}  `#{i+1:02d}`  ╎  **{t['name']}** `{t['tag']}`\n⠀⠀⠀⠀⠀╰ <@{t['manager_id']}>")
            if i < len(wl) - 1: lines.append("┄" * 22)
        embed.description = "\n".join(lines)
    else:
        embed.description = "```\n ვეითლისტი ცარიელია\n```"
    
    embed.set_footer(text="სლოტი გათავისუფლდება → ვეითლისტიდან პირველი ჩადის ავტომატურად")
    return embed

# ─── DISPLAY UPDATER (კრიტიკული ნაწილი) ──────────────────────────────────────

async def refresh_displays(scrim_key: str, guild: discord.Guild):
    cfg  = SCRIMS[scrim_key]
    data = get_data(scrim_key)

    # 1. სლოტების ჩანელი
    slot_ch = bot.get_channel(cfg["slot_channel"])
    if slot_ch:
        embed = build_slot_embed(scrim_key, data, guild)
        msg_id = last_msg_ids.get(scrim_key)
        msg = None

        if msg_id:
            try: msg = await slot_ch.fetch_message(msg_id)
            except: msg = None

        if msg:
            await msg.edit(embed=embed)
        else:
            # თუ მესიჯი ვერ მოიძებნა, ვშლით ბოტის ძველ მესიჯებს და ვსენდავთ ახალს
            await slot_ch.purge(limit=10, check=lambda m: m.author == bot.user)
            msg = await slot_ch.send(embed=embed)
            last_msg_ids[scrim_key] = msg.id
            await msg.add_reaction(REACT_CONFIRM)
            await msg.add_reaction(REACT_CANCEL)

    # 2. ვეითლისტის ჩანელი
    wait_ch = bot.get_channel(cfg["wait_channel"])
    if wait_ch:
        w_embed = build_wait_embed(scrim_key, data, guild)
        w_key = f"{scrim_key}_wait"
        w_msg_id = last_msg_ids.get(w_key)
        w_msg = None

        if w_msg_id:
            try: w_msg = await wait_ch.fetch_message(w_msg_id)
            except: w_msg = None

        if w_msg:
            await w_msg.edit(embed=w_embed)
        else:
            await wait_ch.purge(limit=10, check=lambda m: m.author == bot.user)
            w_msg = await wait_ch.send(embed=w_embed)
            last_msg_ids[w_key] = w_msg.id

# ─── EVENTS ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    logger.info(f"✅  {bot.user} is online.")
    await asyncio.sleep(2)
    
    for scrim_key, cfg in SCRIMS.items():
        # ვეძებთ ბოლო მესიჯებს ისტორიაში (უფრო ღრმად - 100 მესიჯი)
        slot_ch = bot.get_channel(cfg["slot_channel"])
        if slot_ch:
            async for m in slot_ch.history(limit=100):
                if m.author == bot.user and m.embeds:
                    last_msg_ids[scrim_key] = m.id
                    logger.info(f"Found slot msg for {scrim_key}")
                    break
        
        wait_ch = bot.get_channel(cfg["wait_channel"])
        if wait_ch:
            async for m in wait_ch.history(limit=100):
                if m.author == bot.user and m.embeds:
                    last_msg_ids[f"{scrim_key}_wait"] = m.id
                    break

        reg_ch = bot.get_channel(cfg["reg_channel"])
        if reg_ch:
            async for m in reg_ch.history(limit=50):
                if m.author == bot.user and not m.embeds:
                    last_msg_ids[f"{scrim_key}_counter_msg"] = m.id
                    break

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot: return
    if message.channel.id == WATCH_CHANNEL and WATCH_USER in [m.id for m in message.mentions]:
        try:
            await message.add_reaction(YES_EMOJI)
            await message.channel.send(f"{YES_EMOJI} ხო ძმა რა ხდება")
        except: pass
    await bot.process_commands(message)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id: return

    for scrim_key, cfg in SCRIMS.items():
        if payload.message_id != last_msg_ids.get(scrim_key): continue
        
        guild = bot.get_guild(payload.guild_id)
        reactor = guild.get_member(payload.user_id)
        if not reactor: continue

        channel = bot.get_channel(payload.channel_id)
        try:
            msg = await channel.fetch_message(payload.message_id)
            await msg.remove_reaction(payload.emoji, reactor)
        except: pass

        data = get_data(scrim_key)
        emoji_id = str(payload.emoji.id) if payload.emoji.id else str(payload.emoji)
        
        CONFIRM_ID = "1503686337415479337"
        CANCEL_ID  = "1503686325226831943"
        changed = False

        if emoji_id == CONFIRM_ID:
            for t in data["teams"]:
                if t["manager_id"] == reactor.id and not t.get("confirmed"):
                    t["confirmed"] = True
                    changed = True
                    break
            if not changed:
                for s in ["24", "25"]:
                    v = data["vips"].get(s)
                    if v and v["manager_id"] == reactor.id and not v.get("confirmed"):
                        data["vips"][s]["confirmed"] = True
                        changed = True
                        break
            if not changed and reactor.guild_permissions.administrator:
                for t in data["teams"]:
                    if not t.get("confirmed"):
                        t["confirmed"] = True
                        changed = True
                        break

        elif emoji_id == CANCEL_ID:
            target_idx = None
            for i, t in enumerate(data["teams"]):
                if t["manager_id"] == reactor.id:
                    target_idx = i
                    break
            
            if target_idx is not None:
                data["teams"].pop(target_idx)
                await apply_roles(reactor, scrim_key, "none")
                if data["waitlist"]:
                    promoted = data["waitlist"].pop(0)
                    promoted["confirmed"] = False
                    data["teams"].insert(target_idx, promoted)
                    p_member = guild.get_member(promoted["manager_id"])
                    if p_member: await apply_roles(p_member, scrim_key, "main")
                changed = True
            else:
                for s in ["24", "25"]:
                    v = data["vips"].get(s)
                    if v and v["manager_id"] == reactor.id:
                        del data["vips"][s]
                        await apply_roles(reactor, scrim_key, "none")
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

    author_roles = {r.id for r in ctx.author.roles}
    if not (ctx.author.guild_permissions.administrator or (author_roles & ALLOWED_REG_ROLES)):
        return await ctx.send("❌ რეგისტრაციის უფლება არ გაქვს!", delete_after=5)

    target = manager or ctx.author
    if target.id in BANNED_USERS:
        return await ctx.send("🚫 დაბანილი ხარ.", delete_after=5)

    data = get_data(key)
    if any(t["manager_id"] == target.id for t in data["teams"] + data["waitlist"]):
        return await ctx.send(f"⚠️ **{target.display_name}** უკვე რეგისტრირებულია!", delete_after=5)

    new_team = {"name": clan_name, "tag": clan_tag.upper(), "manager_id": target.id, "confirmed": False}

    if len(data["teams"]) < 22:
        data["teams"].append(new_team)
        await apply_roles(target, key, "main")
        react_with = REACT_CONFIRM
    else:
        data["waitlist"].append(new_team)
        await apply_roles(target, key, "wait")
        react_with = REACT_WAIT

    save_data(key, data)
    await refresh_displays(key, ctx.guild)
    try: await ctx.message.add_reaction(react_with)
    except: pass

    # Counter Update
    remaining = 22 - len(data["teams"])
    txt = f"📊 **{remaining}** სლოტი დარჩა!" if remaining > 0 else f"🔴 სლოტები გაივსო! ვეითშია: {len(data['waitlist'])}"
    
    c_key = f"{key}_counter_msg"
    old_c_id = last_msg_ids.get(c_key)
    if old_c_id:
        try:
            m = await ctx.channel.fetch_message(old_c_id)
            await m.delete()
        except: pass
    new_c = await ctx.send(txt)
    last_msg_ids[c_key] = new_c.id

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
async def setvip(ctx, slot: int, member: discord.Member, clan_tag: str, *, clan_name: str):
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]), None)
    if not key or slot not in [24, 25]: return
    data = get_data(key)
    data["vips"][str(slot)] = {"name": clan_name, "tag": clan_tag.upper(), "manager_id": member.id, "confirmed": False}
    save_data(key, data)
    await apply_roles(member, key, "main")
    await refresh_displays(key, ctx.guild)
    await ctx.send(f"✅ VIP {slot} დაყენდა.", delete_after=5)

bot.run(os.getenv('DISCORD_TOKEN'))
