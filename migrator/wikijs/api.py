from typing import TypeVar, Any, Protocol, IO, Callable, cast
from urllib.parse import urljoin
import json
import logging
from functools import wraps

from pydantic import BaseModel
import requests
import httpx

from .graphql_client import Client, CreatePagePagesCreatePage, ListFoldersAssetsFolders, ListPagesPagesList
from .graphql_client.exceptions import GraphQLClientError, GraphQLClientGraphQLMultiError

LOG = logging.getLogger(__name__)

class WikijsConfig(BaseModel):
    base_url: str
    auth_token: str

class WikijsError(Exception):
    error_code: int
    slug: str
    message: str | None

    def __init__(self, error_code: int, slug: str, message: str | None = None) -> None:
        self.error_code = error_code
        self.slug = slug
        self.message = message
        super().__init__(message or f"Error {error_code} slug {slug}")

T = TypeVar('T')

def unwrap_optional(v: T | None) -> T:
    if v is None:
        raise ValueError("Expected a response object")
    return v

class ResultType(Protocol):
    succeeded: bool
    error_code: int
    slug: str
    message: str | None

def raise_if_error_result(optional_result: ResultType | None) -> None:
    result = unwrap_optional(optional_result)
    if not result.succeeded:
        raise WikijsError(result.error_code, result.slug, result.message)

C = TypeVar('C', bound=Callable[..., Any])
def log_exceptions(fn: C) -> C:
    @wraps(fn)
    def _wraped(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except GraphQLClientError as e:
            LOG.warning(f"Error in GraphQL request: {e} {e.__dict__} {repr(e)}")
            if isinstance(e, GraphQLClientGraphQLMultiError):
                for err in e.errors:
                    LOG.warning(f"Multi error {err} {err.__dict__} {repr(err)}")
            raise
        except WikijsError as e:
            LOG.warning(f"Graphql API returned an error result: {e.error_code} {e.slug} {e.message}")
            raise
    return cast(C, _wraped)

class Wikijs:
    _base_url: str
    _graphql: Client
    _session: requests.Session

    def __init__(self, config: WikijsConfig) -> None:
        self._base_url = config.base_url
        headers = { "Authorization": f"Bearer {config.auth_token}" }
        self._graphql = Client(urljoin(config.base_url, "/graphql"), headers, http_client=httpx.Client(timeout=10.0,headers=headers))
        self._session = requests.Session()
        self._session.headers.update(headers)

    @log_exceptions
    def create_page(self, path: str, title: str, content: str, locale: str = "de", editor: str = "ckeditor") -> CreatePagePagesCreatePage:
        pages = unwrap_optional(self._graphql.create_page(
            path=path,
            title=title,
            content=content,
            description="",
            is_published=True,
            is_private=False,
            editor=editor,
            locale=locale,
            tags=[],
        ).pages)
        create = unwrap_optional(pages.create)
        raise_if_error_result(create.response_result)
        return unwrap_optional(create.page)

    @log_exceptions
    def update_page(self, id: int, content: str, editor: str = "ckeditor") -> None:
        pages = unwrap_optional(self._graphql.update_page(
            id=id,
            content=content,
            editor=editor,
            tags=[]
        ).pages)
        update = unwrap_optional(pages.update)
        raise_if_error_result(update.response_result)

    @log_exceptions
    def create_folder(self, slug: str, parent_folder_id: int = 0, name: str | None = None) -> ListFoldersAssetsFolders:
        assets = unwrap_optional(self._graphql.create_folder(parent_folder_id, slug, name or slug.title()).assets)
        create_folder = unwrap_optional(assets.create_folder)
        raise_if_error_result(create_folder.response_result)
        
        folder_assets = unwrap_optional(self._graphql.list_folders(parent_folder_id).assets)
        folders = unwrap_optional(folder_assets.folders)
        return next(f for f in folders if f is not None and f.slug == slug)

    def upload_file(self, file: IO, file_name: str, folder_id: int) -> None:
        upload_url = urljoin(self._base_url, "/u")
        files = (
            ('mediaUpload', (None, json.dumps({ "folderId": folder_id }))),
            ('mediaUpload', (file_name, file))
        )
        response = self._session.post(upload_url, files=files)
        if not response.ok:
            raise RuntimeError(f"Failed to upload {file_name}: {response.status_code} {response.text}")
        LOG.info(response.text)

    @log_exceptions
    def list_pages(self) -> list[ListPagesPagesList]:
        pages = unwrap_optional(self._graphql.list_pages().pages)
        return unwrap_optional(pages.list)

    @log_exceptions
    def delete_page(self, page_id: int) -> None:
        pages = unwrap_optional(self._graphql.delete_page(page_id).pages)
        delete = unwrap_optional(pages.delete)
        raise_if_error_result(delete.response_result)

    @log_exceptions
    def list_folders(self, parent_folder_id: int) -> list[ListFoldersAssetsFolders]:
        assets = unwrap_optional(self._graphql.list_folders(parent_folder_id).assets)
        folders = unwrap_optional(assets.folders)
        return [f for f in folders if f is not None ]