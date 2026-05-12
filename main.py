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

# აქ ჩაწერე იმ ხალხის ID ვისაც ბანი აქვთ
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
# Application Emojis — როგორც display-ში, ასევე reactions-ში
VIP_EMOJI       = "<:VIP_2:1503677407062917130>"
CONFIRM_DISPLAY = "<:Red_Verified:1503686337415479337>"
CANCEL_DISPLAY  = "<:verify_red_cross:1503686325226831943>"
WAIT_DISPLAY    = "<:WAITLISTSF:1503687118302482562>"

REACT_CONFIRM = "<:Red_Verified:1503686337415479337>"
REACT_CANCEL  = "<:verify_red_cross:1503686325226831943>"
REACT_WAIT    = "<:WAITLISTSF:1503687118302482562>"

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

# message_id of the last slot embed per scrim (for reaction tracking)
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

def _member_name(guild: discord.Guild, user_id: int) -> str:
    m = guild.get_member(user_id)
    return m.display_name if m else f"#{user_id}"

def build_slot_embed(scrim_key: str, data: dict, guild: discord.Guild) -> discord.Embed:
    cfg   = SCRIMS[scrim_key]
    teams = data.get("teams", [])
    vips  = data.get("vips", {})

    total_filled    = len(teams) + len(vips)
    confirmed_count = sum(1 for t in teams if t.get("confirmed")) \
                    + sum(1 for v in vips.values() if v.get("confirmed"))

    # Progress bar
    filled_regular = len(teams)
    bar_on  = round((filled_regular / 22) * 16)
    bar_off = 16 - bar_on
    bar     = "█" * bar_on + "░" * bar_off
    pct     = round((filled_regular / 22) * 100)

    status_icon = "🟢" if data.get("status", "OPEN") == "OPEN" else "🔴"

    embed = discord.Embed(
        title=f"🏆  {cfg['name']}",
        color=cfg["color"],
        timestamp=datetime.utcnow(),
    )
    embed.description = (
        f"{status_icon}  `{data.get('status','OPEN')}`  ·  "
        f"**{total_filled + 1}/25** slots  ·  "
        f"✅ **{confirmed_count}** confirmed\n"
        f"```{bar}  {pct}%```"
        f"──────────────────────────────"
    )

    lines = []

    # Slot 01 — Admin
    lines.append(f"🛡️  `01`  **ELITE HOST** *(admin)*")
    lines.append("⠀")   # thin spacer

    # Slots 02 – 23
    for slot_num in range(2, 24):
        idx = slot_num - 2
        if idx < len(teams):
            t    = teams[idx]
            icon = CONFIRM_DISPLAY if t.get("confirmed") else WAIT_DISPLAY
            mgr  = _member_name(guild, t["manager_id"])
            lines.append(
                f"{icon}  `{slot_num:02d}`  **{t['name']}**  `[{t['tag']}]`\n"
                f"⠀⠀⠀⠀└ 👤 {mgr}"
            )
        else:
            lines.append(f"▫️  `{slot_num:02d}`  *— open —*")

        # Visual divider every 4 slots
        if slot_num in (5, 9, 13, 17, 21):
            lines.append("⠀")

    lines.append("⠀")

    # VIP Slots 24 & 25
    for slot_num in [24, 25]:
        v = vips.get(str(slot_num))
        if v:
            icon = CONFIRM_DISPLAY if v.get("confirmed") else WAIT_DISPLAY
            mgr  = _member_name(guild, v["manager_id"])
            lines.append(
                f"{icon}  {VIP_EMOJI}  `{slot_num}`  **{v['name']}**  `[{v['tag']}]`\n"
                f"⠀⠀⠀⠀└ 👤 {mgr}"
            )
        else:
            lines.append(f"{VIP_EMOJI}  `{slot_num}`  *VIP reserved*")

    embed.add_field(name="", value="\n".join(lines), inline=False)
    embed.set_footer(text="✅ confirm your slot  ·  ❌ leave  ·  %register ClanName TAG [@manager]")
    return embed


