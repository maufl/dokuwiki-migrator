#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "click",
#   "toml",
#   "pydantic",
#   "httpx",
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

from migrator.dokuwiki import DokuWiki, DokuWikiConfig
from migrator.bookstack import Bookstack, BookstackConfig
from migrator.wikijs import WikijsConfig
LOG = logging.getLogger(__name__)



class Config(BaseModel):
    dokuwiki: DokuWikiConfig
    dokuwiki_target: DokuWikiConfig | None = None
    bookstack: BookstackConfig | None = None
    wikijs: WikijsConfig | None = None
    only_public: bool = True


@click.group()
def cli() -> None:
    """A tool to migrate wiki content from DokuWiki"""

@cli.command()
@click.option('--config', '-c', required=True, help="The configuration file for the migration", type=click.File(mode='r',  encoding='utf-8'))
def check(config: TextIO) -> None:
    cfg = Config(**toml.load(config))
    dokuwiki = DokuWiki(cfg.dokuwiki)

    me = dokuwiki.who_am_i()
    print(f"Migrating as user {me}")

    for page in dokuwiki.list_pages():
        revisions = dokuwiki.get_page_history(page.id)
        permissions = dokuwiki.acl_check(page.id, user="!!notset!!", groups=["@ALL"])
        print(f"Page {page.id}, latest revision {page.revision}, total revisions {len(revisions)}, public permissions {permissions}")

@cli.group()
def bookstack() -> None:
    ...

@bookstack.command()
@click.option('--config', '-c', required=True, help="The configuration file for the migration", type=click.File(mode='r',  encoding='utf-8'))
@click.option('--progress', '-p', required=False, help="A file which tracks the progress of the migration. Usefull to update a migrated wiki from the original one.", type=click.File(mode='r+',  encoding='utf-8'))
def migrate(config: TextIO, progress: TextIO | None = None) -> None:
    from migrator.bookstack import Migrator, MigrationProgress
    cfg = Config(**toml.load(config))
    assert cfg.bookstack, "Bookstack must be configured"
    dokuwiki = DokuWiki(cfg.dokuwiki)
    bookstack = Bookstack(cfg.bookstack)
    migration_progress = MigrationProgress(**toml.load(progress)) if progress else MigrationProgress()
    migrator = Migrator(
        dokuwiki=dokuwiki,
        bookstack=bookstack,
        progress=migration_progress,
        only_ids=cfg.dokuwiki.only_ids,
        only_public=cfg.only_public
    )
    try:
        migrator.migrate()
    finally:
        if progress:
            progress.seek(0)
            toml.dump(migration_progress.model_dump(), progress)


@bookstack.command()
@click.option('--config', '-c', required=True, help="The configuration file for the migration", type=click.File(mode='r',  encoding='utf-8'))
def reset(config: TextIO) -> None:
    cfg = Config(**toml.load(config))
    assert cfg.bookstack, "Bookstack must be configured"
    bookstack = Bookstack(cfg.bookstack)

    for book in bookstack.books_list():
        bookstack.book_delete(book.id)

@cli.group()
def wikijs() -> None:
    ...

@wikijs.command('migrate')
@click.option('--config', '-c', required=True, help="The configuration file for the migration", type=click.File(mode='r',  encoding='utf-8'))
@click.option('--progress', '-p', required=False, help="A file which tracks the progress of the migration. Usefull to update a migrated wiki from the original one.", type=click.File(mode='r+',  encoding='utf-8'))
def migrate_to_wikijs(config: TextIO, progress: TextIO | None = None) -> None:
    from migrator.wikijs import MigrationProgress, Migrator, Wikijs
    cfg = Config(**toml.load(config))
    assert cfg.wikijs, "Wikijs must be configured"
    dokuwiki = DokuWiki(cfg.dokuwiki)
    wikijs_client = Wikijs(cfg.wikijs)
    migration_progress = MigrationProgress(**toml.load(progress)) if progress else MigrationProgress()
    migrator = Migrator(
        dokuwiki=dokuwiki,
        wikijs=wikijs_client,
        progress=migration_progress,
        only_ids=cfg.dokuwiki.only_ids,
        only_public=cfg.only_public
    )
    try:
        migrator.migrate()
    finally:
        if progress:
            progress.seek(0)
            toml.dump(migration_progress.model_dump(), progress)

@wikijs.command("reset")
@click.option('--config', '-c', required=True, help="The configuration file for the migration", type=click.File(mode='r',  encoding='utf-8'))
def reset_wikijs(config: TextIO) -> None:
    from migrator.wikijs import MigrationProgress, Migrator, Wikijs
    cfg = Config(**toml.load(config))
    assert cfg.wikijs, "Wikijs must be configured"
    wikijs_client = Wikijs(cfg.wikijs)
    pages = wikijs_client.list_pages()
    for page in pages:
        wikijs_client.delete_page(page.id)

@cli.group()
def dokuwiki() -> None:
    ...

@dokuwiki.command('migrate')
@click.option('--config', '-c', required=True, help="The configuration file for the migration", type=click.File(mode='r',  encoding='utf-8'))
@click.option('--progress', '-p', required=False, help="A file which tracks the progress of the migration. Usefull to update a migrated wiki from the original one.", type=click.File(mode='r+',  encoding='utf-8'))
def migrate_to_doku_wiki(config: TextIO, progress: TextIO | None = None) -> None:
    from migrator.dokuwiki import Migrator, MigrationProgress
    cfg = Config(**toml.load(config))
    source = DokuWiki(cfg.dokuwiki)
    assert cfg.dokuwiki_target, "A DokuWiki target must be configured"
    target = DokuWiki(cfg.dokuwiki_target)
    migration_progress = MigrationProgress(**toml.load(progress)) if progress else MigrationProgress()
    migrator = Migrator(
        source=source,
        target=target,
        progress=migration_progress,
        only_ids=cfg.dokuwiki.only_ids,
        only_public=cfg.only_public
    )
    migrator.migrate()

@dokuwiki.command('reset')
@click.option('--config', '-c', required=True, help="The configuration file for the migration", type=click.File(mode='r',  encoding='utf-8'))
def reset_doku_wiki(config: TextIO) -> None:
    from migrator.dokuwiki import Migrator
    cfg = Config(**toml.load(config))
    assert cfg.dokuwiki_target, "A DokuWiki target must be configured"
    target = DokuWiki(cfg.dokuwiki_target)
    pages = target.list_pages()
    for page in pages:
        # Saving an empty page "deletes" it
        # old revisions will be kept, so it's kinda pointless
        target.save_page(page.id, "")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cli()
