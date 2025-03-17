#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "click",
#   "toml",
#   "pydantic",
#   "requests",
#   "beautifulsoup4"
# ]
# ///

from typing import TextIO, NamedTuple
import logging

from pydantic import BaseModel
import click
import toml

from migrator.dokuwiki import DokuWiki, PageInfo
from migrator.bookstack import Bookstack

LOG = logging.getLogger(__name__)

class BookstackToken(BaseModel):
    id: str
    secret: str

class BookstackConfig(BaseModel):
    base_url: str
    token: BookstackToken

class DokuWikiConfig(BaseModel):
    base_url: str
    auth_token: str

class Config(BaseModel):
    dokuwiki: DokuWikiConfig
    bookstack: BookstackConfig

class PagePath(NamedTuple):
    book_slug: str 
    chapter_slug: str | None
    page_slug: str


class ChapterPath(NamedTuple):
    book_slug: str 
    chapter_slug: str

def map_page_id(page_id: str) -> PagePath | None:
    match page_id.split(":"):
        case [book_slug, chapter_slug, page_slug, *rest]:
            return PagePath(book_slug, chapter_slug, "-".join(page_slug, *rest))
        case [book_slug, page_slug]:
            return PagePath(book_slug, None, page_slug)
        case _:
            return None

class MigratedPage(BaseModel):
    page_id: int
    latest_revision: int

class MigrationProgress(BaseModel):
    books: dict[str, int] = {}
    chapters: dict[ChapterPath, int] = {}
    pages: dict[PagePath, MigratedPage] = {}

class Migrator:
    progress: MigrationProgress
    dokuwiki: DokuWiki
    bookstack: Bookstack

    def __init__(self, dokuwiki: DokuWiki, bookstack: Bookstack, progress: MigrationProgress) -> None:
        self.dokuwiki = dokuwiki
        self.bookstack = bookstack
        self.progress = progress

    def migrate_page_and_revisions(self, page: PageInfo) -> None:
        LOG.info(f"Trying to migrate page {page.id}")
        page_path = map_page_id(page.id)
        if not page_path:
            LOG.error(f"Unable to migrate page {page.id}, not enough components in the page path/id")
            return
        book_slug, chapter_slug, page_slug = page_path
        book_id = self.get_book_id_or_migrate(book_slug)
        chapter_id = self.get_chapter_id_or_migrate(book_slug, book_id, chapter_slug) if chapter_slug else None

        page_history_infos = self.dokuwiki.get_page_history(page.id)
        revisions = sorted(info.revision for info in page_history_infos)
        # If only one revision exists, DokuWiki doesn't report it in the history
        # If more than one revision exists, DokuWiki reports all of them ...
        if page.revision not in revisions:
            revisions.append(page.revision)
        LOG.debug(f"Found {len(revisions)} revisions of the page")

        # check if we migrated this page before
        migrated_page = self.progress.pages.get(page_path)
        if migrated_page:
            # if we already migrated this page, ignore revisions that are older than the latest one we migrated
            revisions = [ rev for rev in revisions if rev > migrated_page.latest_revision ]
        else:
            # else create the page for the first time, discard the first revision from the list of revisions to apply
            first_revision, *revisions = revisions
            # if we only have one revision, then we must pass 0 as revision to dokuwiki, otherwise it returns an error
            html = self.dokuwiki.get_page_html(page.id, first_revision if len(revisions) > 0 else 0)
            bookstack_page = self.bookstack.page_create(name=page_slug.title(), html=html, book_id=book_id, chapter_id=chapter_id)
            migrated_page = MigratedPage(page_id=bookstack_page.id, latest_revision=first_revision)
            self.progress.pages[page_path] = migrated_page
        # apply remaining migrations
        for revision in revisions:
            html = self.dokuwiki.get_page_html(page.id, revision)
            self.bookstack.page_update(migrated_page.page_id, html=html)
            self.progress.pages[page_path].latest_revision = revision

    def get_book_id_or_migrate(self, book_slug: str) -> int:
        if book_slug in self.progress.books:
            return self.progress.books[book_slug]

        book = self.bookstack.book_create(book_slug)
        self.progress.books[book_slug] = book.id
        return book.id


    def get_chapter_id_or_migrate(self, book_slug: str, book_id: int, chapter_slug: str) -> int:
        key = ChapterPath(book_slug, chapter_slug)
        if key in self.progress.chapters:
            return self.progress.chapters[key]

        chapter = self.bookstack.chapter_create(chapter_slug, book_id)
        self.progress.chapters[key] = chapter.id
        return chapter.id

    def migrate(self) -> None:
        all_pages = self.dokuwiki.list_pages()
        for page in all_pages:
            self.migrate_page_and_revisions(page)

@click.command()
@click.option('--config', '-c', required=True, help="The configuration file for the migration", type=click.File(mode='r',  encoding='utf-8'))
def migrate(config: TextIO) -> None:
    config = Config(**toml.load(config))
    dokuwiki = DokuWiki(config.dokuwiki.base_url, config.dokuwiki.auth_token)
    bookstack = Bookstack(config.bookstack.base_url, config.bookstack.token.id, config.bookstack.token.secret)
    migrator = Migrator(
        dokuwiki=dokuwiki,
        bookstack=bookstack,
        progress=MigrationProgress()
    )
    migrator.migrate()

@click.command()
@click.option('--config', '-c', required=True, help="The configuration file for the migration", type=click.File(mode='r',  encoding='utf-8'))
def check(config: TextIO) -> None:
    config = Config(**toml.load(config))
    dokuwiki = DokuWiki(config.dokuwiki.base_url, config.dokuwiki.auth_token)

    for page in dokuwiki.list_pages():
        print(f"Page {page.id}, latest revision {page.revision}")
        revisions = dokuwiki.get_page_history(page.id)
        print(f"Revisions {revisions}")


@click.command()
@click.option('--config', '-c', required=True, help="The configuration file for the migration", type=click.File(mode='r',  encoding='utf-8'))
def reset(config: TextIO) -> None:
    config = Config(**toml.load(config))
    bookstack = Bookstack(config.bookstack.base_url, config.bookstack.token.id, config.bookstack.token.secret)

    for book in bookstack.books_list():
        bookstack.book_delete(book.id)


@click.group()
def cli() -> None:
    """A tool to migrate wiki content from DokuWiki"""
    


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    cli.add_command(migrate)
    cli.add_command(check)
    cli.add_command(reset)
    cli()