def build_wait_embed(scrim_key: str, data: dict, guild: discord.Guild) -> discord.Embed:
    cfg = SCRIMS[scrim_key]
    wl  = data.get("waitlist", [])

    embed = discord.Embed(
        title=f"📋  {cfg['name']}  —  WAITLIST",
        color=0x5865F2,
        timestamp=datetime.utcnow(),
    )
    if wl:
        lines = []
        for i, t in enumerate(wl):
            icon = CONFIRM_DISPLAY if t.get("confirmed") else WAIT_DISPLAY
            mgr  = _member_name(guild, t["manager_id"])
            lines.append(
                f"{icon}  `{i+1:02d}`  **{t['name']}**  `[{t['tag']}]`\n"
                f"⠀⠀⠀⠀└ 👤 {mgr}"
            )
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"{len(wl)} team(s) waiting  ·  slot freed → first team auto-promoted")
    else:
        embed.description = "```\nwaitlist is empty\n```"
        embed.set_footer(text="22 regular slots fill up → waitlist opens")
    return embed


async def refresh_displays(scrim_key: str, guild: discord.Guild):
    cfg  = SCRIMS[scrim_key]
    data = get_data(scrim_key)

    # Slot channel
    slot_ch = bot.get_channel(cfg["slot_channel"])
    if slot_ch:
        await slot_ch.purge(limit=5, check=lambda m: m.author == bot.user)
        msg = await slot_ch.send(embed=build_slot_embed(scrim_key, data, guild))
        last_msg_ids[scrim_key] = msg.id
        await msg.add_reaction(REACT_CONFIRM)
        await msg.add_reaction(REACT_CANCEL)

    # Waitlist channel
    wait_ch = bot.get_channel(cfg["wait_channel"])
    if wait_ch:
        await wait_ch.purge(limit=5, check=lambda m: m.author == bot.user)
        await wait_ch.send(embed=build_wait_embed(scrim_key, data, guild))


# ─── EVENTS ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    logger.info(f"✅  {bot.user} is online.")


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

        # Always remove the reaction so it's reusable
        try:
            await msg.remove_reaction(payload.emoji, reactor)
        except Exception:
            pass

        if not reactor:
            break

        is_admin = reactor.guild_permissions.administrator
        data     = get_data(scrim_key)
        emoji    = str(payload.emoji)
        changed  = False

        # ── ✅  CONFIRM ──────────────────────────────────────────────────────
        if emoji == REACT_CONFIRM:
            # Check if reactor is a regular team manager
            for t in data["teams"]:
                if t["manager_id"] == reactor.id and not t.get("confirmed"):
                    t["confirmed"] = True
                    changed = True
                    break
            # Check VIP
            if not changed:
                for s in ["24", "25"]:
                    v = data["vips"].get(s)
                    if v and v["manager_id"] == reactor.id and not v.get("confirmed"):
                        data["vips"][s]["confirmed"] = True
                        changed = True
                        break
            # Admin fallback: confirm first unconfirmed team
            if not changed and is_admin:
                for t in data["teams"]:
                    if not t.get("confirmed"):
                        t["confirmed"] = True
                        changed = True
                        break

        # ── ❌  LEAVE / UNCONFIRM ────────────────────────────────────────────
        elif emoji == REACT_CANCEL:
            # Find reactor's confirmed team and remove them
            target_idx = None
            for i, t in enumerate(data["teams"]):
                if t["manager_id"] == reactor.id and t.get("confirmed"):
                    target_idx = i
                    break

            if target_idx is not None:
                removed = data["teams"].pop(target_idx)
                await apply_roles(reactor, scrim_key, "none")
                changed = True
                # Auto-promote first waitlist entry (unconfirmed — must confirm themselves)
                if data["waitlist"]:
                    promoted = data["waitlist"].pop(0)
                    promoted["confirmed"] = False   # must confirm via ✅
                    data["teams"].insert(target_idx, promoted)
                    p_member = guild.get_member(promoted["manager_id"])
                    if p_member:
                        await apply_roles(p_member, scrim_key, "main")
            else:
                # Check VIP slots
                for s in ["24", "25"]:
                    v = data["vips"].get(s)
                    if v and v["manager_id"] == reactor.id and v.get("confirmed"):
                        del data["vips"][s]
                        await apply_roles(reactor, scrim_key, "none")
                        changed = True
                        break

            # Admin: if still no match, remove last confirmed team
            if not changed and is_admin:
                for i in range(len(data["teams"]) - 1, -1, -1):
                    if data["teams"][i].get("confirmed"):
                        removed = data["teams"].pop(i)
                        old_m = guild.get_member(removed["manager_id"])
                        if old_m:
                            await apply_roles(old_m, scrim_key, "none")
                        changed = True
                        if data["waitlist"]:
                            promoted = data["waitlist"].pop(0)
                            promoted["confirmed"] = False
                            data["teams"].insert(i, promoted)
                            p_member = guild.get_member(promoted["manager_id"])
                            if p_member:
                                await apply_roles(p_member, scrim_key, "main")
                        break

        if changed:
            save_data(scrim_key, data)
            await refresh_displays(scrim_key, guild)
        break


