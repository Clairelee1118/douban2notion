import argparse
import json
import re
import time

import requests
from bs4 import BeautifulSoup

from douban2notion.notion_helper import NotionHelper


DOUBAN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.douban.com/",
}


def get_cover_state(page):
    files = page.get("properties", {}).get("封面", {}).get("files", [])
    if not files:
        return "missing", None
    cover = files[0]
    if cover.get("type") != "external":
        return "internal", None
    return "external", cover.get("external", {}).get("url")


def get_url_property(page, name):
    return page.get("properties", {}).get(name, {}).get("url")


def get_text_property(page, name):
    prop = page.get("properties", {}).get(name, {})
    values = prop.get("rich_text") or prop.get("title") or []
    if values:
        return values[0].get("plain_text", "").strip()

    formula = prop.get("formula") or {}
    value = formula.get("string")
    if value is None:
        value = prop.get("url")
    return str(value).strip() if value is not None else ""


def refresh_wikidata_cover(imdb_id, subject_url):
    identifiers = []
    if imdb_id and re.fullmatch(r"tt\\d+", imdb_id):
        identifiers.append(f'{{ ?item wdt:P345 "{imdb_id}" . }}')

    subject_match = re.search(r"/subject/(\\d+)", subject_url or "")
    if subject_match:
        identifiers.append(
            f'{{ ?item wdt:P4529 "{subject_match.group(1)}" . }}'
        )

    if not identifiers:
        raise ValueError("No valid IMDb or Douban ID is available")

    query = (
        "SELECT ?image WHERE { "
        + " UNION ".join(identifiers)
        + " ?item wdt:P18 ?image . } LIMIT 1"
    )
    response = requests.get(
        "https://query.wikidata.org/sparql",
        params={"query": query, "format": "json"},
        headers={"User-Agent": "douban2notion-cover-repair/1.0"},
        timeout=30,
    )
    response.raise_for_status()
    bindings = response.json().get("results", {}).get("bindings", [])
    if not bindings:
        raise ValueError(f"No Wikidata poster is available for {imdb_id}")
    return bindings[0]["image"]["value"]


def extract_cover_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    for selector, attribute in (
        ('meta[property="og:image"]', "content"),
        ('meta[name="twitter:image"]', "content"),
        ("#mainpic img", "src"),
        (".subject-card img", "src"),
    ):
        node = soup.select_one(selector)
        if node and node.get(attribute):
            return node[attribute]

    for node in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.string or "")
        except (TypeError, json.JSONDecodeError):
            continue
        records = data if isinstance(data, list) else [data]
        for record in records:
            if isinstance(record, dict) and record.get("image"):
                image = record["image"]
                if isinstance(image, list):
                    image = image[0]
                if isinstance(image, dict):
                    image = image.get("url")
                if isinstance(image, str):
                    return image
    return None


def refresh_douban_cover(subject_url):
    if not subject_url:
        raise ValueError("No Douban subject URL is available")

    subject_match = re.search(r"/subject/(\\d+)", subject_url)
    candidates = [subject_url]
    if subject_match:
        subject_id = subject_match.group(1)
        kind = "book" if "book.douban.com" in subject_url else "movie"
        candidates.extend(
            [
                f"https://m.douban.com/{kind}/subject/{subject_id}/",
                f"https://www.douban.com/doubanapp/dispatch?uri=/subject/{subject_id}/",
            ]
        )

    for candidate in candidates:
        try:
            response = requests.get(candidate, headers=DOUBAN_HEADERS, timeout=30)
            response.raise_for_status()
        except requests.RequestException:
            continue
        cover_url = extract_cover_from_html(response.text)
        if cover_url:
            return cover_url
    raise ValueError("No current cover was found on Douban desktop or mobile pages")


def repair_covers(type_, limit, statuses=None, shard_count=1, shard_index=0):
    notion_helper = NotionHelper(type_)
    database_id = (
        notion_helper.movie_database_id
        if type_ == "movie"
        else notion_helper.book_database_id
    )
    repaired = 0
    failed = 0

    if statuses:
        status_filter = {
            "or": [
                {"property": "状态", "status": {"equals": status}}
                for status in statuses
            ]
        }
        pages = notion_helper.query_all_by_book(
            database_id=database_id,
            filter=status_filter,
        )
    else:
        pages = notion_helper.query_all(database_id=database_id)

    for page in pages:
        page_number = int(page["id"].replace("-", ""), 16)
        if page_number % shard_count != shard_index:
            continue

        cover_state, cover_url = get_cover_state(page)
        if cover_state == "internal":
            continue

        title_property = "电影名" if type_ == "movie" else "书名"
        title_parts = (
            page.get("properties", {})
            .get(title_property, {})
            .get("title", [])
        )
        title = title_parts[0].get("plain_text", "") if title_parts else ""
        subject_url = get_url_property(page, "豆瓣链接")

        try:
            repaired_source = None
            source_errors = []

            if cover_url:
                try:
                    notion_helper.repair_page_cover(page["id"], cover_url)
                    repaired_source = "existing Douban URL"
                except Exception as exc:
                    source_errors.append(f"existing URL: {exc}")

            if not repaired_source:
                try:
                    refreshed_url = refresh_douban_cover(subject_url)
                    notion_helper.repair_page_cover(page["id"], refreshed_url)
                    repaired_source = "current Douban page"
                except Exception as exc:
                    source_errors.append(f"Douban page: {exc}")

            if not repaired_source and type_ == "movie":
                imdb_id = get_text_property(page, "IMDB")
                try:
                    wikidata_url = refresh_wikidata_cover(imdb_id, subject_url)
                    notion_helper.repair_page_cover(page["id"], wikidata_url)
                    repaired_source = f"Wikidata via {imdb_id}"
                except Exception as exc:
                    source_errors.append(f"Wikidata: {exc}")

            if not repaired_source:
                raise ValueError("; ".join(source_errors))

            repaired += 1
            print(f"repaired {repaired}: {title} ({repaired_source})")
        except Exception as exc:
            failed += 1
            print(f"failed: {title}: {type(exc).__name__}: {exc}")

        if repaired >= limit:
            break
        time.sleep(0.4)

    print(f"finished: repaired={repaired}, failed={failed}")
    if repaired == 0 and failed:
        raise RuntimeError("No covers were repaired")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate external Douban covers to Notion-managed files."
    )
    parser.add_argument("type", choices=("movie", "book"))
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Maximum number of covers to repair in this run.",
    )
    parser.add_argument(
        "--status",
        action="append",
        dest="statuses",
        help="Only repair this Notion status; repeat for multiple statuses.",
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=1,
        help="Split matching pages into this many stable ID-based shards.",
    )
    parser.add_argument(
        "--shard-index",
        type=int,
        default=0,
        help="Zero-based shard to process.",
    )
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 500:
        parser.error("--limit must be between 1 and 500")
    if args.shard_count < 1:
        parser.error("--shard-count must be at least 1")
    if args.shard_index < 0 or args.shard_index >= args.shard_count:
        parser.error("--shard-index must be within the shard range")
    repair_covers(
        args.type,
        args.limit,
        args.statuses,
        args.shard_count,
        args.shard_index,
    )


if __name__ == "__main__":
    main()
