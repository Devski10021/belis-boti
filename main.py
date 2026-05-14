import discord
from discord.ext import commands
import os
import logging
import certifi
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
CONFIRM_DISPLAY  = "<:confirmed:1503685210737217616>"
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

last_msg_ids: dict[str, int] = {}


# ─── DATABASE ────────────────────────────────────────────────────────────────

def get_data(key: str) -> dict:
    res = collection.find_one({"_id": key})
    return res if res else {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"}

def save_data(key: str, data: dict):
    collection.update_one({"_id": key}, {"$set": data}, upsert=True)


# ─── ROLES ───────────────────────────────────────────────────────────────────

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
        logger.warning(f"Role error: {e}")


# ─── EMBED BUILDERS ──────────────────────────────────────────────────────────
#
# ⚡ FIX: კომპაქტური ფორმატი — ერთ ხაზზე ყველაფერი, embed არ გადალახავს 6000 სიმბოლოს ლიმიტს
# ფოტოს მსგავსი სტილი: "01. TeamName [TAG] | @Manager"
#

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
        f"{status_icon} **{status_text}**  ╎  "
        f"**{total_filled + 1} / 25** სლოტი  ╎  "
        f"{CONFIRM_DISPLAY} **{confirmed_count}** დადასტ.  ╎  "
        f"{WAIT_DISPLAY} **{unconfirmed}** მოლოდ.\n"
        f"```{bar}  {pct}%```"
    )

    # ── კომპაქტური ხაზი ──────────────────────────────────────────────────────
    # ფორმატი: "✅ 02. TeamName [TAG] | @Manager"
    # ან       "⏳ 02. TeamName [TAG] | @Manager"  (unconfirmed)
    # ან       "◻️ 02. — თავისუფალია —"
    # ერთი ხაზი ≈ 60 სიმბოლო → 25 სლოტი ≈ 1500 სიმბოლო, ლიმიტი 6000-ია ✓

    def compact_line(slot_num: int) -> str:
        """ერთი კომპაქტური ხაზი სლოტისთვის."""
        if slot_num == 1:
            return f"🛡️ `01` ~~**ELITE HOST** — ADMIN~~"

        if slot_num in [24, 25]:
            v = vips.get(str(slot_num))
            if v:
                m   = guild.get_member(v["manager_id"])
                mgr = m.display_name if m else f"#{v['manager_id']}"
                if v.get("confirmed"):
                    return f"{VIP_SLOT_EMOJI} `{slot_num}` ~~**{v['name']}** `{v['tag']}` — {mgr}~~"
                else:
                    return f"{WAIT_DISPLAY} {VIP_SLOT_EMOJI} `{slot_num}` **{v['name']}** `{v['tag']}` — {mgr}"
            return f"{VIP_SLOT_EMOJI} `{slot_num}` *VIP — დაჯავშნულია*"

        idx = slot_num - 2
        if idx < len(teams):
            t   = teams[idx]
            m   = guild.get_member(t["manager_id"])
            mgr = m.display_name if m else f"#{t['manager_id']}"
            if t.get("confirmed"):
                return f"`{slot_num:02d}` ~~**{t['name']}** `{t['tag']}` — {mgr}~~"
            else:
                return f"{WAIT_DISPLAY} `{slot_num:02d}` **{t['name']}** `{t['tag']}` — {mgr}"
        return f"◻️ `{slot_num:02d}` *— თავისუფალია —*"

    # სლოტები ორ სვეტად — 01–13 და 14–25
    left_lines  = [compact_line(s) for s in range(1, 14)]
    right_lines = [compact_line(s) for s in range(14, 26)]

    embed.add_field(name="◈ სლოტები 01–13", value="\n".join(left_lines), inline=True)
    embed.add_field(name="◈ სლოტები 14–25", value="\n".join(right_lines), inline=True)
    embed.set_footer(text="confirm ✅ • cancel ❌ • %register ClanName TAG [@manager]")
    return embed


