import re
import uuid
from pyrogram import Client, filters, enums
from pyrogram.types import (
    CallbackQuery,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from Backend.config import Telegram
from Backend.helper.settings_manager import SettingsManager
from Backend.logger import LOGGER
from Backend.helper.metadata import get_tmdb_client, _tmdb_details, tmdb_api_key

#----- In-memory query cache for pagination
IMDB_QUERY_CACHE = {}

#----- ISO country code to full name mapping
ISO_COUNTRY_MAP = {
    "US": "United States",
    "GB": "United Kingdom",
    "CA": "Canada",
    "AU": "Australia",
    "IN": "India",
    "FR": "France",
    "DE": "Germany",
    "IT": "Italy",
    "JP": "Japan",
    "KR": "South Korea",
    "ES": "Spain",
    "CN": "China",
    "RU": "Russia",
    "BR": "Brazil",
    "MX": "Mexico",
    "NZ": "New Zealand",
    "ZA": "South Africa",
    "IE": "Ireland",
    "NL": "Netherlands",
    "SE": "Sweden",
    "NO": "Norway",
    "FI": "Finland",
    "DK": "Denmark",
    "BE": "Belgium",
    "CH": "Switzerland",
    "AT": "Austria",
    "PT": "Portugal",
    "HK": "Hong Kong",
    "TW": "Taiwan",
    "TH": "Thailand",
    "TR": "Turkey",
    "PL": "Poland",
    "UA": "Ukraine",
    "MY": "Malaysia",
    "SG": "Singapore",
    "ID": "Indonesia",
    "PH": "Philippines",
    "VN": "Vietnam",
}

#----- Genre to emoji lookup mapping
GENRE_EMOJI_MAP = {
    "Action": "🔥",
    "Adventure": "🗺️",
    "Animation": "🎨",
    "Comedy": "😂",
    "Crime": "🕵️",
    "Documentary": "🎥",
    "Drama": "🎭",
    "Family": "👨‍👩‍👧‍👦",
    "Fantasy": "✨",
    "History": "📜",
    "Horror": "🧟",
    "Music": "🎵",
    "Mystery": "🕵️‍♂️",
    "Romance": "❤️",
    "Science Fiction": "🚀",
    "TV Movie": "📺",
    "Thriller": "😱",
    "War": "⚔️",
    "Western": "🤠",
}


#----- Helper to verify user authorization
def _is_authorized(user_id: int) -> bool:
    if not user_id:
        return False
    if user_id == Telegram.OWNER_ID:
        return True
    auth_users = SettingsManager.current().imdb_authorized_users or []
    return user_id in auth_users


#----- Helper to clean genre names for valid hashtags
def clean_genre_name(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '', name)


#----- Helper to format minutes runtime into hours/minutes
def format_runtime_imdb(runtime_val) -> str:
    if not runtime_val:
        return ""
    try:
        minutes = int(runtime_val)
        if minutes <= 0:
            return ""
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}min"
    except (ValueError, TypeError):
        return ""


#----- Helper to extract the full country name from TMDB details
def get_origin_country_name(details) -> str:
    prod_countries = getattr(details, "production_countries", []) or []
    for c in prod_countries:
        name = getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else None)
        if name:
            if name == "United States of America":
                return "United States"
            return name

    orig_countries = getattr(details, "origin_country", []) or []
    for code in orig_countries:
        if isinstance(code, str):
            code_upper = code.upper().strip()
            name = ISO_COUNTRY_MAP.get(code_upper)
            if name:
                return name
            return code_upper
        elif hasattr(code, "name"):
            return getattr(code, "name")
    return "Unknown"


#----- Helper to execute TMDB search
async def perform_search(client: Client, query: str, page: int = 1):
    api_key = tmdb_api_key()
    if not api_key:
        return None, "⚠️ TMDB API key is not configured. Please set it in Settings first."

    tmdb_client = get_tmdb_client()
    try:
        results = await tmdb_client.search().multi(query=query, page=page)
        return results, None
    except Exception as e:
        LOGGER.error(f"TMDB multi-search failed for query '{query}': {e}")
        return None, f"⚠️ TMDB search failed: {e}"


