from typing import TextIO, NamedTuple, IO, Iterable, Any
import logging
from tempfile import TemporaryFile
import re
from re import Pattern

from pydantic import BaseModel
from bs4 import BeautifulSoup, PageElement, Tag, NavigableString
import requests

from migrator.dokuwiki import DokuWiki, PageInfo
from .api import Bookstack, Book, Chapter, Page

LOG = logging.getLogger(__name__)

MEDIA_REGEX_PRETTY = re.compile('^/_media/(.*)')
MEDIA_REGEX = re.compile('^/lib/exe/fetch.php?media=(.*)')
PAGE_REGEX_PRETTY = re.compile('^/(.*)')
PAGE_REGEX = re.compile('^/doku.php?id=(.*)')

class PagePath(NamedTuple):
    book_slug: str 
    chapter_slug: str | None
    page_slug: str

    def __str__(self) -> str:
        s = self.book_slug + '/'
        if self.chapter_slug:
            s += self.chapter_slug + '/'
        return s + self.page_slug

def map_page_id(page_id: str) -> PagePath | None:
    match page_id.split(":"):
        case [book_slug, chapter_slug, page_slug, *rest]:
            return PagePath(book_slug, chapter_slug, "-".join(page_slug, *rest))
        case [book_slug, page_slug]:
            return PagePath(book_slug, None, page_slug)
        case [page_slug]:
            return PagePath(page_slug, None, page_slug)
        case _:
            raise RuntimeError("Expected to be unreachable")

class PageAndRevision(BaseModel):
    page_id: str
    revision: int

class MigratedPage(BaseModel):
    page: Page
    latest_revision: int

class MigrationProgress(BaseModel):
    books: dict[str, Book] = {}
    chapters: dict[str, Chapter] = {}
    pages: dict[str, MigratedPage] = {}
    # map dokuwiki media id to bookstack path
    media: dict[str, str] = {}

def download_file(url: str) -> IO:
    filename = url.split("/")[-1]
    tempfile = TemporaryFile()
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=8192):
            tempfile.write(chunk)
    tempfile.seek(0)
    return tempfile

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

