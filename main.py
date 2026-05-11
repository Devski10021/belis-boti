import discord
from discord.ext import commands
import os
import logging
import certifi
from pymongo import MongoClient
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

MONGO_URL = os.getenv('MONGO_URL')
cluster = MongoClient(MONGO_URL, tlsCAFile=certifi.where())
db = cluster["belis_scrims"]
collection = db["storage"]

VIP_EMOJI = "<:diamond:1390948554956341301>"

SCRIMS = {
    "scrim_22": {
        "name": "22:00 Scrim",
        "reg_channel": 1503324709557895288,
        "slot_channel": 1503325306285588510,
        "wait_channel": 1503325883182747742,
        "role_id": 1503327762109304863,
        "wait_role_id": 1503328170311548949,
    },
    "scrim_00": {
        "name": "00:30 Scrim",
        "reg_channel": 1503327037832691832,
        "slot_channel": 1503327123337904189,
        "wait_channel": 1503327364749459506,
        "role_id": 1503327805897707591,
        "wait_role_id": 1503328171884412978,
    }
}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="%", intents=intents)
last_msg_ids = {}


# ─── DATABASE ────────────────────────────────────────────────────────────────

def get_scrim_data(scrim_key):
    res = collection.find_one({"_id": scrim_key})
    if res:
        return {
            "teams": res.get("teams", []),
            "waitlist": res.get("waitlist", []),
            "vips": res.get("vips", {})
        }
    return {"teams": [], "waitlist": [], "vips": {}}


def save_scrim_data(scrim_key, data):
    collection.update_one({"_id": scrim_key}, {"$set": data}, upsert=True)


# ─── ROLES ────────────────────────────────────────────────────────────────────

async def manage_roles(member, scrim_key, status):
    if not member or not isinstance(member, discord.Member):
        return
    cfg = SCRIMS[scrim_key]
    r_main = member.guild.get_role(cfg["role_id"])
    r_wait = member.guild.get_role(cfg["wait_role_id"])
    try:
        if status == 'main':
            if r_wait and r_wait in member.roles:
                await member.remove_roles(r_wait)
            if r_main:
                await member.add_roles(r_main)
        elif status == 'wait':
            if r_main and r_main in member.roles:
                await member.remove_roles(r_main)
            if r_wait:
                await member.add_roles(r_wait)
        elif status == 'none':
            if r_main and r_main in member.roles:
                await member.remove_roles(r_main)
            if r_wait and r_wait in member.roles:
                await member.remove_roles(r_wait)
    except Exception as e:
        logger.warning(f"Role manage error: {e}")


# ─── DISPLAY ──────────────────────────────────────────────────────────────────

def build_team_list_embed(scrim_key, data, guild=None):
    cfg = SCRIMS[scrim_key]
    teams = data.get("teams", [])
    filled = len(teams)
    vips = data.get("vips", {})
    vip_filled = sum(1 for s in ["24","25"] if vips.get(s))
    total_filled = filled + vip_filled

    embed = discord.Embed(
        title=f"🏆  {cfg['name']}  —  TEAM LIST",
        color=0xF1C40F
    )
    embed.description = f"> 📊  **{total_filled + 1}/25** სლოტი დაკავებულია"

    # ── Left column: slots 01–13 ──
    left = []
    left.append(f"🔒 `01` ⚜️ **ADMIN**")
    for i in range(2, 14):
        idx = i - 2
        _slot_line(left, i, idx, teams, guild)

    # ── Right column: slots 14–25 ──
    right = []
    for i in range(14, 24):
        idx = i - 2
        _slot_line(right, i, idx, teams, guild)

    # VIP slots
    for slot_num in [24, 25]:
        v = vips.get(str(slot_num))
        if v:
            icon = "✅" if v.get("confirmed") else "⏳"
            manager_str = ""
            if guild and v.get("manager_id"):
                member = guild.get_member(v["manager_id"])
                if member:
                    manager_str = f" • {member.display_name}"
            right.append(f"{icon} {VIP_EMOJI} **{v['name']}** `{v['tag']}`{manager_str}")
        else:
            right.append(f"🔷 {VIP_EMOJI} *VIP available*")

    embed.add_field(name="​", value="\n".join(left), inline=True)
    embed.add_field(name="​", value="\n".join(right), inline=True)
    embed.set_footer(text=f"react ✅ confirm  •  ❌ unconfirm  •  %register clan tag @manager")
    return embed