def build_wait_embed(scrim_key: str, data: dict, guild: discord.Guild) -> discord.Embed:
    cfg = SCRIMS[scrim_key]
    wl  = data.get("waitlist", [])

    embed = discord.Embed(color=0x2B2D31, timestamp=datetime.utcnow())
    embed.set_author(name=f"📋  {cfg['name']}  —  WAITLIST")

    if wl:
        # კომპაქტური ვეითლისტი — ერთ ხაზზე
        lines = []
        for i, t in enumerate(wl):
            icon = CONFIRM_DISPLAY if t.get("confirmed") else WAIT_DISPLAY
            m    = guild.get_member(t["manager_id"])
            mgr  = m.display_name if m else f"#{t['manager_id']}"
            lines.append(f"{icon} `#{i+1:02d}` **{t['name']}** `{t['tag']}` — {mgr}")
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"სულ {len(wl)} ტიმი მოლოდინში  ·  სლოტი გათავისუფლდება → პირველი ჩადის")
    else:
        embed.description = (
            "```\n"
            "  ვეითლისტი ცარიელია\n"
            "```\n"
            "*22 სლოტი შეივსება → ვეითლისტი გაიხსნება*"
        )
        embed.set_footer(text="სლოტი გათავისუფლდება → ვეითლისტიდან პირველი ჩადის ავტომატურად")
    return embed


async def refresh_displays(scrim_key: str, guild: discord.Guild):
    cfg  = SCRIMS[scrim_key]
    data = get_data(scrim_key)

    # ── Slot channel ──
    slot_ch = bot.get_channel(cfg["slot_channel"])
    if slot_ch:
        embed = build_slot_embed(scrim_key, data, guild)

        existing_id = last_msg_ids.get(scrim_key)

        if not existing_id:
            async for m in slot_ch.history(limit=20):
                if m.author == bot.user and m.embeds:
                    existing_id = m.id
                    last_msg_ids[scrim_key] = m.id
                    break

        edited = False
        if existing_id:
            try:
                existing_msg = await slot_ch.fetch_message(existing_id)
                await existing_msg.edit(embed=embed)
                edited = True
            except (discord.NotFound, discord.HTTPException):
                last_msg_ids.pop(scrim_key, None)

        if not edited:
            await slot_ch.purge(limit=20, check=lambda m: m.author == bot.user)
            msg = await slot_ch.send(embed=embed)
            last_msg_ids[scrim_key] = msg.id
            await msg.add_reaction(REACT_CONFIRM)
            await msg.add_reaction(REACT_CANCEL)

    # ── Waitlist channel ──
    wait_ch = bot.get_channel(cfg["wait_channel"])
    if wait_ch:
        wait_embed = build_wait_embed(scrim_key, data, guild)
        wait_msg_key = f"{scrim_key}_wait"

        existing_wait_id = last_msg_ids.get(wait_msg_key)

        if not existing_wait_id:
            async for m in wait_ch.history(limit=20):
                if m.author == bot.user and m.embeds:
                    existing_wait_id = m.id
                    last_msg_ids[wait_msg_key] = m.id
                    break

        edited = False
        if existing_wait_id:
            try:
                existing_wait = await wait_ch.fetch_message(existing_wait_id)
                await existing_wait.edit(embed=wait_embed)
                edited = True
            except (discord.NotFound, discord.HTTPException):
                last_msg_ids.pop(wait_msg_key, None)

        if not edited:
            await wait_ch.purge(limit=20, check=lambda m: m.author == bot.user)
            wait_msg = await wait_ch.send(embed=wait_embed)
            last_msg_ids[wait_msg_key] = wait_msg.id


# ─── EVENTS ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    import asyncio
    logger.info(f"✅  {bot.user} is online.")
    await asyncio.sleep(3)
    for scrim_key, cfg in SCRIMS.items():
        slot_ch = bot.get_channel(cfg["slot_channel"])
        if slot_ch:
            bot_msgs = []
            async for msg in slot_ch.history(limit=20):
                if msg.author == bot.user and msg.embeds:
                    bot_msgs.append(msg)
            if bot_msgs:
                last_msg_ids[scrim_key] = bot_msgs[0].id
                for old in bot_msgs[1:]:
                    try:
                        await old.delete()
                    except Exception:
                        pass
                logger.info(f"Slot msg for {scrim_key}: {bot_msgs[0].id}")

        wait_ch = bot.get_channel(cfg["wait_channel"])
        if wait_ch:
            bot_msgs = []
            async for msg in wait_ch.history(limit=20):
                if msg.author == bot.user and msg.embeds:
                    bot_msgs.append(msg)
            if bot_msgs:
                last_msg_ids[f"{scrim_key}_wait"] = bot_msgs[0].id
                for old in bot_msgs[1:]:
                    try:
                        await old.delete()
                    except Exception:
                        pass

        reg_ch = bot.get_channel(cfg["reg_channel"])
        if reg_ch:
            async for msg in reg_ch.history(limit=20):
                if msg.author == bot.user and not msg.embeds:
                    last_msg_ids[f"{scrim_key}_counter_msg"] = msg.id
                    break


