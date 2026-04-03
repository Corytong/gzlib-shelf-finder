import html
import json
import os
import random
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from http import HTTPStatus
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8011"))
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "catalog_cache.sqlite3"
CACHE_LOCK = threading.Lock()

CATALOG_BASE = "https://opac.gzlib.org.cn/opac"
LIBRARY_TREE_URL = f"{CATALOG_BASE}/tree/libcodes"
RECOMMENDATION_SOURCE_URL = "https://www.douban.com/doulist/45298673/"
RECOMMENDATION_PAGE_SIZE = 25
RECOMMENDATION_TOTAL = 500

LIBRARY_TTL = 24 * 60 * 60
RECOMMENDATION_TTL = 24 * 60 * 60
SEARCH_TTL = 7 * 24 * 60 * 60
HOLDING_TTL = 12 * 60 * 60

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
}


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_cache (
                key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                fetched_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS book_meta (
                bookrecno TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                normalized_title TEXT NOT NULL,
                author TEXT DEFAULT '',
                normalized_author TEXT DEFAULT '',
                publisher TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                index_hint INTEGER DEFAULT 1,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_book_meta_title ON book_meta(normalized_title)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_book_meta_author ON book_meta(normalized_author)"
        )


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def cache_get_json(key, max_age):
    with CACHE_LOCK:
        with db_connect() as conn:
            row = conn.execute(
                "SELECT payload, fetched_at FROM kv_cache WHERE key = ?",
                (key,),
            ).fetchone()

    if not row:
        return None

    if int(time.time()) - row["fetched_at"] > max_age:
        return None

    return json.loads(row["payload"])


def cache_set_json(key, payload):
    now = int(time.time())
    serialized = json.dumps(payload, ensure_ascii=False)
    with CACHE_LOCK:
        with db_connect() as conn:
            conn.execute(
                """
                INSERT INTO kv_cache(key, payload, fetched_at)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  payload = excluded.payload,
                  fetched_at = excluded.fetched_at
                """,
                (key, serialized, now),
            )


def save_book_meta(candidates):
    now = int(time.time())
    rows = [
        (
            str(candidate.get("bookrecno", "")),
            candidate.get("title", ""),
            simplify_title(candidate.get("title", "")),
            candidate.get("author", ""),
            simplify_author(candidate.get("author", "")),
            candidate.get("publisher", ""),
            candidate.get("summary", ""),
            int(candidate.get("index", 1) or 1),
            now,
        )
        for candidate in candidates
        if candidate.get("bookrecno") and candidate.get("title")
    ]
    if not rows:
        return

    with CACHE_LOCK:
        with db_connect() as conn:
            conn.executemany(
                """
                INSERT INTO book_meta(
                  bookrecno, title, normalized_title, author, normalized_author,
                  publisher, summary, index_hint, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bookrecno) DO UPDATE SET
                  title = excluded.title,
                  normalized_title = excluded.normalized_title,
                  author = excluded.author,
                  normalized_author = excluded.normalized_author,
                  publisher = excluded.publisher,
                  summary = excluded.summary,
                  index_hint = excluded.index_hint,
                  updated_at = excluded.updated_at
                """,
                rows,
            )


def find_local_candidates(query, options):
    normalized_title = simplify_title(query)
    normalized_author = simplify_author(options.get("author", ""))
    if not normalized_title:
        return []

    clauses = []
    params = []

    if options.get("fuzzy"):
        clauses.append("normalized_title LIKE ?")
        params.append(f"%{normalized_title}%")
    else:
        clauses.append("(normalized_title = ? OR normalized_title LIKE ?)")
        params.extend([normalized_title, f"{normalized_title}%"])

    if normalized_author:
        clauses.append(
            "(normalized_author = ? OR normalized_author LIKE ? OR normalized_author LIKE ?)"
        )
        params.extend(
            [
                normalized_author,
                f"%{normalized_author}%",
                f"{normalized_author}%",
            ]
        )

    where_sql = " AND ".join(clauses)
    with CACHE_LOCK:
        with db_connect() as conn:
            rows = conn.execute(
                f"""
                SELECT bookrecno, title, author, publisher, summary, index_hint
                FROM book_meta
                WHERE {where_sql}
                ORDER BY updated_at DESC
                LIMIT 20
                """,
                params,
            ).fetchall()

    return [
        {
            "bookrecno": row["bookrecno"],
            "title": row["title"],
            "author": row["author"],
            "publisher": row["publisher"],
            "summary": row["summary"],
            "index": row["index_hint"] or 1,
        }
        for row in rows
    ]


def load_proxy_pool():
    env_value = os.environ.get("GZLIB_PROXY_POOL", "")
    proxies = []
    if env_value.strip():
        proxies.extend([item.strip() for item in re.split(r"[\n,]+", env_value) if item.strip()])

    proxy_file = ROOT / "proxy_pool.txt"
    if proxy_file.exists():
        proxies.extend(
            [
                line.strip()
                for line in proxy_file.read_text("utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        )

    unique = []
    seen = set()
    for proxy in proxies:
        if proxy in seen:
            continue
        seen.add(proxy)
        unique.append(proxy)
    return unique


PROXY_POOL = load_proxy_pool()


class CatalogSession:
    def __init__(self):
        self.user_agent = random.choice(USER_AGENTS)
        self.proxy = random.choice(PROXY_POOL) if PROXY_POOL else None
        handlers = [urllib.request.HTTPCookieProcessor(CookieJar())]
        if self.proxy:
            handlers.append(
                urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy})
            )
        self.opener = urllib.request.build_opener(*handlers)

    def _headers(self, referer=None):
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/json,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def fetch_text(self, url, referer=None):
        request = urllib.request.Request(url, headers=self._headers(referer))
        try:
            with self.opener.open(request, timeout=20) as response:
                content_type = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(content_type, errors="ignore")
        except Exception as exc:
            raise RuntimeError(f"广州图书馆数据抓取失败：{exc}") from exc

    def fetch_json(self, url, referer=None):
        return json.loads(self.fetch_text(url, referer=referer))


def build_lookup_result(titles, libcode, options):
    libraries = get_libraries()
    selected_library = next(
        (item for item in libraries if item["libcode"] == libcode),
        {"libcode": libcode, "simpleName": libcode, "name": libcode},
    )

    query_terms = list(titles)
    query_mode = "title"
    if not query_terms and options.get("author"):
        query_terms = [options["author"]]
        query_mode = "author-only"

    items = []
    missing = []
    seen_bookrecnos = set()

    for index, query in enumerate(query_terms):
        matched_items = search_books(
            query,
            libcode,
            index,
            options,
            search_way="author" if query_mode == "author-only" else "title",
        )
        fresh_items = []
        for item in matched_items:
            bookrecno = str(item.get("bookrecno", "")).strip()
            if bookrecno and bookrecno in seen_bookrecnos:
                continue
            if bookrecno:
                seen_bookrecnos.add(bookrecno)
            fresh_items.append(item)

        if not fresh_items:
            missing.append(query)
            continue
        items.extend(fresh_items)

    items.sort(key=compare_item_key)

    return {
        "queryCount": len(query_terms),
        "queryMode": query_mode,
        "selectedLibrary": selected_library,
        "queryOptions": {
            "author": options.get("author", ""),
            "fuzzy": bool(options.get("fuzzy")),
        },
        "items": items,
        "missing": missing,
        "totalLoanableCount": sum(item["totalLoanableCount"] for item in items),
        "totalHoldingCount": sum(len(item["holdings"]) for item in items),
        "meta": {
            "catalogBaseUrl": f"{CATALOG_BASE}/index",
            "generatedAt": datetime.now().strftime("%Y/%-m/%-d %H:%M:%S"),
            "dataSource": "广州图书馆联合目录 OPAC",
        },
    }


def search_books(query, libcode, query_index, options, search_way="title"):
    session = CatalogSession()
    candidates = fetch_candidates(query, libcode, options, session, search_way=search_way)
    if not candidates:
        return []

    ranked_candidates = rank_candidates(query, candidates, options, search_way=search_way)
    if not ranked_candidates:
        return []

    return_multiple = search_way == "author" or bool(options.get("fuzzy"))
    max_results = determine_candidate_limit(options, search_way)
    results = []
    for entry in ranked_candidates[:max_results]:
        if return_multiple and not is_strong_enough_match(entry, search_way):
            continue
        detail_payload = fetch_holding_detail(entry["candidate"]["bookrecno"], session)
        item = build_result_item(query, query_index, entry["candidate"], detail_payload, libcode)
        if item:
            results.append(item)
            if not return_multiple:
                break
    return results


def fetch_candidates(query, libcode, options, session, search_way="title"):
    candidates = []
    seen = set()

    def append_candidate(candidate):
        recno = str(candidate.get("bookrecno", "")).strip()
        if not recno or recno in seen:
            return
        seen.add(recno)
        candidates.append(candidate)

    if search_way == "title":
        for candidate in find_local_candidates(query, options):
            append_candidate(candidate)

    if search_way == "author":
        search_terms = [normalize_search_text(query)]
        row_limit = 60
        desired = 30
    else:
        search_terms = build_search_variants(query) if options.get("fuzzy") else [normalize_search_text(query)]
        row_limit = 80 if options.get("fuzzy") else 30
        desired = 36 if options.get("fuzzy") else 12

    for search_term in search_terms:
        if not search_term:
            continue
        cache_key = f"search::{libcode}::{search_way}::{search_term}"
        parsed_candidates = cache_get_json(cache_key, SEARCH_TTL)
        if parsed_candidates is None:
            search_url = (
                f"{CATALOG_BASE}/search?"
                f"q={urllib.parse.quote(search_term)}&searchWay={search_way}&rows={row_limit}"
                f"&searchSource=reader&curlibcode={urllib.parse.quote(libcode)}"
            )
            search_html = session.fetch_text(search_url, referer=f"{CATALOG_BASE}/index")
            parsed_candidates = parse_search_results(search_html)
            cache_set_json(cache_key, parsed_candidates)
            save_book_meta(parsed_candidates)
        else:
            save_book_meta(parsed_candidates)

        for candidate in parsed_candidates:
            append_candidate(candidate)

        if len(candidates) >= desired:
            break

    return candidates


def rank_candidates(query, candidates, options, search_way="title"):
    normalized_query = simplify_title(query)
    normalized_author = simplify_author(options.get("author", ""))
    ranked = []

    for index, candidate in enumerate(candidates):
        normalized_title = simplify_title(candidate.get("title", ""))
        candidate_author = simplify_author(candidate.get("author", ""))

        if search_way == "author":
            title_score = 0
            author_score = build_author_match_score(
                simplify_author(query),
                candidate_author,
            )
            if author_score < 0:
                continue
        elif options.get("fuzzy"):
            title_score = build_title_match_score(normalized_query, normalized_title)
        else:
            title_score = build_strict_title_score(normalized_query, normalized_title)

        if search_way != "author" and title_score < 0:
            continue

        if search_way != "author" and normalized_author:
            author_score = build_author_match_score(normalized_author, candidate_author)
            if author_score < 0:
                continue
        elif search_way != "author":
            author_score = 0

        ranked.append(
            {
                "candidate": candidate,
                "titleScore": title_score,
                "authorScore": author_score,
                "score": title_score + max(author_score, 0) - index * 0.25,
            }
        )

    ranked.sort(
        key=lambda item: (
            -item["titleScore"],
            -item["authorScore"],
            -item["score"],
        )
    )
    return ranked


def determine_candidate_limit(options, search_way):
    if search_way == "author":
        return 10
    if options.get("fuzzy"):
        return 12
    return 8


def is_strong_enough_match(entry, search_way):
    if search_way == "author":
        return entry["authorScore"] >= 100
    return entry["titleScore"] >= 70


def fetch_holding_detail(bookrecno, session):
    cache_key = f"holding::{bookrecno}"
    cached = cache_get_json(cache_key, HOLDING_TTL)
    if cached is not None:
        return cached

    detail_url = f"{CATALOG_BASE}/api/holding/{bookrecno}?limitLibcodes=&isCluster="
    payload = session.fetch_json(detail_url, referer=f"{CATALOG_BASE}/index")
    cache_set_json(cache_key, payload)
    return payload


def build_result_item(query, query_index, candidate, detail_payload, libcode):
    holdings = []
    for holding in detail_payload.get("holdingList", []):
        if holding.get("curlib") != libcode:
            continue
        item = build_detailed_holding(holding, detail_payload)
        if item["addressLabel"]:
            holdings.append(item)

    if not holdings:
        return None

    display_holdings = [finalize_holding_summary(item) for item in dedupe_holdings(holdings)]
    display_holdings = pick_display_holdings(display_holdings)
    display_holdings.sort(key=compare_holding_key)
    if not display_holdings:
        return None

    return {
        "query": query,
        "queryIndex": query_index,
        "title": candidate.get("title", ""),
        "author": candidate.get("author", ""),
        "publisher": candidate.get("publisher", ""),
        "bookrecno": candidate.get("bookrecno", ""),
        "totalLoanableCount": sum(item["loanableCount"] for item in display_holdings),
        "holdings": display_holdings,
        "primaryFloor": infer_primary_floor(display_holdings),
        "opacUrl": build_opac_book_url(
            candidate.get("bookrecno", ""),
            candidate.get("index", 1),
            query,
        ),
    }


def build_detailed_holding(holding, detail_payload):
    state_name = (
        detail_payload.get("holdStateMap", {})
        .get(str(holding.get("state")), {})
        .get("stateName", "")
    )
    cirtype_name = (
        detail_payload.get("pBCtypeMap", {})
        .get(str(holding.get("cirtype")), {})
        .get("name", "")
    )
    curlocal_name = resolve_location_name(detail_payload.get("localMap", {}), holding.get("curlocal"))
    formatted_address = format_shelf_address(holding)
    fallback_address = build_fallback_address({**holding, "curlocalName": curlocal_name})
    address_label = formatted_address or fallback_address or curlocal_name or ""
    floor_number = infer_floor_number({**holding, "curlocalName": curlocal_name}, formatted_address)
    area_code, column_number, rack_number = parse_address_parts(holding.get("shelfno", ""))
    is_loanable = is_loanable_holding(holding, cirtype_name)
    note = build_holding_note(state_name, cirtype_name, is_loanable)

    return {
        **holding,
        "copycount": 1,
        "totalCount": 1,
        "loanableCount": 1 if is_loanable else 0,
        "nonLoanableCount": 0 if is_loanable else 1,
        "hasNonCirculating": is_non_circulating_type(cirtype_name),
        "notes": [note] if note else [],
        "stateName": state_name,
        "cirtypeName": cirtype_name,
        "curlocalName": curlocal_name,
        "curlibName": resolve_library_name(detail_payload.get("libcodeMap", {}), holding.get("curlib")),
        "formattedAddress": formatted_address,
        "fallbackAddress": fallback_address,
        "addressLabel": address_label,
        "addressSummary": "",
        "floorNumber": floor_number,
        "areaCode": area_code,
        "columnNumber": column_number,
        "rackNumber": rack_number,
    }


def parse_search_results(html_text):
    segments = []
    marker = '<div class="bookmeta" bookrecno="'
    cursor = 0
    while True:
        start = html_text.find(marker, cursor)
        if start == -1:
            break
        end = html_text.find('<div class="expressServiceTab"', start)
        if end == -1:
            break
        segments.append(html_text[start:end])
        cursor = end

    results = []
    for segment in segments:
        recno_match = re.search(r'bookrecno="(\d+)"', segment)
        title_match = re.search(
            r'<a class="title-link"[\s\S]*?id="title_[^"]+">([\s\S]*?)</a>',
            segment,
        )
        author_match = re.search(r"<div>著者:\s*([\s\S]*?)</div>", segment)
        publisher_match = re.search(
            r'出版社:\s*<a class="publisher-link"[\s\S]*?>([\s\S]*?)</a>',
            segment,
        )
        row_number_match = re.search(r"javascript:bookDetail\(\d+,(\d+),0\);", segment)
        if not recno_match or not title_match:
            continue

        results.append(
            {
                "bookrecno": recno_match.group(1),
                "index": int(row_number_match.group(1)) if row_number_match else 1,
                "title": clean_text(title_match.group(1)),
                "author": clean_text(author_match.group(1) if author_match else ""),
                "publisher": clean_text(publisher_match.group(1) if publisher_match else ""),
                "summary": "",
            }
        )
    return results


def dedupe_holdings(holdings):
    grouped = {}
    for holding in holdings:
        key = holding["addressLabel"]
        if key not in grouped:
            grouped[key] = {
                **holding,
                "notes": list(holding.get("notes", [])),
            }
            continue

        current = grouped[key]
        current["copycount"] += int(holding.get("copycount", 0))
        current["totalCount"] += int(holding.get("totalCount", 0))
        current["loanableCount"] += int(holding.get("loanableCount", 0))
        current["nonLoanableCount"] += int(holding.get("nonLoanableCount", 0))
        current["hasNonCirculating"] = current["hasNonCirculating"] or holding.get("hasNonCirculating", False)
        current["notes"] = merge_unique_strings(current["notes"], holding.get("notes", []))
    return list(grouped.values())


def merge_unique_strings(current, extra):
    values = []
    seen = set()
    for item in list(current or []) + list(extra or []):
        if not item or item in seen:
            continue
        seen.add(item)
        values.append(item)
    return values


def finalize_holding_summary(holding):
    holding["addressSummary"] = build_holding_address_summary(holding)
    return holding


def build_holding_address_summary(holding):
    label = holding.get("addressLabel", "")
    if not label:
        return ""

    if 0 < holding["loanableCount"] < holding["totalCount"]:
        return f"{label}（可借{holding['loanableCount']}/共{holding['totalCount']}）"

    if holding["loanableCount"] == 0:
        if holding.get("hasNonCirculating"):
            return f"{label}（不外借）"
        if holding.get("notes"):
            return f"{label}（{' / '.join(holding['notes'])}）"

    return label


def build_holding_note(state_name, cirtype_name, is_loanable):
    if is_non_circulating_type(cirtype_name):
        return "不外借"
    if not is_loanable and state_name and state_name != "在馆":
        return state_name
    return ""


def is_loanable_holding(holding, cirtype_name):
    return int(holding.get("state", 0) or 0) == 2 and not is_non_circulating_type(cirtype_name)


def is_non_circulating_type(cirtype_name):
    return "不外借" in str(cirtype_name or "")


def resolve_location_name(local_map, code):
    if not code:
        return ""
    return local_map.get(str(code), str(code))


def resolve_library_name(libcode_map, code):
    if not code:
        return ""
    return libcode_map.get(str(code), str(code))


def pick_display_holdings(holdings):
    shelf_holdings = [holding for holding in holdings if is_shelf_holding(holding)]
    if shelf_holdings:
        return shelf_holdings

    internal_holdings = [holding for holding in holdings if is_internal_library_holding(holding)]
    if internal_holdings:
        return internal_holdings

    return holdings


def is_shelf_holding(holding):
    if holding.get("formattedAddress"):
        return True

    text = " ".join(
        part
        for part in [
            holding.get("fallbackAddress"),
            holding.get("addressLabel"),
            holding.get("shelfno"),
            holding.get("curlocalName"),
        ]
        if part
    )
    return bool(re.search(r"(?:\d+|[一二三四五六七八九十]+)楼", text)) and bool(
        re.search(r"(?:列|排|架|层|面)", text)
    )


def is_internal_library_holding(holding):
    text = " ".join(
        part
        for part in [
            holding.get("fallbackAddress"),
            holding.get("addressLabel"),
            holding.get("curlocalName"),
        ]
        if part
    )
    return bool(re.search(r"图书区|书库|借还|总馆|馆藏区|典藏|待处理|流通|阅览", text))


def compare_holding_key(holding):
    availability_rank = 0 if int(holding.get("loanableCount", 0) or 0) > 0 else 1
    floor = holding.get("floorNumber")
    floor_rank = floor if floor is not None else 10 ** 9
    return (
        availability_rank,
        -int(holding.get("loanableCount", 0) or 0),
        floor_rank,
        area_rank(holding.get("areaCode", "")),
        holding.get("columnNumber", 10 ** 9),
        holding.get("rackNumber", 10 ** 9),
        holding.get("addressLabel", ""),
    )


def compare_item_key(item):
    availability_rank = 0 if int(item.get("totalLoanableCount", 0) or 0) > 0 else 1
    floor = item.get("primaryFloor")
    floor_rank = floor if floor is not None else 10 ** 9
    return (
        availability_rank,
        -int(item.get("totalLoanableCount", 0) or 0),
        floor_rank,
        item.get("queryIndex", 0),
        item.get("title", ""),
    )


def infer_primary_floor(holdings):
    for holding in holdings:
        if holding.get("floorNumber") is not None:
            return holding["floorNumber"]
    return None


def format_shelf_address(holding):
    raw_shelfno = str(holding.get("shelfno", "") or "").strip()
    if not raw_shelfno:
        return ""

    match = re.match(r"^([NSEWC])(\d{2})(\d{4,5})([A-Z])(\d{2})(\d{2})$", raw_shelfno, re.I)
    if not match:
        match = re.match(r"^([NSEWC])(\d{2})(\d{4,5})([A-Z])(\d{2})$", raw_shelfno, re.I)
    if not match:
        return ""

    area, floor, column, face, rack = match.group(1), match.group(2), match.group(3), match.group(4), match.group(5)
    return f"{translate_area(area)}{int(floor)}楼{column}列{face.upper()}面{rack}架"


def build_fallback_address(holding):
    raw_shelfno = str(holding.get("shelfno", "") or "").strip()
    if not raw_shelfno:
        return holding.get("curlocalName", "") or ""

    if re.match(r"^U\d+", raw_shelfno, re.I):
        return f"{holding.get('curlocalName') or '智能书库'} {raw_shelfno}"

    if re.match(r"^\d+区$", raw_shelfno):
        return f"{holding.get('curlocalName') or '馆藏区'} {raw_shelfno}"

    return raw_shelfno


def infer_floor_number(holding, formatted_address):
    match = re.search(r"^[^\d]*(\d+)楼", str(formatted_address or ""))
    if match:
        return int(match.group(1))

    local_name = str(holding.get("curlocalName", "") or "")
    digit_match = re.search(r"(\d+)楼", local_name)
    if digit_match:
        return int(digit_match.group(1))

    chinese_match = re.search(r"([一二三四五六七八九十]+)楼", local_name)
    if chinese_match:
        return chinese_number_to_arabic(chinese_match.group(1))

    return None


def parse_address_parts(raw_shelfno):
    raw = str(raw_shelfno or "").strip()
    match = re.match(r"^([NSEWC])(\d{2})(\d{4,5})([A-Z])(\d{2})(\d{2})$", raw, re.I)
    if not match:
        match = re.match(r"^([NSEWC])(\d{2})(\d{4,5})([A-Z])(\d{2})$", raw, re.I)
    if not match:
        return "", 10 ** 9, 10 ** 9
    return match.group(1).upper(), int(match.group(3)), int(match.group(5))


def build_opac_book_url(bookrecno, index, search_keyword):
    inner = (
        f"q={urllib.parse.quote(search_keyword)}&searchType=standard&isFacet=false"
        f"&view=standard&searchWay=title&rows=1"
    )
    base = urllib.parse.quote(inner)
    return (
        f"{CATALOG_BASE}/book/{bookrecno}?index={int(index or 1)}"
        f"&globalSearchWay=title&base={base}"
        f"&searchKeyword={urllib.parse.quote(search_keyword)}"
    )


def get_libraries():
    cache_key = "libraries::tree"
    cached = cache_get_json(cache_key, LIBRARY_TTL)
    if cached is not None:
        return cached

    session = CatalogSession()
    request = urllib.request.Request(
        LIBRARY_TREE_URL,
        data=b"",
        headers=session._headers(referer=f"{CATALOG_BASE}/index"),
        method="POST",
    )
    try:
        with session.opener.open(request, timeout=20) as response:
            content_type = response.headers.get_content_charset() or "utf-8"
            payload = json.loads(response.read().decode(content_type, errors="ignore"))
    except Exception as exc:
        raise RuntimeError(f"无法加载广州图书馆馆别列表：{exc}") from exc

    libraries = [
        {
            "libcode": item.get("libcode", ""),
            "simpleName": item.get("simpleName") or item.get("name") or item.get("libcode", ""),
            "name": item.get("name") or item.get("simpleName") or item.get("libcode", ""),
            "plibcode": item.get("plibcode", ""),
        }
        for item in payload
    ]
    libraries.sort(key=lambda item: (library_rank(item["libcode"]), item["simpleName"]))
    cache_set_json(cache_key, libraries)
    return libraries


def get_recommendations():
    cache_key = "recommendations::public-list"
    cached = cache_get_json(cache_key, RECOMMENDATION_TTL)
    if cached is not None:
        return cached

    session = CatalogSession()
    starts = list(range(0, RECOMMENDATION_TOTAL, RECOMMENDATION_PAGE_SIZE))
    items = []
    seen_titles = set()
    for start in starts:
        url = (
            f"{RECOMMENDATION_SOURCE_URL}?start={start}&sort=seq&playable=0&sub_type="
        )
        html_text = session.fetch_text(url, referer="https://www.douban.com/")
        matches = re.findall(
            r'<div class="title">\s*<a [^>]*>([\s\S]*?)</a>[\s\S]*?<div class="abstract">([\s\S]*?)</div>',
            html_text,
        )
        for title_raw, abstract_raw in matches:
            title = clean_text(title_raw)
            if not title or title in seen_titles:
                continue
            abstract = clean_text(abstract_raw)
            author_match = re.search(r"作者:\s*(.+?)(?:\s+出版社:|$)", abstract)
            seen_titles.add(title)
            items.append(
                {
                    "title": title,
                    "author": author_match.group(1).strip() if author_match else "",
                }
            )
    cache_set_json(cache_key, items)
    return items


def library_rank(libcode):
    ranking = {
        "GT": 1,
        "GS": 2,
        "YT": 3,
        "HZQ": 4,
        "LW": 5,
        "TH": 6,
        "BY": 7,
        "HP": 8,
        "PY": 9,
        "HD": 10,
        "NS": 11,
        "ZC": 12,
        "CH": 13,
    }
    return ranking.get(libcode, 99)


def translate_area(area_code):
    mapping = {"C": "中", "N": "北", "S": "南", "E": "东", "W": "西"}
    return mapping.get(str(area_code).upper(), str(area_code).upper())


def area_rank(area_code):
    mapping = {"N": 1, "C": 2, "E": 3, "S": 4, "W": 5}
    return mapping.get(str(area_code or "").upper(), 9)


def chinese_number_to_arabic(value):
    mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + mapping.get(value[1], 0)
    if value.endswith("十"):
        return mapping.get(value[0], 0) * 10
    if "十" in value:
        left, right = value.split("十", 1)
        return mapping.get(left, 0) * 10 + mapping.get(right, 0)
    return mapping.get(value)


def normalize_search_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def simplify_title(text):
    value = re.sub(r"（[^）]*）", "", str(text or ""))
    value = re.sub(r"\([^)]*\)", "", value)
    return "".join(char.lower() for char in value if char.isalnum())


def simplify_author(text):
    return "".join(char.lower() for char in str(text or "") if char.isalnum())


def build_search_variants(query):
    raw = str(query or "").strip()
    normalized = normalize_search_text(raw)
    latin_parts = re.findall(r"[a-z0-9+#.]+", raw, re.I)
    han_parts = re.findall(r"[\u4e00-\u9fff]+", raw)
    joined_han = "".join(han_parts)
    variants = []
    for item in [raw, normalized]:
        if item and item not in variants:
            variants.append(item)
    if latin_parts:
        joined = " ".join(latin_parts)
        if joined not in variants:
            variants.append(joined)
        if latin_parts[0] not in variants:
            variants.append(latin_parts[0])
    if len(joined_han) >= 3:
        if joined_han not in variants:
            variants.append(joined_han)
        short_han = joined_han[: min(6, len(joined_han))]
        if short_han not in variants:
            variants.append(short_han)
    return variants


def build_strict_title_score(normalized_query, normalized_title):
    if not normalized_query or not normalized_title:
        return -1
    if normalized_title == normalized_query:
        return 320
    if is_exactish_match(normalized_query, normalized_title):
        return 260
    return -1


def is_exactish_match(query, title):
    if title == query:
        return True
    if not title.startswith(query):
        return False
    remainder = title[len(query):]
    return not remainder or bool(re.match(r"^[0-9a-z版卷册集上下修订增订精藏译注校注]", remainder, re.I))


def build_author_match_score(normalized_query, normalized_author):
    if not normalized_query:
        return 0
    if not normalized_author:
        return -1
    if normalized_author == normalized_query:
        return 200
    if normalized_query in normalized_author or normalized_author in normalized_query:
        return 140
    coverage = shared_character_coverage(normalized_query, normalized_author)
    return coverage * 120 if coverage >= 0.8 else -1


def build_title_match_score(normalized_query, normalized_title):
    if not normalized_query or not normalized_title:
        return -1
    if normalized_title == normalized_query:
        return 260
    if is_exactish_match(normalized_query, normalized_title):
        return 220
    if normalized_query in normalized_title:
        return 220 - max(0, len(normalized_title) - len(normalized_query)) * 6
    if normalized_title in normalized_query:
        return 150 - max(0, len(normalized_query) - len(normalized_title)) * 2

    query_han = extract_han_text(normalized_query)
    title_han = extract_han_text(normalized_title)
    query_latin = extract_latin_text(normalized_query)
    title_latin = extract_latin_text(normalized_title)
    han_score = build_segment_match_score(query_han, title_han)
    latin_score = build_segment_match_score(query_latin, title_latin)

    if query_han and han_score < 0:
        return -1
    if query_latin and latin_score < 0:
        return -1

    longest_common = longest_common_substring_length(normalized_query, normalized_title)
    subsequence_length = longest_common_subsequence_length(normalized_query, normalized_title)
    prefix_length = common_prefix_length(normalized_query, normalized_title)
    overlap_ratio = shared_character_ratio(normalized_query, normalized_title)
    substring_ratio = longest_common / max(len(normalized_query), len(normalized_title))
    query_cover_ratio = longest_common / len(normalized_query)
    subsequence_ratio = subsequence_length / len(normalized_query)

    score = (
        overlap_ratio * 80
        + substring_ratio * 60
        + query_cover_ratio * 60
        + subsequence_ratio * 100
        + prefix_length * 8
        + max(han_score, 0)
        + max(latin_score, 0)
    )

    if len(normalized_query) <= 2:
        if normalized_query in normalized_title:
            return max(score, 120 - max(0, len(normalized_title) - len(normalized_query)) * 2)
        return -1

    if (
        subsequence_ratio >= 0.75
        or query_cover_ratio >= 0.5
        or overlap_ratio >= 0.55
        or (prefix_length >= 2 and longest_common >= 2)
    ):
        return score
    return -1


def build_segment_match_score(query_segment, title_segment):
    if not query_segment:
        return 0
    if not title_segment:
        return -1
    if query_segment == title_segment:
        return 180
    if query_segment in title_segment:
        return 170 - max(0, len(title_segment) - len(query_segment)) * 6

    subsequence_length = longest_common_subsequence_length(query_segment, title_segment)
    substring_length = longest_common_substring_length(query_segment, title_segment)
    query_coverage = shared_character_coverage(query_segment, title_segment)
    subsequence_coverage = subsequence_length / len(query_segment)
    substring_coverage = substring_length / len(query_segment)
    score = query_coverage * 110 + subsequence_coverage * 120 + substring_coverage * 70

    if len(query_segment) <= 2:
        if query_segment in title_segment:
            return max(score, 110 - max(0, len(title_segment) - len(query_segment)) * 2)
        return score if query_coverage == 1 and subsequence_coverage == 1 else -1
    if query_coverage >= 0.8 or subsequence_coverage >= 0.75 or substring_coverage >= 0.6:
        return score
    return -1


def longest_common_substring_length(left, right):
    if not left or not right:
        return 0
    rows = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    max_length = 0
    for row in range(1, len(left) + 1):
        for col in range(1, len(right) + 1):
            if left[row - 1] != right[col - 1]:
                continue
            rows[row][col] = rows[row - 1][col - 1] + 1
            max_length = max(max_length, rows[row][col])
    return max_length


def longest_common_subsequence_length(left, right):
    if not left or not right:
        return 0
    rows = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for row in range(1, len(left) + 1):
        for col in range(1, len(right) + 1):
            if left[row - 1] == right[col - 1]:
                rows[row][col] = rows[row - 1][col - 1] + 1
            else:
                rows[row][col] = max(rows[row - 1][col], rows[row][col - 1])
    return rows[-1][-1]


def common_prefix_length(left, right):
    length = 0
    limit = min(len(left), len(right))
    while length < limit and left[length] == right[length]:
        length += 1
    return length


def shared_character_ratio(left, right):
    return count_shared_characters(left, right) / max(len(left), len(right))


def shared_character_coverage(left, right):
    return count_shared_characters(left, right) / len(left)


def count_shared_characters(left, right):
    counter = {}
    for char in left:
        counter[char] = counter.get(char, 0) + 1
    shared = 0
    for char in right:
        if counter.get(char, 0) <= 0:
            continue
        shared += 1
        counter[char] -= 1
    return shared


def extract_han_text(text):
    return "".join(char for char in str(text or "") if "\u4e00" <= char <= "\u9fff")


def extract_latin_text(text):
    return "".join(char for char in str(text or "") if char.isascii() and char.isalnum())


def clean_text(text):
    value = re.sub(r"<[^>]+>", "", str(text or ""))
    value = html.unescape(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


class AppHandler(BaseHTTPRequestHandler):
    server_version = "GzLibCatalogProxy/1.0"

    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/libraries":
                return self.respond_json({"libraries": get_libraries()})

            if parsed.path == "/api/recommendations":
                return self.respond_json({"items": get_recommendations()})

            if parsed.path in ("/", "/index.html"):
                return self.serve_static(ROOT / "index.html")

            if parsed.path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
                return

            safe_path = (ROOT / parsed.path.lstrip("/")).resolve()
            return self.serve_static(safe_path)
        except Exception as exc:
            return self.respond_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/api/plan-route":
                return self.respond_json({"error": "未找到请求资源。"}, status=HTTPStatus.NOT_FOUND)

            content_length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            body = json.loads(raw_body.decode("utf-8"))

            titles = [str(item).strip() for item in body.get("titles", []) if str(item).strip()]
            author = str(body.get("author") or "").strip()
            if not titles and not author:
                return self.respond_json({"error": "请输入至少一本书名或作者。"}, status=HTTPStatus.BAD_REQUEST)

            payload = build_lookup_result(
                titles,
                str(body.get("libcode") or "GT").strip() or "GT",
                {
                    "author": author,
                    "fuzzy": bool(body.get("fuzzy")),
                },
            )
            return self.respond_json(payload)
        except json.JSONDecodeError:
            return self.respond_json({"error": "请求体不是有效的 JSON。"}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            return self.respond_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def serve_static(self, file_path):
        if not str(file_path).startswith(str(ROOT)):
            return self.respond_json({"error": "禁止访问该文件。"}, status=HTTPStatus.FORBIDDEN)

        if not file_path.exists() or not file_path.is_file():
            return self.respond_json({"error": "文件不存在。"}, status=HTTPStatus.NOT_FOUND)

        content = file_path.read_bytes()
        mime_type = MIME_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def respond_json(self, payload, status=HTTPStatus.OK):
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def log_message(self, format_string, *args):
        return


def main():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Library route server running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