def _slot_line(lines, slot_num, idx, teams, guild=None):
    """Append one slot line to the given list."""
    n = f"`{slot_num:02d}`"
    if idx < len(teams):
        tm = teams[idx]
        icon = "✅" if tm.get("confirmed") else "⏳"
        manager_str = ""
        if guild and tm.get("manager_id"):
            member = guild.get_member(tm["manager_id"])
            if member:
                manager_str = f" • {member.display_name}"
        lines.append(f"{icon} {n} **{tm['name']}** `{tm['tag']}`{manager_str}")
    else:
        lines.append(f"◻️ {n} *— open —*")


def build_waitlist_embed(scrim_key, data):
    cfg = SCRIMS[scrim_key]
    embed = discord.Embed(
        title=f"📋  {cfg['name']}  —  WAITLIST",
        color=0x5865F2
    )
    wl = data.get("waitlist", [])
    if wl:
        lines = []
        for i, x in enumerate(wl):
            lines.append(f"⏳ `{i+1:02d}` **{x['name']}** `{x['tag']}`")
        embed.description = "\n".join(lines)
        embed.set_footer(text="სლოტი გათავისუფლდება → პირველი ტიმი ავტომატურად ჩადის")
    else:
        embed.description = "```\nვეითლისტი ცარიელია\n```"
        embed.set_footer(text="სლოტები გაივსება → ვეითლისტი გაიხსნება")
    return embed


async def update_all_displays(scrim_key, guild=None):
    cfg = SCRIMS[scrim_key]
    data = get_scrim_data(scrim_key)

    # ── Team List channel ──
    slot_ch = bot.get_channel(cfg["slot_channel"])
    if slot_ch:
        await slot_ch.purge(limit=10, check=lambda m: m.author == bot.user)
        embed = build_team_list_embed(scrim_key, data, guild=guild or slot_ch.guild)
        msg = await slot_ch.send(embed=embed)
        last_msg_ids[scrim_key] = msg.id
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

    # ── Waitlist channel ──
    wait_ch = bot.get_channel(cfg["wait_channel"])
    if wait_ch:
        await wait_ch.purge(limit=10, check=lambda m: m.author == bot.user)
        embed = build_waitlist_embed(scrim_key, data)
        await wait_ch.send(embed=embed)


# ─── COMMANDS ─────────────────────────────────────────────────────────────────

@bot.command()
async def register(ctx, *, text=None):
    """
    %register <clan name> <clan tag> [@manager]
    """
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id == v["reg_channel"]), None)
    if not key or not text:
        return

    manager = ctx.message.mentions[0] if ctx.message.mentions else ctx.author
    parts = [x for x in text.split() if not x.startswith('<@')]

    if len(parts) < 2:
        await ctx.send("❌  გამოყენება: `%register <clan name> <clan tag> [@manager]`", delete_after=10)
        return

    clan_tag = parts[-1]
    clan_name = " ".join(parts[:-1])
    data = get_scrim_data(key)

    new_team = {
        'name': clan_name,
        'tag': clan_tag,
        'manager_id': manager.id,
        'confirmed': False
    }

    if len(data["teams"]) < 22:
        data["teams"].append(new_team)
        await manage_roles(manager, key, 'main')
        slot_num = len(data["teams"]) + 1  # +1 because slot 01 is admin
        status_msg = f"✅  **{clan_name}** დარეგისტრირდა! სლოტი → **`{slot_num:02d}`**"
    else:
        data["waitlist"].append(new_team)
        await manage_roles(manager, key, 'wait')
        wait_pos = len(data["waitlist"])
        status_msg = f"📋  **{clan_name}** ვეითლისტშია! პოზიცია → **`{wait_pos}`**"

    save_scrim_data(key, data)
    await update_all_displays(key, guild=ctx.guild)
    reply = await ctx.send(status_msg)
    await ctx.message.delete(delay=5)
    await reply.delete(delay=8)


@bot.command()
@commands.has_permissions(administrator=True)
async def setvip(ctx, slot: int, member: discord.Member, *, text):
    """
    %setvip <24|25> @manager <clan name> <clan tag>
    """
    key = next(
        (k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]),
        None
    )
    if not key or slot not in [24, 25]:
        return

    parts = text.split()
    if len(parts) < 2:
        await ctx.send("❌  გამოყენება: `%setvip <24|25> @manager <clan name> <clan tag>`", delete_after=10)
        return

    clan_tag = parts[-1]
    clan_name = " ".join(parts[:-1])
    data = get_scrim_data(key)
    data["vips"][str(slot)] = {'name': clan_name, 'tag': clan_tag, 'manager_id': member.id}
    save_scrim_data(key, data)
    await manage_roles(member, key, 'main')
    await update_all_displays(key, guild=ctx.guild)
    reply = await ctx.send(f"✅  VIP სლოტი **{slot}** → **{clan_name}** [`{clan_tag}`]")
    await reply.delete(delay=8)