@bot.event
async def on_message(message: discord.Message):
    if (message.channel.id == WATCH_CHANNEL
            and not message.author.bot
            and WATCH_USER in [m.id for m in message.mentions]):
        try:
            await message.add_reaction(YES_EMOJI)
            await message.channel.send(f"{YES_EMOJI} ხო ძმა რა ხდება")
        except Exception as e:
            logger.warning(f"Reaction error: {e}")

    await bot.process_commands(message)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    for scrim_key, cfg in SCRIMS.items():
        if payload.message_id != last_msg_ids.get(scrim_key):
            continue
        if payload.channel_id != cfg["slot_channel"]:
            continue

        guild   = bot.get_guild(payload.guild_id)
        reactor = guild.get_member(payload.user_id)
        channel = bot.get_channel(payload.channel_id)
        msg     = await channel.fetch_message(payload.message_id)

        try:
            await msg.remove_reaction(payload.emoji, reactor)
        except Exception:
            pass

        if not reactor:
            break

        is_admin = reactor.guild_permissions.administrator
        data     = get_data(scrim_key)

        emoji_id = str(payload.emoji.id) if payload.emoji.id else str(payload.emoji)

        CONFIRM_ID = "1503686337415479337"
        CANCEL_ID  = "1503686325226831943"

        changed = False

        if emoji_id == CONFIRM_ID:
            # ჯერ საკუთარი სლოტი — main list
            for t in data["teams"]:
                if t["manager_id"] == reactor.id and not t.get("confirmed"):
                    t["confirmed"] = True
                    changed = True
                    break
            # თუ main-ში არ იყო — VIP სლოტი
            if not changed:
                for s in ["24", "25"]:
                    v = data["vips"].get(s)
                    if v and v["manager_id"] == reactor.id and not v.get("confirmed"):
                        data["vips"][s]["confirmed"] = True
                        changed = True
                        break
            # ადმინი reaction-ით confirm-ს ვერ გააკეთებს სხვისთვის —
            # ამისთვის %edit ან %remove + %register არსებობს

        elif emoji_id == CANCEL_ID:
            # ❗ მხოლოდ საკუთარი სლოტის გაუქმება — ადმინიც ვერ შლის სხვისას reaction-ით
            # სხვისი სლოტის წასაშლელად გამოიყენება %remove კომანდა

            # main list-ში ვეძებთ reactor-ის სლოტს
            target_idx = None
            for i, t in enumerate(data["teams"]):
                if t["manager_id"] == reactor.id:
                    target_idx = i
                    break

            if target_idx is not None:
                data["teams"].pop(target_idx)
                await apply_roles(reactor, scrim_key, "none")
                changed = True
                # ვეითლისტიდან პირველი ავტომატურად ჩადის
                if data["waitlist"]:
                    promoted = data["waitlist"].pop(0)
                    promoted["confirmed"] = False
                    data["teams"].insert(target_idx, promoted)
                    p_member = guild.get_member(promoted["manager_id"])
                    if p_member:
                        await apply_roles(p_member, scrim_key, "main")
            else:
                # VIP სლოტში ვეძებთ
                for s in ["24", "25"]:
                    v = data["vips"].get(s)
                    if v and v["manager_id"] == reactor.id:
                        del data["vips"][s]
                        await apply_roles(reactor, scrim_key, "none")
                        changed = True
                        break
                # თუ reactor-ს საერთოდ არ ჰქონდა სლოტი — არაფერი ხდება

        if changed:
            save_data(scrim_key, data)
            await refresh_displays(scrim_key, guild)
        break


# ─── COMMANDS ────────────────────────────────────────────────────────────────