# ─── COMMANDS ────────────────────────────────────────────────────────────────

@bot.command(name="register", aliases=["reg"])
async def register(ctx: commands.Context, clan_name: str, clan_tag: str, manager: discord.Member = None):
    """
    %register <ClanName> <TAG> [@manager]
    Registers a team. If no manager is mentioned, the command author is used.
    """
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id == v["reg_channel"]), None)
    if not key:
        return

    target = manager or ctx.author

    if target.id in BANNED_USERS:
        reply = await ctx.send("🚫 ეს მომხმარებელი დაბანილია.")
        await ctx.message.delete(delay=5)
        await reply.delete(delay=8)
        return

    data = get_data(key)

    # Duplicate check
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
        "confirmed":  False,   # must confirm via ✅ reaction
    }

    if len(data["teams"]) < 22:
        data["teams"].append(new_team)
        await apply_roles(target, key, "main")
        slot_num  = len(data["teams"]) + 1   # +1 because slot 01 is admin
        status_msg = f"✅  **{clan_name}** დარეგისტრირდა! სლოტი → `{slot_num:02d}`"
        react_with = REACT_CONFIRM   # registered in main list
    else:
        data["waitlist"].append(new_team)
        await apply_roles(target, key, "wait")
        wait_pos   = len(data["waitlist"])
        status_msg = f"⏳  **{clan_name}** ვეითლისტშია! პოზიცია → `{wait_pos}`"
        react_with = REACT_WAIT   # landed on waitlist

    save_data(key, data)
    await refresh_displays(key, ctx.guild)

    # React on the registration message to indicate slot vs waitlist
    try:
        await ctx.message.add_reaction(react_with)
    except Exception:
        pass

    reply = await ctx.send(status_msg)
    await ctx.message.delete(delay=6)
    await reply.delete(delay=9)


@bot.command()
@commands.has_permissions(administrator=True)
async def setvip(ctx: commands.Context, slot: int, member: discord.Member, clan_tag: str, *, clan_name: str):
    """
    %setvip <24|25> @manager <TAG> <ClanName>
    """
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
    """
    %edit <slot> @manager <TAG> <ClanName>
    """
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
    """
    %remove <slot_number>   OR   %remove @manager
    """
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

    # Auto-promote from waitlist (unconfirmed)
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
    """Reset all data for the scrim associated with this channel."""
    key = next(
        (k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]),
        None,
    )
    if not key:
        return
    save_data(key, {"teams": [], "waitlist": [], "vips": {}, "status": "OPEN"})
    await refresh_displays(key, ctx.guild)
    reply = await ctx.send("🔄  სკრიმი გასუფთავდა!")
    await ctx.message.delete(delay=3)
    await reply.delete(delay=6)


@bot.command()
@commands.has_permissions(administrator=True)
async def refresh(ctx: commands.Context):
    """Force-refresh the display channels."""
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