@bot.command()
@commands.has_permissions(administrator=True)
async def edit(ctx, *, text=None):
    """
    Edit any slot by slot number or by tagging the manager.
    """
    key = next(
        (k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]),
        None
    )
    if not key or not text:
        return

    data = get_scrim_data(key)
    parts = [x for x in text.split() if not x.startswith('<@')]
    mentions = ctx.message.mentions
    updated = False

    # ── Mode 1: slot number provided ──
    if parts and parts[0].isdigit():
        slot_num = int(parts[0])
        rest = parts[1:]
        if len(rest) < 2:
            await ctx.send("❌  გამოყენება: `%edit <slot> <clan name> <clan tag> [@manager]`", delete_after=10)
            return

        clan_tag = rest[-1]
        clan_name = " ".join(rest[:-1])
        new_manager_id = mentions[0].id if mentions else None

        # VIP slots
        if slot_num in [24, 25]:
            if data["vips"].get(str(slot_num)):
                data["vips"][str(slot_num)]["name"] = clan_name
                data["vips"][str(slot_num)]["tag"] = clan_tag
                if new_manager_id:
                    data["vips"][str(slot_num)]["manager_id"] = new_manager_id
                updated = True
            else:
                mgr_id = new_manager_id or ctx.author.id
                data["vips"][str(slot_num)] = {
                    'name': clan_name, 'tag': clan_tag, 'manager_id': mgr_id
                }
                updated = True

        # Regular slots
        elif 2 <= slot_num <= 23:
            idx = slot_num - 2
            if idx < len(data["teams"]):
                old_manager_id = data["teams"][idx]["manager_id"]
                data["teams"][idx]["name"] = clan_name
                data["teams"][idx]["tag"] = clan_tag
                if new_manager_id:
                    guild = ctx.guild
                    old_member = guild.get_member(old_manager_id)
                    new_member = guild.get_member(new_manager_id)
                    if old_member:
                        await manage_roles(old_member, key, 'none')
                    if new_member:
                        await manage_roles(new_member, key, 'main')
                    data["teams"][idx]["manager_id"] = new_manager_id
                updated = True

    # ── Mode 2: manager mention provided ──
    elif mentions:
        target_id = mentions[0].id
        if len(parts) < 2:
            await ctx.send("❌  გამოყენება: `%edit @manager <clan name> <clan tag>`", delete_after=10)
            return

        clan_tag = parts[-1]
        clan_name = " ".join(parts[:-1])

        for t in data["teams"]:
            if t["manager_id"] == target_id:
                t["name"] = clan_name
                t["tag"] = clan_tag
                updated = True
                break
        if not updated:
            for s in ["24", "25"]:
                if data["vips"].get(s) and data["vips"][s]["manager_id"] == target_id:
                    data["vips"][s]["name"] = clan_name
                    data["vips"][s]["tag"] = clan_tag
                    updated = True
                    break

    if updated:
        save_scrim_data(key, data)
        await update_all_displays(key, guild=ctx.guild)
        reply = await ctx.send("✅  სლოტი განახლდა!")
    else:
        reply = await ctx.send("❌  სლოტი ვერ მოიძებნა.")

    await ctx.message.delete(delay=5)
    await reply.delete(delay=8)


