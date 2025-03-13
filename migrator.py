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

from typing import TextIO

from pydantic import BaseModel
import click
import toml

from migrator.dokuwiki import DokuWiki

class BookstackToken(BaseModel):
    id: str
    secret: str

class BookstackConfig(BaseModel):
    token: BookstackToken

class DokuWikiConfig(BaseModel):
    base_url: str
    auth_token: str

class Config(BaseModel):
    dokuwiki: DokuWikiConfig
    bookstack: BookstackConfig



@click.command()
@click.option('--config', '-c', required=True, help="The configuration file for the migration", type=click.File(mode='r',  encoding='utf-8'))
def main(config: TextIO) -> None:
    config = Config(**toml.load(config))
    dokuwiki = DokuWiki(config.dokuwiki.base_url, config.dokuwiki.auth_token)

    for page in dokuwiki.list_pages():
        revisions = dokuwiki.get_page_history(page.id)
        print(f"Page {page.id}\n")
        print(revisions)
        print("\n")
        print(dokuwiki.get_page(page.id))
        print("\n")
        print(dokuwiki.get_page_html(page.id))
        print("\n\n")


    


if __name__ == "__main__":
    main()
