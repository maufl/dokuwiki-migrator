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

class DokuWikiConfig(BaseModel):
    base_url: str
    auth_token: str

class Config(BaseModel):
    dokuwiki: DokuWikiConfig
    bookstack: BookstackConfig


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
    logging.basicConfig(level=logging.INFO)
    cli.add_command(migrate)
    cli.add_command(check)
    cli.add_command(reset)
    cli()
