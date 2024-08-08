import pendulum
import utils
from notion_helper import notion_helper, book_properties_type_dict, get_icon

# 配置豆瓣账号和书籍状态
douban_name = "your_douban_account"
book_status = {
    "collect": "读过",
    "do": "在读",
    "wish": "想读"
}
rating = {
    "1": "很差",
    "2": "较差",
    "3": "还行",
    "4": "推荐",
    "5": "力荐"
}
TAG_ICON_URL = "tag_icon_url"
USER_ICON_URL = "user_icon_url"

def fetch_subjects(douban_name, category, status):
    # 假设这个函数从豆瓣API获取数据并返回
    return []

def insert_book():
    notion_books = notion_helper.query_all(database_id=notion_helper.book_database_id)
    notion_book_dict = {}
    for i in notion_books:
        book = {}
        for key, value in i.get("properties").items():
            book[key] = utils.get_property_value(value)
        notion_book_dict[book.get("豆瓣链接")] = {
            "短评": book.get("短评"),
            "状态": book.get("状态"),
            "日期": book.get("日期"),
            "评分": book.get("评分"),
            "page_id": i.get("id")
        }
    print(f"Notion books count: {len(notion_book_dict)}")
    results = []
    for i in book_status.keys():
        results.extend(fetch_subjects(douban_name, "book", i))
    for result in results:
        book = {}
        subject = result.get("subject")
        book["书名"] = subject.get("title")
        create_time = result.get("create_time")
        create_time = pendulum.parse(create_time, tz=utils.tz)
        create_time = create_time.replace(second=0)
        book["豆瓣链接"] = subject.get("url")
        book["状态"] = book_status.get(result.get("status"))
        if result.get("rating"):
            book["评分"] = rating.get(result.get("rating").get("value"))
        if result.get("comment"):
            book["短评"] = result.get("comment")
        if notion_book_dict.get(book.get("豆瓣链接")):
            notion_book = notion_book_dict.get(book.get("豆瓣链接"))
            start_date = None
            end_date = None
            if book["状态"] == "在读":
                start_date = create_time.to_iso8601_string()
            elif book["状态"] == "读过":
                end_date = create_time.to_iso8601_string()
                start_date = notion_book.get("日期").get("start") if notion_book.get("日期") else None

            if (
                notion_book.get("日期") != {"start": start_date, "end": end_date}
                or notion_book.get("短评") != book.get("短评")
                or notion_book.get("状态") != book.get("状态")
                or notion_book.get("评分") != book.get("评分")
            ):
                properties = utils.get_properties(book, book_properties_type_dict)
                properties["日期"] = {
                    "date": {
                        "start": start_date,
                        "end": end_date
                    }
                }
                print(f"Updating page with ID {notion_book.get('page_id')}, properties: {properties}")
                notion_helper.update_page(
                    page_id=notion_book.get("page_id"),
                    properties=properties
                )
        else:
            print(f"Inserting new book: {book.get('书名')}")
            cover = subject.get("pic").get("large")
            press = []
            if "press" in subject:
                press.extend(subject["press"].split(","))
            book["出版社"] = press
            book["类型"] = subject.get("type")
            if result.get("tags"):
                book["分类"] = [
                    notion_helper.get_relation_id(
                        x, notion_helper.category_database_id, TAG_ICON_URL
                    )
                    for x in result.get("tags")
                ]
            if subject.get("author"):
                book["作者"] = [
                    notion_helper.get_relation_id(
                        x, notion_helper.author_database_id, USER_ICON_URL
                    )
                    for x in subject.get("author")[0:100]
                ]
            properties = utils.get_properties(book, book_properties_type_dict)
            properties["日期"] = {
                "date": {
                    "start": create_time.to_iso8601_string() if book["状态"] == "在读" else None,
                    "end": create_time.to_iso8601_string() if book["状态"] == "读过" else None
                }
            }
            parent = {
                "database_id": notion_helper.book_database_id,
                "type": "database_id",
            }
            print(f"Creating new page, properties: {properties}")
            notion_helper.create_page(
                parent=parent, properties=properties, icon=get_icon(cover)
            )

def get_properties(data, properties_type_dict):
    print(f"Input data: {data}")
    properties = {}
    for key, value in data.items():
        if key in properties_type_dict:
            property_type = properties_type_dict[key]
            if property_type == "date":
                if value:
                    properties[key] = {"date": {"start": value, "end": None}}
                else:
                    properties[key] = {"date": {"start": None, "end": None}}
            elif property_type == "rich_text":
                properties[key] = {"rich_text": [{"text": {"content": value}}]}
            else:
                properties[key] = {property_type: value}
    print(f"Processed properties: {properties}")
    return properties

if __name__ == "__main__":
    insert_book()

