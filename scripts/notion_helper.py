import logging
import os
import re
import time

from notion_client import Client
from retrying import retry
from datetime import timedelta

from utils import (
    format_date,
    get_date,
    get_first_and_last_day_of_month,
    get_first_and_last_day_of_week,
    get_first_and_last_day_of_year,
    get_icon,
    get_number,
    get_relation,
    get_rich_text,
    get_title,
    timestamp_to_date,
    get_property_value,
)

TAG_ICON_URL = "https://www.notion.so/icons/tag_gray.svg"
USER_ICON_URL = "https://www.notion.so/icons/user-circle-filled_gray.svg"
TARGET_ICON_URL = "https://www.notion.so/icons/target_red.svg"
BOOKMARK_ICON_URL = "https://www.notion.so/icons/bookmark_gray.svg"

class NotionHelper:
    # ... class implementation ...

notion_helper = NotionHelper(type="book")

book_properties_type_dict = {
    # Define your book properties type dictionary here
}

def get_icon(icon_url):
    # Define your get_icon function here
    return {"type": "external", "external": {"url": icon_url}}
