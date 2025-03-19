from urllib.parse import urljoin

from pydantic import BaseModel

from .graphql_client import Client, CreatePagePagesCreatePage

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

class Wikijs:
    _base_url: str
    _graphql: Client

    def __init__(self, config: WikijsConfig) -> None:
        self._base_url = config.base_url
        self._graphql = Client(urljoin(config.base_url, "/graphql"), { "Authorization": f"Bearer {config.auth_token}" })

    def create_page(self, path: str, title: str, content: str, locale: str = "de", editor: str = "ckeditor") -> CreatePagePagesCreatePage:
        pages = self._graphql.create_page(
            path=path,
            title=title,
            content=content,
            description="",
            is_published=True,
            is_private=False,
            editor=editor,
            locale=locale,
            tags=[],
        ).pages
        if pages is None:
            raise RuntimeError("Expected a response object")
        create = pages.create
        if create is None:
            raise RuntimeError("Exprected a response object")
        result = create.response_result
        if result is not None and not result.succeeded:
            raise WikijsError(result.error_code, result.slug, result.message)
        if create.page is None:
            raise RuntimeError("Exprected a response object")
        return create.page

    def update_page(self, id: int, content: str, editor: str = "ckeditor") -> None:
        pages = self._graphql.update_page(
            id=id,
            content=content,
            editor=editor
        ).pages
        if pages is None:
            raise RuntimeError("Expected a response object")
        update = pages.update
        if update is None:
            raise RuntimeError("Exprected a response object")
        result = update.response_result
        if result is not None and not result.succeeded:
            raise WikijsError(result.error_code, result.slug, result.message)