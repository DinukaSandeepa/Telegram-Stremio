# Prompt for Antigravity 2.0 — "/imdb Search → Formatted Channel Post" feature

Copy everything below into Antigravity as your task prompt.

---

## Context

This is the **Telegram-Stremio** project (FastAPI + MongoDB + PyroFork, Python backend under `Backend/`, with a web admin panel and a Telegram bot). Key things already in the codebase you should reuse rather than reinvent:

- A working **TMDB API integration** (TMDB v3 key stored in Settings, used today for auto-matching posters/metadata and for the "Add Content" / "Manual Upload Session" search boxes that already search by title, IMDb id/link, or TMDB id/link).
- A **web Settings page** (`/admin/settings`) backed by a settings collection/model in MongoDB, where things like `AUTH_CHANNELS`, `Announcement Channel`, `Skip Channel`, `Manual Channel` are stored and applied instantly without restart.
- An existing **bot command layer** (PyroFork handlers) with authorization/owner checks already used elsewhere (e.g. subscription approval flow, manual upload session).
- Look specifically at `Backend/fastapi/routes/` (TMDB/Stremio metadata formatting logic, e.g. `stremio_routes.py`) and the bot handlers directory (search for existing `/imdb`, `/search`, or "Manual Upload Session" TMDB search code) — **reuse their TMDB client, search, and pagination/inline-keyboard patterns instead of writing new ones.**

Before writing any code: explore the repo structure yourself (`Backend/` tree, bot handlers, settings model, TMDB client module) and confirm where the existing `/imdb` command (if any) currently lives, and how TMDB search results are currently paginated/rendered as inline buttons. Tell me what you find before generating the final plan, in case an `/imdb` command already exists partially and just needs the "send formatted post" step added.

## Goal

Add/extend the `/imdb` bot command so that:

1. An **authorized user** runs `/imdb <query>` (or is prompted for a query).
2. The bot searches **TMDB** (movie + TV) for that query and shows results as an inline keyboard (poster thumbnail optional, title + year per row), reusing the existing search/pagination pattern from Manual Upload Session if one exists.
3. When the user **taps/selects a title**, the bot fetches that title's full TMDB details (runtime, release/air date, origin country, genres, vote average, vote count, title/name) and **renders them into the exact template below**.
4. The bot then **posts that rendered message** to a Telegram channel — the destination channel must be **configurable from the web admin Settings page** (add a new setting, e.g. `IMDB_POST_CHANNEL`, following the same pattern as `Announcement Channel` / `Skip Channel`: store as channel ID or `@username`, validate the bot is admin there, apply instantly without restart).
5. Confirm success back to the user in the bot chat (e.g. "✅ Posted to channel").

## Exact template to reproduce

```
📺{Title}📺

📆Info : {Runtime} | {Release Date} ({Origin Country})
🎭Genres : {Genre list with per-genre emoji}
⭐Rating : {Vote Average} / 10 (by {Vote Count})

🔥Click Here To Download🔥
```

Formatting rules for each field:

- **Title**: TMDB `title` (movies) or `name` (TV), wrapped in the 📺 emoji on both sides exactly as shown.
- **Runtime**: convert TMDB minutes into `XhYmin` format, e.g. `50` → `0h 50min`, `128` → `2h 8min`. For TV shows, use `episode_run_time[0]` if present; if runtime is missing/zero, omit the `XhYmin |` segment gracefully rather than printing `0h 0min`.
- **Release Date**: format as `D / M / YYYY` (no leading zeros, matching the example `17 / 7 / 2026`) from TMDB `release_date` (movies) or `first_air_date` (TV).
- **Origin Country**: full country name in parentheses, e.g. `(United States)`, derived from TMDB `production_countries` (movies) or `origin_country` (TV) — map ISO codes to full names (there's likely already a country-code lookup somewhere in the metadata formatting code; reuse it).
- **Genres**: each genre rendered as `#GenreName` with a genre-specific emoji. Build a lookup dict covering all standard TMDB genres, e.g.:

  | Genre | Emoji |
  |---|---|
  | Action | 🔥 |
  | Adventure | 🗺️ |
  | Animation | 🎨 |
  | Comedy | 😂 |
  | Crime | 🕵️ |
  | Documentary | 🎥 |
  | Drama | 🎭 |
  | Family | 👨‍👩‍👧‍👦 |
  | Fantasy | ✨ |
  | History | 📜 |
  | Horror | 🧟 |
  | Music | 🎵 |
  | Mystery | 🕵️‍♂️ |
  | Romance | ❤️ |
  | Science Fiction | 🚀 |
  | TV Movie | 📺 |
  | Thriller | 😱 |
  | War | ⚔️ |
  | Western | 🤠 |

  Join genres as `#Genre1 emoji1 #Genre2 emoji2 #Genre3 ...` — **match the exact spacing/ordering shown in the sample** (`#Action ✨ #Fantasy 📜 #History 🧟 #Horror`): emoji sits between two hashtags. Implement it as: for each genre after the first, prefix it with the *previous* genre's... **actually, please just replicate this literally**: iterate genres, and after each genre (except the last) insert that *next* genre's emoji before the `#`. If ambiguous, ask me to confirm with a live example before finalizing, since this spacing is easy to get subtly wrong.
- **Rating**: `{vote_average rounded to 1 decimal} / 10 (by {vote_count})`. If `vote_count` is 0, still show `0 / 10 (by 0)` rather than crashing.
- **Download line**: `🔥Click Here To Download🔥` should be a clickable inline link/button, not plain text. Since the title may not exist in the library yet at post time, make the **link target configurable**: default it to a deep link back into the bot (`https://t.me/<bot_username>?start=req_{tmdb_id}`) so an admin/user tapping it triggers a bot flow, but structure the code so this URL template is a single named constant/setting I can easily change later (e.g. to point at the eventual Stremio/manifest page once the title is added). **Ask me to confirm the exact target if it matters before hardcoding one option.**

## Implementation requirements

- **Authorization**: reuse whatever existing decorator/check gates other privileged commands (e.g. Manual Upload Session, Add Content) — don't build a new auth mechanism.
- **Settings**: add `IMDB_POST_CHANNEL` (name it consistently with existing settings keys) to the settings model, the Settings page UI, and validate the bot is an admin there, mirroring how `Announcement Channel` / `Skip Channel` are implemented (find their code and copy the pattern exactly, including instant-apply/no-restart behavior).
- **Error handling**: TMDB lookup failures, missing fields (no runtime, no genres, no country), bot not being admin in the target channel, and no `IMDB_POST_CHANNEL` configured yet should all fail gracefully with a clear message back to the user — never a raw exception/stack trace in the chat.
- **Code style**: match existing project conventions (async PyroFork handlers, existing TMDB client wrapper, existing MongoDB access patterns, existing logging).
- **No breaking changes**: don't touch the existing Manual Upload Session / Add Content TMDB search flows except to extract shared helpers if that's clearly the right refactor — flag it to me first if it touches those files.
- **Testing**: after implementing, show me the exact rendered message for at least one movie and one TV show example (using real TMDB data via a search) so I can sanity-check spacing/emoji/formatting before we call this done.

## Before you start coding

Please first:
1. Report back the relevant existing files/functions you found (TMDB client, settings model/page, `/imdb` command if it exists, announcement/skip channel implementation).
2. Propose the exact diff/plan (new files vs. edited files, new settings field name, exact genre-join algorithm) for my approval.
3. Only then implement.
