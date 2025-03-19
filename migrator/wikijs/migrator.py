from typing import Any
import logging 

from pydantic import BaseModel
from bs4 import BeautifulSoup

from migrator.dokuwiki import DokuWiki
from .api import Wikijs
from migrator.shared import MEDIA_REGEX, MEDIA_REGEX_PRETTY, PAGE_REGEX, PAGE_REGEX_PRETTY, extract, find_all_tags, download_file, PageAndRevision

LOG = logging.getLogger(__name__)

class MigratedPage(BaseModel):
    page_id: int
    latest_revision: int

class MigrationProgress(BaseModel):
    pages: dict[str, MigratedPage] = {}

def page_id_to_path(page_id: str) -> str:
    return page_id.replace(":", "/")

def page_id_to_title(page_id: str) -> str:
    return page_id.split(":")[-1].title()

class Migrator:
    progress: MigrationProgress
    dokuwiki: DokuWiki
    wikijs: Wikijs
    only_ids: list[str]
    only_public: bool

    def __init__(self, dokuwiki: DokuWiki, wikijs: Wikijs, progress: MigrationProgress, only_ids: list[str] = [], only_public: bool = True) -> None:
        self.dokuwiki = dokuwiki
        self.wikijs = wikijs
        self.progress = progress
        self.only_ids = only_ids
        self.only_public = only_public

    def migrate_page_revision(self, page: PageAndRevision) -> None:
        page_id = page.page_id
        page_revision = page.revision
        LOG.info(f"Trying to migrate page {page_id} revision {page_revision}")
        migrated_page = self.progress.pages.get(page_id)
        if migrated_page:
            # if we already migrated this page, assert that we try to create a newer revision
            if migrated_page.latest_revision >= page_revision:
                return LOG.info(f"Skip migration of {page_id} {page_revision}, already migrated")
            html = self.dokuwiki.get_page_html(page_id, page_revision)
            html = self.upload_and_patch_img_urls(html, migrated_page.page_id) or html
            html = self.patch_page_urls(html) or html
            self.wikijs.update_page(
                id=migrated_page.page_id,
                content=html,
            )
            self.progress.pages[page_id].latest_revision = page_revision
        else:
            page_history_infos = self.dokuwiki.get_page_history(page_id)
            revisions = sorted(info.revision for info in page_history_infos)
            # if we only have one revision, then we must pass 0 as revision to dokuwiki, otherwise it returns an error
            html = self.dokuwiki.get_page_html(page_id, page_revision if len(revisions) > 0 else 0)
            # update image URLs for images we already uploaded to bookstack
            html = self.upload_and_patch_img_urls(html) or html
            html = self.patch_page_urls(html) or html
            wikijs_page = self.wikijs.create_page(
                path=page_id_to_path(page_id),
                title=page_id_to_title(page_id),
                content=html,
                editor="ckeditor",
                locale="de",
            )
            LOG.info(f"Page creation result {wikijs_page}")
            wikijs_page_id = wikijs_page.id
            fixed_html = self.upload_and_patch_img_urls(html)
            if fixed_html is not None:
                self.wikijs.update_page(
                    id=wikijs_page_id,
                    content=fixed_html,
                )
            migrated_page = MigratedPage(page_id=wikijs_page_id, latest_revision=page_revision)
            self.progress.pages[page_id] = migrated_page
        

    def patch_page_urls(self, html: str) -> str | None:
        soup = BeautifulSoup(html, 'html.parser')
        regex = PAGE_REGEX_PRETTY if self.dokuwiki.pretty_urls else PAGE_REGEX
        links_to_fix = find_all_tags(soup, 'a', href=regex)
        if len(links_to_fix) == 0:
            return None
        for a in links_to_fix:  
            page_id = extract(a, 'href', regex)
            if page_id is None:
                LOG.warning(f"Unable to fix link {a}, can't find page id")
                continue
            a['href'] = page_id_to_path(page_id)
        return str(soup)
    
    def upload_and_patch_img_urls(self, html: str, page_id: int | None = None) -> str | None:
        soup = BeautifulSoup(html, 'html.parser')
        regex = MEDIA_REGEX_PRETTY if self.dokuwiki.pretty_urls else MEDIA_REGEX
        images_to_fix = find_all_tags(soup, 'img', src=regex)
        if len(images_to_fix) == 0:
            return None
        for img in images_to_fix:
            image_name = extract(img, 'src', regex)
            if image_name is None:
                LOG.warning("Unable to fix image {img}, can't find media id")
                continue
            image_name = image_name.split("?")[0]   
            # TODO
            #if bookstack_path := self.progress.media.get(image_name):
            #    img['src'] = bookstack_path
            #    continue
            #if page_id:
            #    img_file = download_file(self.dokuwiki._base_url + str(img['src']))
            #    bookstack_image = self.bookstack.image_gallery_create(page_id, img_file, image_name.split(":")[-1])
            #    self.progress.media[image_name] = bookstack_image.path
            #    img['src'] = bookstack_image.path
        return str(soup)

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
            self.migrate_page_revision(page_and_revision)