@bot.command(name="register", aliases=["reg"])
async def register(ctx: commands.Context, clan_name: str, clan_tag: str, manager: discord.Member = None):
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id == v["reg_channel"]), None)
    if not key:
        return

    author_role_ids = {r.id for r in ctx.author.roles}
    has_permission  = (
        ctx.author.guild_permissions.administrator
        or bool(author_role_ids & ALLOWED_REG_ROLES)
    )
    if not has_permission:
        reply = await ctx.send("❌  რეგისტრაციის უფლება არ გაქვს!")
        await ctx.message.delete(delay=5)
        await reply.delete(delay=8)
        return

    target = manager or ctx.author

    if target.id in BANNED_USERS:
        reply = await ctx.send("🚫 ეს მომხმარებელი დაბანილია.")
        await ctx.message.delete(delay=5)
        await reply.delete(delay=8)
        return

    data = get_data(key)

    already_in = any(t["manager_id"] == target.id for t in data["teams"] + data["waitlist"])
    if already_in:
        reply = await ctx.send(f"⚠️  **{target.display_name}** უკვე რეგისტრირებულია!")
        await ctx.message.delete(delay=5)
        await reply.delete(delay=8)
        return

    new_team = {
        "name":       clan_name,
        "tag":        clan_tag.upper(),
        "manager_id": target.id,
        "confirmed":  False,
    }

    if len(data["teams"]) < 22:
        data["teams"].append(new_team)
        await apply_roles(target, key, "main")
        slot_num  = len(data["teams"]) + 1
        status_msg = f"✅  **{clan_name}** დარეგისტრირდა! სლოტი → `{slot_num:02d}`"
        react_with = REACT_CONFIRM
    else:
        data["waitlist"].append(new_team)
        await apply_roles(target, key, "wait")
        wait_pos   = len(data["waitlist"])
        status_msg = f"⏳  **{clan_name}** ვეითლისტშია! პოზიცია → `{wait_pos}`"
        react_with = REACT_WAIT

    save_data(key, data)
    await refresh_displays(key, ctx.guild)

    try:
        await ctx.message.add_reaction(react_with)
    except Exception:
        pass

    fresh_data = get_data(key)
    remaining  = 22 - len(fresh_data["teams"])
    if remaining > 0:
        slots_text = f"📊  **{remaining}** სლოტი დარჩენილია!"
    else:
        slots_text = f"🔴  სლოტები გაივსო! ვეითლისტი: **{len(fresh_data['waitlist'])}** ტიმი"

    slot_counter_key = f"{key}_counter_msg"
    old_counter_id   = last_msg_ids.get(slot_counter_key)
    if old_counter_id:
        try:
            old_msg = await ctx.channel.fetch_message(old_counter_id)
            await old_msg.delete()
        except Exception:
            pass

    counter_msg = await ctx.send(slots_text)
    last_msg_ids[slot_counter_key] = counter_msg.id


@bot.command()
@commands.has_permissions(administrator=True)
async def setvip(ctx: commands.Context, slot: int, member: discord.Member, clan_tag: str, *, clan_name: str):
    key = next(
        (k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]),
        None,
    )
    if not key or slot not in [24, 25]:
        return

    data = get_data(key)
    data["vips"][str(slot)] = {
        "name":       clan_name,
        "tag":        clan_tag.upper(),
        "manager_id": member.id,
        "confirmed":  False,
    }
    save_data(key, data)
    await apply_roles(member, key, "main")
    await refresh_displays(key, ctx.guild)

    reply = await ctx.send(f"✅  VIP slot **{slot}** → **{clan_name}** `[{clan_tag.upper()}]`")
    await ctx.message.delete(delay=5)
    await reply.delete(delay=8)


@bot.command()
@commands.has_permissions(administrator=True)
async def edit(ctx: commands.Context, slot_num: int, member: discord.Member, clan_tag: str, *, clan_name: str):
    key = next(
        (k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]),
        None,
    )
    if not key:
        return

    data = get_data(key)

    if slot_num in [24, 25]:
        data["vips"][str(slot_num)] = {
            "name":       clan_name,
            "tag":        clan_tag.upper(),
            "manager_id": member.id,
            "confirmed":  False,
        }
        await apply_roles(member, key, "main")
    elif 2 <= slot_num <= 23:
        idx = slot_num - 2
        new_team = {
            "name":       clan_name,
            "tag":        clan_tag.upper(),
            "manager_id": member.id,
            "confirmed":  False,
        }
        if idx < len(data["teams"]):
            old_m = ctx.guild.get_member(data["teams"][idx]["manager_id"])
            if old_m and old_m.id != member.id:
                await apply_roles(old_m, key, "none")
            data["teams"][idx] = new_team
        else:
            data["teams"].append(new_team)
        await apply_roles(member, key, "main")
    else:
        reply = await ctx.send("❌  Invalid slot number.")
        await reply.delete(delay=8)
        return

    save_data(key, data)
    await refresh_displays(key, ctx.guild)
    reply = await ctx.send(f"✅  Slot `{slot_num:02d}` updated → **{clan_name}**")
    await ctx.message.delete(delay=5)
    await reply.delete(delay=8)


