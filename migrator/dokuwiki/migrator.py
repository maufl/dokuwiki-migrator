from typing import Any, IO
import logging 
import base64

from pydantic import BaseModel
from bs4 import BeautifulSoup

from .api import DokuWiki
from migrator.shared import MEDIA_REGEX, MEDIA_REGEX_PRETTY, extract, find_all_tags, download_file, PageAndRevision

LOG = logging.getLogger(__name__)


class Migrator:
    source: DokuWiki
    target: DokuWiki
    only_ids: list[str]
    only_public: bool

    def __init__(self, source: DokuWiki, target: DokuWiki, only_ids: list[str] = [], only_public: bool = True) -> None:
        self.source = source
        self.target = target
        self.only_ids = only_ids
        self.only_public = only_public

    def migrate_page_revision(self, page: PageAndRevision) -> None:
        page_id = page.page_id
        page_revision = page.revision
        LOG.info(f"Trying to migrate page {page_id} revision {page_revision}")
        page_history_infos = self.source.get_page_history(page_id)
        revisions = sorted(info.revision for info in page_history_infos)
        # if we only have one revision, then we must pass 0 as revision to dokuwiki, otherwise it returns an error
        text = self.source.get_page(page_id, page_revision if len(revisions) > 0 else 0)
        self.target.save_page(page_id, text)
        # upload media contained in page
        html = self.source.get_page_html(page_id, page_revision if len(revisions) > 0 else 0)
        self.upload_media(html)
    
    def upload_media(self, html: str) -> str | None:
        soup = BeautifulSoup(html, 'html.parser')
        regex = MEDIA_REGEX_PRETTY if self.source.pretty_urls else MEDIA_REGEX
        images_to_fix = find_all_tags(soup, 'img', src=regex)
        for img in images_to_fix:
            image_name = extract(img, 'src', regex)
            if image_name is None:
                LOG.warning("Unable to fix image {img}, can't find media id")
                continue
            image_name = image_name.split("?")[0]
            img_file = download_file(self.source._base_url + str(img['src']))
            self.target.save_media(image_name, base64.b64encode(img_file.read()).decode('utf-8'), overwrite=True)
        links_to_fix = find_all_tags(soup, 'a', href=regex)
        for a in links_to_fix:
            media_name = extract(a, 'href', regex)
            if media_name is None:
                LOG.warning(f"Unable to fix link {a}, can't find media id")
                continue
            media_name = media_name.split("?")[0] 
            media_file = download_file(self.source._base_url + str(a['href']))
            self.target.save_media(media_name, base64.b64encode(media_file.read()).decode('utf-8'), overwrite=True)
        return str(soup)


    def migrate(self) -> None:
        all_pages_and_revisions: list[PageAndRevision] = []
        all_pages = self.source.list_pages()
        for page in all_pages:
            if len(self.only_ids) != 0 and page.id not in self.only_ids:
                continue
            if self.only_public:
                public_permissions = self.source.acl_check(page.id, user="!!notset!!", groups=["@ALL"])
                if public_permissions == 0:
                    LOG.info(f"Skipping page {page.id} because it's not public")
                    continue
            page_history_infos = self.source.get_page_history(page.id)
            if len(page_history_infos) > 0:
                all_pages_and_revisions.extend(PageAndRevision(page_id=info.id, revision=info.revision) for info in page_history_infos)
            else:
                all_pages_and_revisions.append(PageAndRevision(page_id=page.id, revision=page.revision))

        all_pages_and_revisions.sort(key=lambda p: p.revision)
        for page_and_revision in all_pages_and_revisions:
            self.migrate_page_revision(page_and_revision)