@bot.command()
@commands.has_permissions(administrator=True)
async def remove(ctx, *, text=None):
    """
    Remove a team by slot number or manager mention, and auto-promote from waitlist.
    """
    key = next(
        (k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"]]),
        None
    )
    if not key or not text:
        return

    data = get_scrim_data(key)
    parts = text.split()
    mentions = ctx.message.mentions
    removed = False
    removed_idx = None

    # By slot number
    if parts and parts[0].isdigit():
        slot_num = int(parts[0])

        if slot_num in [24, 25]:
            if data["vips"].get(str(slot_num)):
                old_mgr = ctx.guild.get_member(data["vips"][str(slot_num)]["manager_id"])
                if old_mgr:
                    await manage_roles(old_mgr, key, 'none')
                del data["vips"][str(slot_num)]
                removed = True
        elif 2 <= slot_num <= 23:
            idx = slot_num - 2
            if idx < len(data["teams"]):
                old_mgr = ctx.guild.get_member(data["teams"][idx]["manager_id"])
                if old_mgr:
                    await manage_roles(old_mgr, key, 'none')
                data["teams"].pop(idx)
                removed = True
                removed_idx = idx

    # By manager mention
    elif mentions:
        target_id = mentions[0].id
        for i, t in enumerate(data["teams"]):
            if t["manager_id"] == target_id:
                old_mgr = ctx.guild.get_member(target_id)
                if old_mgr:
                    await manage_roles(old_mgr, key, 'none')
                data["teams"].pop(i)
                removed = True
                removed_idx = i
                break

        if not removed:
            for s in ["24", "25"]:
                if data["vips"].get(s) and data["vips"][s]["manager_id"] == target_id:
                    old_mgr = ctx.guild.get_member(target_id)
                    if old_mgr:
                        await manage_roles(old_mgr, key, 'none')
                    del data["vips"][s]
                    removed = True
                    break

    # Auto-promote from waitlist if a regular slot was freed
    if removed and removed_idx is not None and data["waitlist"]:
        promoted = data["waitlist"].pop(0)
        data["teams"].insert(removed_idx, promoted)
        promo_member = ctx.guild.get_member(promoted["manager_id"])
        if promo_member:
            await manage_roles(promo_member, key, 'main')
        logger.info(f"Auto-promoted {promoted['name']} from waitlist to slot {removed_idx + 2:02d}")

    if removed:
        save_scrim_data(key, data)
        await update_all_displays(key, guild=ctx.guild)
        reply = await ctx.send("✅  ტიმი წაიშალა" + (" და ვეითლისტიდან ავტომატურად ჩაისვა!" if removed_idx is not None and removed else "!"))
    else:
        reply = await ctx.send("❌  სლოტი ვერ მოიძებნა.")

    await ctx.message.delete(delay=5)
    await reply.delete(delay=8)


@bot.command()
@commands.has_permissions(administrator=True)
async def reset(ctx):
    """Reset all registrations for this scrim."""
    key = next((k for k, v in SCRIMS.items() if ctx.channel.id == v["reg_channel"]), None)
    if not key:
        return
    save_scrim_data(key, {"teams": [], "waitlist": [], "vips": {}})
    await update_all_displays(key, guild=ctx.guild)
    reply = await ctx.send("🔄  სკრიმი სრულად გაასუფთავდა!")
    await ctx.message.delete(delay=3)
    await reply.delete(delay=6)


@bot.command()
@commands.has_permissions(administrator=True)
async def refresh(ctx):
    """Force-refresh both display channels for this scrim."""
    key = next(
        (k for k, v in SCRIMS.items() if ctx.channel.id in [v["reg_channel"], v["slot_channel"], v["wait_channel"]]),
        None
    )
    if not key:
        return
    await update_all_displays(key, guild=ctx.guild)
    reply = await ctx.send("🔁  დისპლეი განახლდა!")
    await reply.delete(delay=5)


# ─── REACTION CONFIRM/UNCONFIRM ──────────────────────────────────────────────

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return

    for scrim_key, cfg in SCRIMS.items():
        if payload.channel_id == cfg["slot_channel"] and payload.message_id == last_msg_ids.get(scrim_key):
            guild = bot.get_guild(payload.guild_id)
            member = guild.get_member(payload.user_id)
            if not member or not member.guild_permissions.administrator:
                channel = bot.get_channel(payload.channel_id)
                msg = await channel.fetch_message(payload.message_id)
                await msg.remove_reaction(payload.emoji, member)
                return

            data = get_scrim_data(scrim_key)
            changed = False

            if str(payload.emoji) == "✅":
                # Confirm the first unconfirmed team
                for t in data["teams"]:
                    if not t.get("confirmed"):
                        t["confirmed"] = True
                        changed = True
                        break

            elif str(payload.emoji) == "❌":
                # Find the last confirmed team, remove from main list, send to waitlist
                for i in range(len(data["teams"]) - 1, -1, -1):
                    if data["teams"][i].get("confirmed"):
                        removed_team = data["teams"].pop(i)
                        removed_team["confirmed"] = False
                        data["waitlist"].append(removed_team)
                        # Demote manager role to waitlist role
                        removed_member = guild.get_member(removed_team["manager_id"])
                        if removed_member:
                            await manage_roles(removed_member, scrim_key, 'wait')
                        changed = True
                        break

            if changed:
                save_scrim_data(scrim_key, data)
                await update_all_displays(scrim_key, guild=guild)
            break


# ─── READY ────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    logger.info(f"✅ {bot.user} მზად არის!")


bot.run(os.getenv('DISCORD_TOKEN'))
