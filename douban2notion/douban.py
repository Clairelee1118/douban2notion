import argparse
import os
import requests
import pendulum
from bs4 import BeautifulSoup
from retrying import retry
from dotenv import load_dotenv

from douban2notion.notion_helper import NotionHelper
from douban2notion import utils
from douban2notion.utils import get_icon
from douban2notion.config import (
    movie_properties_type_dict,
    book_properties_type_dict,
    TAG_ICON_URL,
    USER_ICON_URL,
)

load_dotenv()

DOUBAN_API_HOST = os.getenv("DOUBAN_API_HOST", "frodo.douban.com")
DOUBAN_API_KEY = os.getenv("DOUBAN_API_KEY", "0ac44ae016490db2204ce0a042db2916")
AUTH_TOKEN = os.getenv("AUTH_TOKEN")

headers = {
    "host": DOUBAN_API_HOST,
    "authorization": f"Bearer {AUTH_TOKEN}" if AUTH_TOKEN else "",
    "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_3 like Mac OS X)",
    "referer": "https://servicewechat.com/wx2f9b06c1de1ccfca/84/page-frame.html",
}

rating = {
    1: "⭐️",
    2: "⭐️⭐️",
    3: "⭐️⭐️⭐️",
    4: "⭐️⭐️⭐️⭐️",
    5: "⭐️⭐️⭐️⭐️⭐️",
}

movie_status = {"mark": "想看", "doing": "在看", "done": "看过"}
book_status = {"mark": "想读", "doing": "在读", "done": "读过"}


def handle_cover(url):
    if not url:
        return None
    try:
        return utils.upload_cover(url)
    except Exception as e:
        print(f"❌ 封面上传失败: {url}, {e}")
        return None


@retry(stop_max_attempt_number=3, wait_fixed=5000)
def fetch_subjects(user, type_, status):
    offset = 0
    results = []
    url = f"https://{DOUBAN_API_HOST}/api/v2/user/{user}/interests"

    while True:
        params = {
            "type": type_,
            "count": 50,
            "status": status,
            "start": offset,
            "apiKey": DOUBAN_API_KEY,
        }
        r = requests.get(url, headers=headers, params=params)
        if not r.ok:
            break

        data = r.json().get("interests", [])
        if not data:
            break

        results.extend(data)
        offset += 50

    return results


def get_imdb(link):
    r = requests.get(link, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.content, "html.parser")
    info = soup.find(id="info")
    if not info:
        return None
    for span in info.find_all("span", class_="pl"):
        if span.string == "IMDb:":
            return span.next_sibling.strip()
    return None


def insert_movie(douban_name, notion_helper):
    notion_movies = notion_helper.query_all(notion_helper.movie_database_id)
    notion_map = {
        utils.get_property_value(i["properties"]["豆瓣链接"]): i["id"]
        for i in notion_movies
    }

    results = []
    for s in movie_status:
        results.extend(fetch_subjects(douban_name, "movie", s))

    for r in results:
        subject = r["subject"]
        movie = {}

        movie["电影名"] = subject["title"]
        movie["豆瓣链接"] = subject["url"]
        movie["状态"] = movie_status[r["status"]]

        create_time = pendulum.parse(r["create_time"], tz=utils.tz).replace(second=0)
        movie["日期"] = create_time.int_timestamp

        if r.get("rating"):
            movie["评分"] = rating[r["rating"]["value"]]
        if r.get("comment"):
            movie["短评"] = r["comment"]

        cover_url = subject.get("pic", {}).get("normal")
        cover = handle_cover(cover_url)
        movie["封面"] = cover

        if subject.get("genres"):
            movie["分类"] = [
                notion_helper.get_relation_id(x, notion_helper.category_database_id, TAG_ICON_URL)
                for x in subject["genres"]
            ]

        if subject.get("actors"):
            movie["演员"] = [
                notion_helper.get_relation_id(x["name"], notion_helper.actor_database_id, USER_ICON_URL)
                for x in subject["actors"][:5]
            ]

        if subject.get("directors"):
            movie["导演"] = [
                notion_helper.get_relation_id(x["name"], notion_helper.director_database_id, USER_ICON_URL)
                for x in subject["directors"][:5]
            ]

        movie["IMDB"] = get_imdb(movie["豆瓣链接"])

        properties = utils.get_properties(movie, movie_properties_type_dict)
        notion_helper.get_date_relation(properties, create_time)

        if movie["豆瓣链接"] in notion_map:
            notion_helper.update_page(
                page_id=notion_map[movie["豆瓣链接"]],
                properties=properties,
            )
        else:
            notion_helper.create_page(
                parent={"database_id": notion_helper.movie_database_id},
                properties=properties,
                icon=get_icon(cover) if cover else None,
            )


def insert_book(douban_name, notion_helper):
    notion_books = notion_helper.query_all(notion_helper.book_database_id)
    notion_map = {
        utils.get_property_value(i["properties"]["豆瓣链接"]): i["id"]
        for i in notion_books
    }

    results = []
    for s in book_status:
        results.extend(fetch_subjects(douban_name, "book", s))

    for r in results:
        subject = r["subject"]
        book = {}

        book["书名"] = subject["title"]
        book["豆瓣链接"] = subject["url"]
        book["状态"] = book_status[r["status"]]

        create_time = pendulum.parse(r["create_time"], tz=utils.tz).replace(second=0)
        book["日期"] = create_time.int_timestamp

        if r.get("rating"):
            book["评分"] = rating[r["rating"]["value"]]
        if r.get("comment"):
            book["短评"] = r["comment"]

        cover_url = subject.get("pic", {}).get("large")
        cover = handle_cover(cover_url)
        book["封面"] = cover

        if subject.get("intro"):
            book["简介"] = subject["intro"]

        if subject.get("author"):
            book["作者"] = [
                notion_helper.get_relation_id(x, notion_helper.author_database_id, USER_ICON_URL)
                for x in subject["author"]
            ]

        properties = utils.get_properties(book, book_properties_type_dict)
        notion_helper.get_date_relation(properties, create_time)

        if book["豆瓣链接"] in notion_map:
            notion_helper.update_page(
                page_id=notion_map[book["豆瓣链接"]],
                properties=properties,
            )
        else:
            notion_helper.create_page(
                parent={"database_id": notion_helper.book_database_id},
                properties=properties,
                icon=get_icon(cover) if cover else None,
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("type")
    args = parser.parse_args()

    notion_helper = NotionHelper(args.type)
    douban_name = os.getenv("DOUBAN_NAME")

    if args.type == "movie":
        insert_movie(douban_name, notion_helper)
    else:
        insert_book(douban_name, notion_helper)


if __name__ == "__main__":
    main()
