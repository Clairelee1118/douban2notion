import argparse
import time

from douban2notion.notion_helper import NotionHelper


def get_external_cover(page):
    files = page.get("properties", {}).get("封面", {}).get("files", [])
    if not files:
        return None
    cover = files[0]
    if cover.get("type") != "external":
        return None
    return cover.get("external", {}).get("url")


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

        cover_url = get_external_cover(page)
        if not cover_url:
            continue

        title_property = "电影名" if type_ == "movie" else "书名"
        title_parts = (
            page.get("properties", {})
            .get(title_property, {})
            .get("title", [])
        )
        title = title_parts[0].get("plain_text", "") if title_parts else ""

        try:
            notion_helper.repair_page_cover(page["id"], cover_url)
            repaired += 1
            print(f"repaired {repaired}: {title}")
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
