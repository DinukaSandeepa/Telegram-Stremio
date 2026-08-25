from __future__ import annotations

import re
import traceback
from typing import Optional

from rapidfuzz import fuzz

from Backend.helper.encrypt import encode_string
from Backend.helper.metadata.common import extract_default_id
from Backend.helper.settings_manager import SettingsManager
from Backend.logger import LOGGER


def clean_porn_title(title: str) -> str:
    # 1. Lowercase for uniform matching
    t = title.lower()
    # Replace dots, underscores, dashes with space
    t = re.sub(r'[._\-]', ' ', t)
    
    # 2. Find index of first quality/codec indicator to truncate from
    indicators = [
        r'\b720p\b', r'\b1080p\b', r'\b2160p\b', r'\b4k\b',
        r'\bweb\b', r'\bdvdrip\b', r'\bhdrip\b', r'\bwebrip\b', r'\brip\b',
        r'\bx264\b', r'\bx265\b', r'\bhevc\b', r'\bh264\b', r'\bh265\b',
        r'\bglam\s+porn\b', r'\bgalaxxxy\b'
    ]
    
    min_idx = len(t)
    for ind in indicators:
        match = re.search(ind, t)
        if match:
            min_idx = min(min_idx, match.start())
            
    # Truncate technical detail suffixes
    t = t[:min_idx]
    
    # 3. Match and remove dates (YY MM DD or YYYY MM DD)
    t = re.sub(r'\b(20)?\d{2}\s+\d{2}\s+\d{2}\b', ' ', t)
    
    # 4. Remove other noise words
    noise_words = [
        r'\bxxx\b', r'\bhardcore\b', r'\bpov\b', r'\bfrench\b', r'\bdutch\b',
        r'\bgerman\b', r'\bspanish\b', r'\bjapanese\b', r'\brussian\b'
    ]
    for nw in noise_words:
        t = re.sub(nw, ' ', t)
        
    # 5. Collapse spaces and strip
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def is_uuid(s: str) -> bool:
    if not s:
        return False
    return bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", s.lower()))


def extract_porn_date(filename: str) -> str | None:
    # Match YY.MM.DD or YYYY.MM.DD separated by dots, spaces, dashes or underscores
    match = re.search(r'\b(?:20)?(\d{2})[.\s_-](\d{2})[.\s_-](\d{2})\b', filename)
    if match:
        yy = match.group(1)
        mm = match.group(2)
        dd = match.group(3)
        if len(yy) == 2:
            year_val = int(yy)
            yyyy = f"20{year_val:02d}" if year_val < 50 else f"19{year_val:02d}"
        else:
            yyyy = yy
        return f"{yyyy}-{mm}-{dd}"
    return None


def generate_porn_queries(filename: str) -> list[str]:
    # Strip extension
    base_name = re.sub(r"\.(mkv|mp4|avi|ts|m4v|mov|wmv|webm|flv)$", "", filename, flags=re.IGNORECASE)
    
    # Extract date
    extracted_date = extract_porn_date(base_name)
    
    # Remove date from the string for cleaning
    date_pattern = r'\b(?:20)?\d{2}[.\s_-]\d{2}[.\s_-]\d{2}\b'
    no_date_name = re.sub(date_pattern, ' ', base_name)
    
    # Clean the name (replace dots/dashes/underscores with space, remove technical indicators, noise words)
    cleaned_no_date = clean_porn_title(no_date_name)
    
    queries = []
    
    # 1. Cleaned name with formatted date
    if extracted_date:
        queries.append(f"{cleaned_no_date} {extracted_date}")
        # Also try with raw date parts if different
        date_match = re.search(r'\b(?:20)?(\d{2})[.\s_-](\d{2})[.\s_-](\d{2})\b', base_name)
        if date_match:
            raw_date_str = date_match.group(0).replace('.', ' ').replace('_', ' ').replace('-', ' ')
            queries.append(f"{cleaned_no_date} {raw_date_str}")
            
    # 2. Cleaned name alone
    queries.append(cleaned_no_date)
    
    # 3. Shortened version (first few words) + date
    words = cleaned_no_date.split()
    if len(words) > 2:
        short_name = " ".join(words[:3])
        if extracted_date:
            queries.append(f"{short_name} {extracted_date}")
        queries.append(short_name)
        
        # Also try removing the first word (often studio)
        rest_name = " ".join(words[1:])
        if extracted_date:
            queries.append(f"{rest_name} {extracted_date}")
        queries.append(rest_name)
        
    # Deduplicate while preserving order
    seen = set()
    deduped_queries = []
    for q in queries:
        q_strip = q.strip()
        if q_strip and q_strip not in seen and len(q_strip) >= 3:
            seen.add(q_strip)
            deduped_queries.append(q_strip)
            
    return deduped_queries