class Migrator:
    progress: MigrationProgress
    dokuwiki: DokuWiki
    bookstack: Bookstack
    only_ids: list[str]
    only_public: bool

    def __init__(self, dokuwiki: DokuWiki, bookstack: Bookstack, progress: MigrationProgress, only_ids: list[str] = [], only_public: bool = True) -> None:
        self.dokuwiki = dokuwiki
        self.bookstack = bookstack
        self.progress = progress
        self.only_ids = only_ids
        self.only_public = only_public

    def migrate_page_revision(self, page_id: str, page_revision: int) -> None:
        LOG.info(f"Trying to migrate page {page_id} revision {page_revision}")
        page_path = map_page_id(page_id)
        if not page_path:
            LOG.error(f"Unable to migrate page {page_id}, not enough components in the page path/id")
            return
        book_slug, chapter_slug, page_slug = page_path
        book = self.get_book_or_migrate(book_slug)
        chapter = self.get_chapter_or_migrate(book_slug, book.id, chapter_slug) if chapter_slug else None

        # check if we migrated this page before
        migrated_page = self.progress.pages.get(str(page_path))
        if migrated_page:
            # if we already migrated this page, assert that we try to create a newer revision
            if migrated_page.latest_revision >= page_revision:
                return LOG.info(f"Skip migration of {page_id} {page_revision}, already migrated")
            html = self.dokuwiki.get_page_html(page_id, page_revision)
            html = self.upload_and_patch_img_urls(html, migrated_page.page.id)
            html = self.patch_page_urls(html)
            self.bookstack.page_update(migrated_page.page.id, html=html)
            self.progress.pages[str(page_path)].latest_revision = page_revision
        else:
            page_history_infos = self.dokuwiki.get_page_history(page_id)
            revisions = sorted(info.revision for info in page_history_infos)
            # if we only have one revision, then we must pass 0 as revision to dokuwiki, otherwise it returns an error
            html = self.dokuwiki.get_page_html(page_id, page_revision if len(revisions) > 0 else 0)
            # update image URLs for images we already uploaded to bookstack
            html = self.upload_and_patch_img_urls(html)
            html = self.patch_page_urls(html)
            bookstack_page = self.bookstack.page_create(name=page_slug.title(), html=html, book_id=book.id, chapter_id=chapter.id if chapter else None)
            html = self.upload_and_patch_img_urls(html, bookstack_page.id)
            self.bookstack.page_update(bookstack_page.id, html=html)
            migrated_page = MigratedPage(page=bookstack_page, latest_revision=page_revision)
            self.progress.pages[str(page_path)] = migrated_page

    def bookstack_url_from_dokuwiki_id(self, page_id: str) -> str | None:
        page_path = map_page_id(page_id)
        if not page_path:
            return None
        book_id, chapter_id, page_slug = page_path
        book = self.progress.books.get(book_id)
        migrate_page = self.progress.pages.get(str(page_path))
        if book is None or migrate_page is None:
            return None
        return  f"/books/{book.slug}/page/{migrate_page.page.slug}"

    def patch_page_urls(self, html: str) -> str:
        soup = BeautifulSoup(html, 'html.parser')
        regex = PAGE_REGEX_PRETTY if self.dokuwiki.pretty_urls else PAGE_REGEX
        links_to_fix = find_all_tags(soup, 'a', href=regex)
        if len(links_to_fix) == 0:
            return html
        for a in links_to_fix:  
            page_id = extract(a, 'href', regex)
            if page_id is None:
                LOG.warning(f"Unable to fix link {a}, can't find page id")
                continue
            a['href'] = self.bookstack_url_from_dokuwiki_id(page_id) or a['href']
        return str(soup)
    
    def upload_and_patch_img_urls(self, html: str, page_id: int | None = None) -> str:
        soup = BeautifulSoup(html, 'html.parser')
        regex = MEDIA_REGEX_PRETTY if self.dokuwiki.pretty_urls else MEDIA_REGEX
        images_to_fix = find_all_tags(soup, 'img', src=regex)
        if len(images_to_fix) == 0:
            return html
        for img in images_to_fix:
            image_name = extract(img, 'src', regex)
            if image_name is None:
                LOG.warning("Unable to fix image {img}, can't find media id")
                continue
            image_name = image_name.split("?")[0]   
            if bookstack_path := self.progress.media.get(image_name):
                img['src'] = bookstack_path
                continue
            if page_id:
                img_file = download_file(self.dokuwiki._base_url + str(img['src']))
                bookstack_image = self.bookstack.image_gallery_create(page_id, img_file, image_name.split(":")[-1])
                self.progress.media[image_name] = bookstack_image.path
                img['src'] = bookstack_image.path
        return str(soup)

    def get_book_or_migrate(self, book_slug: str) -> Book:
        if book_slug in self.progress.books:
            return self.progress.books[book_slug]

        book = self.bookstack.book_create(book_slug.title())
        self.progress.books[book_slug] = book
        return book


    def get_chapter_or_migrate(self, book_slug: str, book_id: int, chapter_slug: str) -> Chapter:
        key = f"{book_slug}/{chapter_slug}"
        if key in self.progress.chapters:
            return self.progress.chapters[key]

        chapter = self.bookstack.chapter_create(chapter_slug.title(), book_id)
        self.progress.chapters[key] = chapter
        return chapter

    def migrate(self) -> None:
        all_pages_and_revisions: list[PageAndRevision] = []
        all_pages = self.dokuwiki.list_pages()
        for page in all_pages:
            if len(self.only_ids) != 0 and page.id not in self.only_ids:
                continue
            if self.only_public:
                public_permissions = self.dokuwiki.acl_check(page.id, user="!!notset!!", groups=["@ALL"])
                if public_permissions == 0:
                    LOG.info(f"Skipping page {page.id} because it's not public")
                    continue
            page_history_infos = self.dokuwiki.get_page_history(page.id)
            if len(page_history_infos) > 0:
                all_pages_and_revisions.extend(PageAndRevision(page_id=info.id, revision=info.revision) for info in page_history_infos)
            else:
                all_pages_and_revisions.append(PageAndRevision(page_id=page.id, revision=page.revision))

        all_pages_and_revisions.sort(key=lambda p: p.revision)
        for page_and_revision in all_pages_and_revisions:
            self.migrate_page_revision(page_id = page_and_revision.page_id, page_revision = page_and_revision.revision)