from typing import Any, IO
from urllib.parse import urljoin
import logging

from pydantic import BaseModel
import requests

API_PATH = "/api"

LOG = logging.getLogger(__name__)

class BookstackError(Exception):
    code: int
    message: str

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

class Book(BaseModel):
    id: int
    slug: str
    name: str
    description: str

class ListBooksResponse(BaseModel):
    data: list[Book]
    total: int


class Chapter(BaseModel):
    id: int
    book_id: int
    slug: str
    name: str
    description: str

class ListChaptersResponse(BaseModel):
    data: list[Chapter]
    total: int

class Page(BaseModel):
    id: int
    book_id: int
    chapter_id: int
    name: str
    slug: str

class Image(BaseModel):
    name: str
    path: str
    url: str

def remove_none(json: Any) -> Any:
    if not isinstance(json, dict):
        return json
    return {
        k: v
        for k, v in json.items()
        if v is not None
    }

class Bookstack:
    _base_url: str
    _session: requests.Session

    def __init__(self, base_url: str, token_id: str, token_secret: str) -> None:
        self._base_url = base_url
        self._session = requests.Session()
        self._session.headers.update({ "Authorization": f"Token {token_id}:{token_secret}" })

    def _rais_error_if_any(self, json: Any) -> Any:
        if "error" in json:
            error = json["error"]
            raise BookstackError(error["code"], error["message"])
        return json

    def get(self, endpoint: str) -> Any:
        LOG.debug(f"GET {endpoint}")
        response = self._session.get(urljoin(self._base_url, API_PATH + endpoint))
        return self._rais_error_if_any(response.json())

    def delete(self, endpoint: str) -> Any:
        LOG.debug(f"GET {endpoint}")
        response = self._session.delete(urljoin(self._base_url, API_PATH + endpoint))
        if not response.ok:
            raise RuntimeError(f"Unable to delete {endpoint}")

    def post(self, endpoint: str, json: Any | None = None, files: Any | None = None) -> Any:
        LOG.debug(f"POST {endpoint} json={json} files={files}")
        assert not (json and files), "You can't specifiy JSON and multipart content at the same time"
        url = urljoin(self._base_url, API_PATH + endpoint)
        if json:
            response = self._session.post(url, json=remove_none(json))
        else:
            response = self._session.post(url, files=files)
            LOG.debug(response.request.body)
        return self._rais_error_if_any(response.json())

    def put(self, endpoint: str, json: Any | None = None) -> Any:
        LOG.debug(f"PUT {endpoint} json={json}")
        response = self._session.put(urljoin(self._base_url, API_PATH + endpoint), json=remove_none(json))
        return self._rais_error_if_any(response.json())

    def books_list(self) -> list[Book]:
        response = ListBooksResponse(**self.get("/books"))
        return response.data

    def book_read(self, id: int) -> Book:
        return Book(**self.get(f"/books/{id}"))

    def book_create(self, name: str) -> Book:
        book = Book(**self.post(f"/books", json={ "name": name }))
        return book

    def book_delete(self, book_id: int) -> None:
        self.delete(f"/books/{book_id}")
    

    
    def chapters_list(self) -> list[Chapter]:
        response = ListChaptersResponse(**self.get("/chapters"))
        return response.data

    def chapter_read(self, id: int) -> Chapter:
        return Chapter(**self.get(f"/chapters/{id}"))

    def chapter_create(self, name: str, book_id: int) -> Chapter:
        chapter = Chapter(**self.post(f"/chapters", json={ "name": name, "book_id": book_id }))
        return chapter


    def page_create(self, name: str, html: str | None = None, markdown: str | None = None, book_id: int | None = None, chapter_id: int | None = None) -> Page:
        assert html or markdown_str, "Either HTML or Markdown content is required"
        assert book_id or chapter_id, "Either a book id or a chapter id is required"
        return Page(**self.post(f"/pages", json={
            "name": name,
            "html": html,
            "markdown": markdown,
            "book_id": book_id,
            "chapter_id": chapter_id,
        }))

    def page_update(self, page_id: int, name: str | None = None, html: str | None = None, markdown: str | None = None, book_id: int | None = None, chapter_id: int | None = None) -> Page:
        return Page(**self.put(f"/pages/{page_id}", json={
            "name": name,
            "html": html,
            "markdown": markdown,
            "book_id": book_id,
            "chapter_id": chapter_id,
        }))

    def image_gallery_create(self, page_id: int, image: IO, name: str | None = None) -> Image:
        return Image(**self.post(f"/image-gallery", files={ "uploaded_to": (None, page_id), "type": (None, "gallery"), "image": (name, image), "name": (None, name) }))