def text_containment_score(query: str, target: str) -> float:
    q_words = set(re.findall(r'\w+', query.lower()))
    t_words = set(re.findall(r'\w+', target.lower()))
    if not t_words:
        return 0.0
    matched = t_words.intersection(q_words)
    return len(matched) / len(t_words)


def score_scene(scene: dict, query_clean: str, file_date: str | None, file_year: int | None, tg_duration: int | None) -> float:
    scene_title = scene.get("title") or ""
    
    # 1. Base text match
    fuzz_ratio = fuzz.token_sort_ratio(query_clean, scene_title.lower()) / 100.0
    containment = text_containment_score(query_clean, scene_title)
    score = max(fuzz_ratio, containment)
    
    # 2. Date match
    scene_date = scene.get("date")
    if file_date and scene_date and file_date == scene_date:
        score += 0.50
    elif file_year and scene_date:
        try:
            scene_year = int(scene_date[:4])
            if scene_year == file_year:
                score += 0.10
        except ValueError:
            pass
            
    # 3. Performer match
    performers = [p.get("performer", {}).get("name") for p in (scene.get("performers") or []) if p.get("performer")]
    perf_matched = False
    for p in performers:
        if p:
            p_clean = p.lower()
            p_no_spaces = p_clean.replace(" ", "")
            if p_clean in query_clean or p_no_spaces in query_clean.replace(" ", ""):
                perf_matched = True
    if perf_matched:
        score += 0.15
        
    # 4. Studio match
    studio = (scene.get("studio") or {}).get("name")
    if studio:
        s_clean = studio.lower()
        s_no_spaces = s_clean.replace(" ", "")
        if s_clean in query_clean or s_no_spaces in query_clean.replace(" ", ""):
            score += 0.15
            
    # 5. Duration match
    scene_duration = scene.get("duration")
    if tg_duration and scene_duration:
        diff = abs(tg_duration - scene_duration)
        if diff <= 5:
            score += 0.60
        elif diff <= 15:
            score += 0.40
        elif diff <= 30:
            score += 0.20
        elif diff > 60:
            score -= 0.30
            
    return score