@bot.command()
@commands.has_permissions(administrator=True)
async def remove(ctx: commands.Context, *, target: str):
    key = next(
        (k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]),
        None,
    )
    if not key:
        return

    data    = get_data(key)
    removed = False
    removed_idx = None

    if ctx.message.mentions:
        target_id = ctx.message.mentions[0].id
        for i, t in enumerate(data["teams"]):
            if t["manager_id"] == target_id:
                old_m = ctx.guild.get_member(target_id)
                if old_m: await apply_roles(old_m, key, "none")
                data["teams"].pop(i)
                removed = True
                removed_idx = i
                break
        if not removed:
            for s in ["24", "25"]:
                if data["vips"].get(s) and data["vips"][s]["manager_id"] == target_id:
                    old_m = ctx.guild.get_member(target_id)
                    if old_m: await apply_roles(old_m, key, "none")
                    del data["vips"][s]
                    removed = True
                    break
    elif target.isdigit():
        slot_num = int(target)
        if slot_num in [24, 25]:
            if data["vips"].get(str(slot_num)):
                old_m = ctx.guild.get_member(data["vips"][str(slot_num)]["manager_id"])
                if old_m: await apply_roles(old_m, key, "none")
                del data["vips"][str(slot_num)]
                removed = True
        elif 2 <= slot_num <= 23:
            idx = slot_num - 2
            if idx < len(data["teams"]):
                old_m = ctx.guild.get_member(data["teams"][idx]["manager_id"])
                if old_m: await apply_roles(old_m, key, "none")
                data["teams"].pop(idx)
                removed = True
                removed_idx = idx

    if removed and removed_idx is not None and data["waitlist"]:
        promoted = data["waitlist"].pop(0)
        promoted["confirmed"] = False
        data["teams"].insert(removed_idx, promoted)
        p_member = ctx.guild.get_member(promoted["manager_id"])
        if p_member:
            await apply_roles(p_member, key, "main")
        logger.info(f"Promoted {promoted['name']} to slot {removed_idx + 2:02d}")

    if removed:
        save_data(key, data)
        await refresh_displays(key, ctx.guild)
        reply = await ctx.send("✅  ტიმი წაიშალა!")
    else:
        reply = await ctx.send("❌  სლოტი ვერ მოიძებნა.")

    await ctx.message.delete(delay=5)
    await reply.delete(delay=8)


@bot.command()
@commands.has_permissions(administrator=True)
async def reset(ctx: commands.Context):
    key = next(
        (k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]),
        None,
    )
    if not key:
        return
    save_data(key, {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"})

    slot_counter_key = f"{key}_counter_msg"
    old_counter_id   = last_msg_ids.pop(slot_counter_key, None)
    cfg = SCRIMS[key]
    if old_counter_id:
        try:
            reg_ch = bot.get_channel(cfg["reg_channel"])
            if reg_ch:
                old_msg = await reg_ch.fetch_message(old_counter_id)
                await old_msg.delete()
        except Exception:
            pass

    await refresh_displays(key, ctx.guild)
    reply = await ctx.send("🔄  სკრიმი გასუფთავდა!")
    await ctx.message.delete(delay=3)
    await reply.delete(delay=6)


@bot.command()
@commands.has_permissions(administrator=True)
async def refresh(ctx: commands.Context):
    key = next(
        (k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"], v["wait_channel"]]),
        None,
    )
    if not key:
        return
    await refresh_displays(key, ctx.guild)
    reply = await ctx.send("🔁  დისპლეი განახლდა!")
    await reply.delete(delay=5)


bot.run(os.getenv('DISCORD_TOKEN'))
