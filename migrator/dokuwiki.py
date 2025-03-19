from typing import Any
from urllib.parse import urljoin
import logging

from pydantic import BaseModel
import requests

JSONRPC_PATH = "/lib/exe/jsonrpc.php"

LOG = logging.getLogger(__name__)

class RpcError(Exception):
    method: str
    code: int
    message: str

    def __init__(self, method: str, code: int, message: str) -> None:
        super().__init__(f"Error calling {method}. Server returned {code}: {message}")
        self.method = method
        self.code = code
        self.message = message

class Error(BaseModel):
    code: int
    message: str

    @property
    def no_error(self) -> bool:
        return self.code == 0 and self.message == "success"

class PageInfo(BaseModel):
    id: str
    revision: int
    size: int
    title: str
    permission: int
    author: str

class ListPagesResult(BaseModel):
    result: list[PageInfo] | None = None
    error: Error


class PageHistoryInfo(BaseModel):
    id: str
    revision: int
    author: str
    summary: str
    type: str
    sizechange: int

class GetPageHistoryResult(BaseModel):
    result: list[PageHistoryInfo] | None = None
    error: Error


class GetPageHtmlResult(BaseModel):
    result: str
    error: Error


class GetPageResult(BaseModel):
    result: str
    error: Error

class DokuWiki:
    _base_url: str
    _auth_token: str | None
    _session: requests.Session
    pretty_urls: bool

    def __init__(self, base_url: str, auth_token: str | None = None, pretty_urls: bool = False) -> None:
        self._base_url = base_url
        self._auth_token = auth_token
        self._session = requests.Session()
        if auth_token:
            self._session.headers.update({ "Authorization": f"Bearer {auth_token}", "Content-Type": "application/json" })
        self.pretty_urls = pretty_urls

    def call(self, rpc_method: str, args: Any | None = None) -> Any:
        url = urljoin(self._base_url, JSONRPC_PATH + rpc_method)
        resp = self._session.post(url, json=args)
        if not resp.ok:
            raise Exception(f"Call {rpc_method} did not succeed: {resp.status_code} {resp.text}")
        resp = resp.json()
        if "error" in resp:
            error = Error(**resp["error"])
            if not error.no_error:
                raise RpcError(rpc_method, error.code, error.message)
        return resp


    def list_pages(self) -> list[PageInfo]:
        args = {
            "namespace": "",
            "depth": 0
        }
        result = ListPagesResult(**self.call("/core.listPages", args))
        return result.result



    def get_page_history(self, id: str, skip: int = 0) -> list[PageHistoryInfo]:
        args = {
            "page": id,
            "first": skip
        }
        result = GetPageHistoryResult(**self.call("/core.getPageHistory", args))
        return result.result

    def get_page(self, id: str, revision: int = 0) -> str:
        result = GetPageResult(**self.call("/core.getPage", { "page": id, "rev": revision }))
        return result.result


    def get_page_html(self, id: str, revision: int = 0) -> str:
        result = GetPageResult(**self.call("/core.getPageHTML", { "page": id, "rev": revision }))
        LOG.debug(f"Result of getPageHTML for {id} {revision}: {result}")
        return result.result