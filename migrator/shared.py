import re
from re import Pattern
import logging
from typing import Any, IO
from tempfile import TemporaryFile
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel

LOG = logging.getLogger(__name__)

MEDIA_REGEX_PRETTY = re.compile('^/_media/(.*)')
MEDIA_REGEX = re.compile('^/lib/exe/fetch.php\\?(.*)')
PAGE_REGEX_PRETTY = re.compile('^/(.*)')
PAGE_REGEX = re.compile('^/doku.php\\?id=(.*)')


class PageAndRevision(BaseModel):
    page_id: str
    revision: int

def download_file(url: str) -> IO:
    filename = url.split("/")[-1]
    tempfile = TemporaryFile()
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=8192):
            tempfile.write(chunk)
    tempfile.seek(0)
    return tempfile


def extract_media_id(e: Tag, attr_name: str, regex: Pattern[str]) -> str | None:
    if regex == MEDIA_REGEX_PRETTY:
        return extract(e, attr_name, regex)
    attr_value = e[attr_name]
    if not isinstance(attr_value, str):
        LOG.debug(f"Attribute {attr_name} of {e} is not a str but {attr_value}")
        return None
    relative_url = urlparse(attr_value)
    media_parameters = parse_qs(relative_url.query).get('media')
    return media_parameters[0] if media_parameters and len(media_parameters) > 0 else None

def extract(e: Tag, attr_name: str, regex: Pattern[str]) -> str | None:
    attr_value = e[attr_name]
    if not isinstance(attr_value, str):
        LOG.debug(f"Attribute {attr_name} of {e} is not a str but {attr_value}")
        return None
    m = regex.match(attr_value)
    if not m:
        LOG.debug(f"Expected regex {regex} to match {attr_value}")
        return None
    return m[1]

def find_all_tags(soup: BeautifulSoup, name: str, **kwargs: Any) -> list[Tag]:
    return [
        t 
        for t in soup.find_all(name, **kwargs)
        if isinstance(t, Tag)
    ]