async def fetch_porn_metadata(
    title: str,
    encoded_string: str | None,
    year: int | None,
    quality: str,
    duration: int | None = None,
    override_id: str | None = None
) -> dict | None:
    """Query ThePornDB GraphQL API for scene metadata, with fallback query logic and local metadata generation."""
    try:
        import httpx
    except ImportError:
        LOGGER.error("[PORN] httpx not installed – cannot call ThePornDB API")
        return None

    cleaned = clean_porn_title(title)
    LOGGER.info(f"[PORN] Cleaned search query: '{cleaned}' (original: '{title}', duration: {duration}, override_id: {override_id})")

    api_key = SettingsManager.current().theporndb_api_key
    best = None
    best_score = 0.0

    graphql_find_query = """
    query findScene($id: ID!) {
        findScene(id: $id) {
            id
            title
            date
            details
            duration
            images {
                url
                width
                height
            }
            studio {
                name
            }
            tags {
                name
            }
            performers {
                performer {
                    name
                }
            }
        }
    }
    """

    graphql_query = """
    query searchScene($term: String!, $limit: Int) {
        searchScene(term: $term, limit: $limit) {
            id
            title
            date
            details
            duration
            images {
                url
                width
                height
            }
            studio {
                name
            }
            tags {
                name
            }
            performers {
                performer {
                    name
                }
            }
        }
    }
    """

    if api_key:
        # Check override_id first
        if override_id:
            clean_id = override_id.strip()
            if ":" in clean_id:
                clean_id = clean_id.split(":", 1)[1]
            elif "_" in clean_id:
                clean_id = clean_id.split("_", 1)[1]

            if is_uuid(clean_id):
                try:
                    LOGGER.info(f"[PORN] Querying findScene directly with ID: '{clean_id}'")
                    async with httpx.AsyncClient(timeout=15) as client:
                        resp = await client.post(
                            "https://theporndb.net/graphql",
                            json={"query": graphql_find_query, "variables": {"id": clean_id}},
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                            },
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        best = (data.get("data") or {}).get("findScene")
                        if best:
                            best_score = 3.0  # Absolute match
                except Exception as e:
                    LOGGER.error(f"[PORN] ThePornDB API error for findScene ID '{clean_id}': {e}")

        # If no override match, query standard search
        if not best and cleaned:
            queries_to_try = generate_porn_queries(title)
            unique_scenes = {}

            for q in queries_to_try:
                try:
                    LOGGER.info(f"[PORN] Querying ThePornDB with: '{q}'")
                    async with httpx.AsyncClient(timeout=15) as client:
                        resp = await client.post(
                            "https://theporndb.net/graphql",
                            json={"query": graphql_query, "variables": {"term": q, "limit": 100}},
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                            },
                        )
                        resp.raise_for_status()
                        data = resp.json()
                except Exception as e:
                    LOGGER.error(f"[PORN] ThePornDB API error for query '{q}': {e}")
                    continue

                scenes = (data.get("data") or {}).get("searchScene") or []
                for scene in scenes:
                    if scene and scene.get("id"):
                        unique_scenes[scene["id"]] = scene

            file_date = extract_porn_date(title)
            scored_scenes = []
            for scene_id, scene in unique_scenes.items():
                score = score_scene(scene, cleaned, file_date, year, duration)
                scored_scenes.append((score, scene))

            if scored_scenes:
                scored_scenes.sort(key=lambda x: x[0], reverse=True)
                top_score, top_scene = scored_scenes[0]
                if top_score >= 0.40:
                    best = top_scene
                    best_score = top_score
                    LOGGER.info(f"[PORN] Best match chosen with score {best_score:.2f}: {best.get('title')} (ID: {best.get('id')})")
                else:
                    LOGGER.info(f"[PORN] Highest score {top_score:.2f} below threshold 0.40; falling back to local metadata.")

    # ── FALLBACK / LOCAL METADATA GENERATION ──
    # If no API key or no match found above threshold
    if not best:
        LOGGER.info(f"[PORN] Generating fallback metadata locally for '{title}'")
        file_date = extract_porn_date(title)
        release_year = int(file_date[:4]) if file_date else year
        
        # Clean title for display (capitalize words)
        display_title = " ".join(word.capitalize() for word in cleaned.split()) if cleaned else title

        local_id = abs(hash(display_title + str(release_year))) % (10 ** 8)
        
        return {
            "title": display_title,
            "rate": None,
            "year": release_year,
            "poster": None,
            "backdrop": None,
            "description": f"Adult scene: {display_title}",
            "genres": ["Adult"],
            "media_type": "porn",
            "imdb_id": f"tpdb:{local_id}",
            "tmdb_id": local_id,
            "tpdb_id": str(local_id),
            "studio": None,
            "cast": [],
            "runtime": None,
            "id": encoded_string,
            "quality": quality,
        }

    # ── PARSE BEST SCENE ──
    tpdb_id = best.get("id")
    scene_title = best.get("title") or cleaned
    scene_date = best.get("date") or ""
    release_year = int(scene_date[:4]) if len(scene_date) >= 4 and scene_date[:4].isdigit() else year
    description = best.get("details") or ""
    
    images = best.get("images") or []
    poster_url = None
    backdrop_url = None
    
    for img in images:
        url = img.get("url")
        w = img.get("width")
        h = img.get("height")
        if url:
            if w and h:
                if w > h:
                    if not backdrop_url:
                        backdrop_url = url
                else:
                    if not poster_url:
                        poster_url = url
            else:
                if not poster_url:
                    poster_url = url

    if not poster_url and backdrop_url:
        poster_url = backdrop_url
    if not backdrop_url and poster_url:
        backdrop_url = poster_url

    studio = (best.get("studio") or {}).get("name")
    
    tags = [t.get("name") for t in (best.get("tags") or []) if t.get("name")]
    genres = ["Adult"]
    for t in tags:
        if t not in genres:
            genres.append(t)
            
    performers = [p.get("performer", {}).get("name") for p in (best.get("performers") or []) if p.get("performer")]
    
    duration_secs = best.get("duration")
    runtime = f"{duration_secs // 60} min" if duration_secs else None

    # Derive numeric ID for internal lookups
    clean_numeric_id = abs(hash(tpdb_id)) % (10 ** 8)

    return {
        "title": scene_title,
        "rate": 10.0,
        "year": release_year,
        "poster": poster_url,
        "backdrop": backdrop_url,
        "description": description,
        "genres": genres,
        "media_type": "porn",
        "imdb_id": f"tpdb:{tpdb_id}",
        "tmdb_id": clean_numeric_id,
        "tpdb_id": tpdb_id,
        "studio": studio,
        "cast": performers,
        "runtime": runtime,
        "id": encoded_string,
        "quality": quality,
    }


