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

from typing import TextIO, NamedTuple, IO
import logging
from tempfile import TemporaryFile

from pydantic import BaseModel
import click
import toml

from migrator.dokuwiki import DokuWiki, PageInfo
from migrator.bookstack import Bookstack
from migrator.migrator import Migrator, MigrationProgress

LOG = logging.getLogger(__name__)

class BookstackToken(BaseModel):
    id: str
    secret: str

class BookstackConfig(BaseModel):
    base_url: str
    token: BookstackToken

class DokuWikiBasicAuth(BaseModel):
    username: str
    password: str

class DokuWikiConfig(BaseModel):
    base_url: str
    auth_token: str | None = None
    auth_basic: DokuWikiBasicAuth | None = None
    only_ids: list[str] = []
    pretty_urls: bool = False

class Config(BaseModel):
    dokuwiki: DokuWikiConfig
    bookstack: BookstackConfig


@click.command()
@click.option('--config', '-c', required=True, help="The configuration file for the migration", type=click.File(mode='r',  encoding='utf-8'))
@click.option('--progress', '-p', required=False, help="A file which tracks the progress of the migration. Usefull to update a migrated wiki from the original one.", type=click.File(mode='w+',  encoding='utf-8'))
def migrate(config: TextIO, progress: TextIO | None = None) -> None:
    config = Config(**toml.load(config))
    dokuwiki = DokuWiki(config.dokuwiki.base_url, config.dokuwiki.auth_token, basic_auth = config.dokuwiki.auth_basic, pretty_urls = config.dokuwiki.pretty_urls)
    bookstack = Bookstack(config.bookstack.base_url, config.bookstack.token.id, config.bookstack.token.secret)
    migration_progress = MigrationProgress(**toml.load(progress)) if progress else MigrationProgress()
    migrator = Migrator(
        dokuwiki=dokuwiki,
        bookstack=bookstack,
        progress=migration_progress,
        only_ids=config.dokuwiki.only_ids
    )
    try:
        migrator.migrate()
    finally:
        if progress:
            progress.seek(0)
            toml.dump(migration_progress.model_dump(), progress)

@click.command()
@click.option('--config', '-c', required=True, help="The configuration file for the migration", type=click.File(mode='r',  encoding='utf-8'))
def check(config: TextIO) -> None:
    config = Config(**toml.load(config))
    dokuwiki = DokuWiki(config.dokuwiki.base_url, config.dokuwiki.auth_token, basic_auth = config.dokuwiki.auth_basic)

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
    logging.basicConfig(level=logging.INFO)
    cli.add_command(migrate)
    cli.add_command(check)
    cli.add_command(reset)
    cli()