#----- Helper to construct search result markup with pagination
def build_results_markup(results, page: int, short_id: str) -> InlineKeyboardMarkup:
    buttons = []
    filtered = []
    for item in (results.results or []):
        media_type = getattr(item, "media_type", None)
        if media_type in ("movie", "tv"):
            filtered.append(item)

    for item in filtered:
        media_type = "movie" if item.media_type == "movie" else "tv"
        title = getattr(item, "title" if media_type == "movie" else "name", "Unknown Title")
        date_val = getattr(item, "release_date" if media_type == "movie" else "first_air_date", None)
        year = date_val.year if date_val and hasattr(date_val, "year") else "N/A"
        emoji = "🎬" if media_type == "movie" else "📺"
        button_text = f"{emoji} {title} ({year})"
        callback_data = f"imdb_det:{media_type}:{item.id}"
        buttons.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    # Pagination buttons
    total_pages = getattr(results, "total_pages", 1)
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"imdb_p:{page-1}:{short_id}"))
    nav_buttons.append(InlineKeyboardButton(f"Page {page}/{total_pages}", callback_data="imdb_noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"imdb_p:{page+1}:{short_id}"))
    if nav_buttons:
        buttons.append(nav_buttons)

    return InlineKeyboardMarkup(buttons)


#----- Bot command: /imdb
@Client.on_message(filters.command("imdb"))
async def imdb_cmd(client: Client, message: Message):
    try:
        user_id = (message.from_user.id if message.from_user else None) or (message.sender_chat.id if message.sender_chat else None) or message.chat.id
        if not user_id or not _is_authorized(user_id):
            return await message.reply_text("❌ You are not authorized to use this command.", quote=True)

        if len(message.command) > 1:
            query = " ".join(message.command[1:]).strip()
        else:
            if message.chat.type == enums.ChatType.PRIVATE:
                return await message.reply_text(
                    "🔍 **IMDb Search**\n\nReply to this message with the movie or TV show title you want to search for.",
                    reply_markup=ForceReply(selective=True),
                    quote=True
                )
            else:
                return await message.reply_text("⚠️ Please provide a search query, e.g. `/imdb Inception`", quote=True)

        results, err = await perform_search(client, query, page=1)
        if err:
            return await message.reply_text(err, quote=True)

        if not results or not results.results:
            return await message.reply_text(f"❌ No results found for '{query}'.", quote=True)

        short_id = uuid.uuid4().hex[:8]
        IMDB_QUERY_CACHE[short_id] = query

        markup = build_results_markup(results, 1, short_id)
        await message.reply_text(
            f"🔍 **Search results for:** `{query}`\nSelect a title to format:",
            reply_markup=markup,
            quote=True
        )
    except Exception as e:
        LOGGER.error(f"Error in /imdb command: {e}")
        await message.reply_text(f"⚠️ Error: {e}", quote=True)


#----- Bot private chat reply capture
@Client.on_message(filters.reply & filters.private)
async def handle_imdb_prompt_reply(client: Client, message: Message):
    try:
        user_id = message.from_user.id if message.from_user else message.chat.id
        if not _is_authorized(user_id):
            return

        reply = message.reply_to_message
        if not reply or not reply.text:
            return

        if "Reply to this message with the movie or TV show title" in reply.text:
            query = (message.text or "").strip()
            if not query:
                return await message.reply_text("⚠️ Search query cannot be empty.", quote=True)

            results, err = await perform_search(client, query, page=1)
            if err:
                return await message.reply_text(err, quote=True)

            if not results or not results.results:
                return await message.reply_text(f"❌ No results found for '{query}'.", quote=True)

            short_id = uuid.uuid4().hex[:8]
            IMDB_QUERY_CACHE[short_id] = query

            markup = build_results_markup(results, 1, short_id)
            await message.reply_text(
                f"🔍 **Search results for:** `{query}`\nSelect a title to format:",
                reply_markup=markup,
                quote=True
            )
    except Exception as e:
        LOGGER.error(f"Error in handle_imdb_prompt_reply: {e}")
        await message.reply_text(f"⚠️ Error: {e}", quote=True)


#----- Callback query: Pagination
@Client.on_callback_query(filters.regex(r"^imdb_p:(\d+):([a-zA-Z0-9]+)$"))
async def imdb_page_callback(client: Client, callback_query: CallbackQuery):
    try:
        user_id = callback_query.from_user.id
        if not _is_authorized(user_id):
            return await callback_query.answer("You are not authorized to perform this action.", show_alert=True)

        page = int(callback_query.matches[0].group(1))
        short_id = callback_query.matches[0].group(2)

        query = IMDB_QUERY_CACHE.get(short_id)
        if not query:
            return await callback_query.answer("Search session expired. Please run the command again.", show_alert=True)

        await callback_query.answer("Loading page...")

        results, err = await perform_search(client, query, page=page)
        if err:
            return await callback_query.message.edit_text(err)

        if not results or not results.results:
            return await callback_query.message.edit_text(f"❌ No results found for '{query}'.")

        markup = build_results_markup(results, page, short_id)
        await callback_query.message.edit_text(
            f"🔍 **Search results for:** `{query}`\nSelect a title to format:",
            reply_markup=markup
        )
    except Exception as e:
        LOGGER.error(f"Error in imdb_page_callback: {e}")
        await callback_query.answer(f"Error: {e}", show_alert=True)


#----- Callback query: No-op
@Client.on_callback_query(filters.regex(r"^imdb_noop$"))
async def imdb_noop_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()


#----- Callback query: Detail selection & in-bot formatting response
@Client.on_callback_query(filters.regex(r"^imdb_det:(movie|tv):(\d+)$"))
async def imdb_detail_callback(client: Client, callback_query: CallbackQuery):
    try:
        user_id = callback_query.from_user.id
        if not _is_authorized(user_id):
            return await callback_query.answer("You are not authorized to perform this action.", show_alert=True)

        media_type = callback_query.matches[0].group(1)
        tmdb_id = int(callback_query.matches[0].group(2))

        await callback_query.answer("Formatting post...")

        # Fetch full details
        details = await _tmdb_details(media_type, tmdb_id)
        if not details:
            return await callback_query.message.reply_text(
                f"❌ Failed to fetch TMDB details for {media_type} id {tmdb_id}.",
                quote=True
            )

        # Format fields
        title = getattr(details, "title" if media_type == "movie" else "name", "Unknown Title") or "Unknown Title"

        # Runtime
        if media_type == "movie":
            runtime_mins = getattr(details, "runtime", None)
        else:
            runtimes = getattr(details, "episode_run_time", None)
            runtime_mins = runtimes[0] if runtimes and len(runtimes) > 0 else None

        runtime_str = format_runtime_imdb(runtime_mins)

        # Date
        date_val = getattr(details, "release_date" if media_type == "movie" else "first_air_date", None)
        if date_val and hasattr(date_val, "day") and hasattr(date_val, "month") and hasattr(date_val, "year"):
            release_date = f"{date_val.day} / {date_val.month} / {date_val.year}"
        elif isinstance(date_val, str):
            try:
                from datetime import datetime
                dt = datetime.strptime(date_val.split("T")[0], "%Y-%m-%d")
                release_date = f"{dt.day} / {dt.month} / {dt.year}"
            except Exception:
                release_date = date_val or "N/A"
        else:
            release_date = "N/A"

        # Country
        origin_country = get_origin_country_name(details)

        # Genres (e.g. #Action ✨ #Fantasy 📜 #History 🧟 #Horror)
        genre_names = [g.name for g in (getattr(details, "genres", []) or []) if getattr(g, "name", None)]
        genre_strings = []
        for i, gname in enumerate(genre_names):
            cleaned_name = clean_genre_name(gname)
            genre_emoji = GENRE_EMOJI_MAP.get(gname, "")
            if i == 0:
                genre_strings.append(f"#{cleaned_name}")
            else:
                emoji_prefix = f" {genre_emoji} " if genre_emoji else " "
                genre_strings.append(f"{emoji_prefix}#{cleaned_name}")
        genres_text = "".join(genre_strings) if genre_strings else "N/A"

        # Rating
        vote_avg = getattr(details, "vote_average", 0) or 0
        vote_cnt = getattr(details, "vote_count", 0) or 0
        try:
            rating_val = f"{float(vote_avg):.1f}"
        except (ValueError, TypeError):
            rating_val = "0.0"
        rating_text = f"{rating_val} / 10 (by {vote_cnt})"

        # Assemble Info Line
        info_parts = []
        if runtime_str:
            info_parts.append(runtime_str)
        info_parts.append(f"{release_date} ({origin_country})")
        info_line = " | ".join(info_parts)

        # Render template text (ends with simple plain text)
        post_text = (
            f"📺{title}📺\n\n"
            f"📆Info : {info_line}\n"
            f"🎭Genres : {genres_text}\n"
            f"⭐Rating : {rating_text}\n\n"
            f"🔥Click Here To Download🔥"
        )

        # Send the final formatted message back to the bot chat
        await client.send_message(
            chat_id=callback_query.message.chat.id,
            text=post_text,
            disable_web_page_preview=True
        )

        # Delete the interactive search menu message
        try:
            await callback_query.message.delete()
        except Exception:
            pass

    except Exception as e:
        LOGGER.error(f"Error in imdb_detail_callback: {e}")
        await callback_query.message.reply_text(f"⚠️ Error formatting: {e}", quote=True)