def _to_selection_payload(data: dict, media_type: str = "porn") -> dict:
    return {
        "title": data.get("title", ""),
        "year": data.get("year"),
        "poster": data.get("poster"),
        "backdrop": data.get("backdrop"),
        "description": data.get("description", ""),
        "rate": data.get("rate"),
        "genres": data.get("genres", []),
        "cast": data.get("cast", []),
        "studio": data.get("studio"),
        "runtime": data.get("runtime"),
        "media_type": media_type,
        "imdb_id": data.get("imdb_id"),
        "tmdb_id": data.get("tmdb_id"),
        "tpdb_id": data.get("tpdb_id"),
    }


async def search_porn_candidates(query: str, limit: int = 8) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []

    default_id = extract_default_id(query)
    if default_id:
        clean_id = default_id.strip()
        if ":" in clean_id:
            clean_id = clean_id.split(":", 1)[1]
        elif "_" in clean_id:
            clean_id = clean_id.split("_", 1)[1]

        if is_uuid(clean_id):
            best = await fetch_porn_metadata(
                title="manual-rescan", encoded_string=None, year=None, quality="HD", override_id=clean_id
            )
            if best:
                tpdb_id = best.get("tpdb_id") or clean_id
                selected_id = f"tpdb:{tpdb_id}"
                studio = best.get("studio") or "Unknown Studio"
                cast = best.get("cast") or []
                cast_str = f" ({', '.join(cast)})" if cast else ""
                subtitle = f"{studio}{cast_str}"
                return [{
                    "source": "tpdb",
                    "media_type": "porn",
                    "title": best.get("title", ""),
                    "year": str(best.get("year", "")),
                    "imdb_id": f"tpdb:{tpdb_id}",
                    "tmdb_id": best.get("tmdb_id"),
                    "selected_id": selected_id,
                    "poster": best.get("poster"),
                    "backdrop": best.get("backdrop"),
                    "subtitle": subtitle,
                }]

    api_key = SettingsManager.current().theporndb_api_key
    if not api_key:
        return []

    graphql_query = """
    query searchScene($term: String!, $limit: Int) {
        searchScene(term: $term, limit: $limit) {
            id
            title
            date
            duration
            images {
                url
                width
                height
            }
            studio {
                name
            }
            performers {
                performer {
                    name
                }
            }
        }
    }
    """

    results = []
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://theporndb.net/graphql",
                json={"query": graphql_query, "variables": {"term": query, "limit": limit}},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            scenes = (data.get("data") or {}).get("searchScene") or []
            for scene in scenes:
                tpdb_id = scene.get("id")
                title = scene.get("title")
                date_str = scene.get("date") or ""
                year = date_str[:4] if len(date_str) >= 4 else ""
                
                images = scene.get("images") or []
                poster_url = None
                backdrop_url = None
                for img in images:
                    url = img.get("url")
                    w = img.get("width")
                    h = img.get("height")
                    if url:
                        if w and h:
                            if w > h:
                                if not backdrop_url:
                                    backdrop_url = url
                            else:
                                if not poster_url:
                                    poster_url = url
                        else:
                            if not poster_url:
                                poster_url = url
                if not poster_url and backdrop_url:
                    poster_url = backdrop_url
                if not backdrop_url and poster_url:
                    backdrop_url = poster_url

                studio = (scene.get("studio") or {}).get("name") or "Unknown Studio"
                performers = [p.get("performer", {}).get("name") for p in (scene.get("performers") or []) if p.get("performer")]
                perf_str = f" ({', '.join(performers)})" if performers else ""
                subtitle = f"{studio}{perf_str}"

                results.append({
                    "source": "tpdb",
                    "media_type": "porn",
                    "title": title,
                    "year": year,
                    "imdb_id": f"tpdb:{tpdb_id}",
                    "tmdb_id": None,
                    "selected_id": f"tpdb:{tpdb_id}",
                    "poster": poster_url,
                    "backdrop": backdrop_url,
                    "subtitle": subtitle,
                })
    except Exception as e:
        LOGGER.error(f"[PORN] search_porn_candidates API error for query '{query}': {e}")

    return results


async def fetch_selected_porn_metadata(selected_id: str) -> dict | None:
    selected_id = str(selected_id).strip()
    if not selected_id:
        return None
    data = await fetch_porn_metadata(
        title="manual-rescan", encoded_string=None, year=None, quality="HD", override_id=selected_id
    )
    return _to_selection_payload(data, "porn") if data else None
