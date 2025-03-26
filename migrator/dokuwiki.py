from typing import Any
from urllib.parse import urljoin
import logging
from enum import IntEnum

from pydantic import BaseModel
import requests

JSONRPC_PATH = "/lib/exe/jsonrpc.php"

LOG = logging.getLogger(__name__)
#LOG.setLevel(logging.DEBUG)


class DokuWikiBasicAuth(BaseModel):
    username: str
    password: str

class DokuWikiConfig(BaseModel):
    base_url: str
    auth_token: str | None = None
    auth_basic: DokuWikiBasicAuth | None = None
    only_ids: list[str] = []
    pretty_urls: bool = False

class Permission(IntEnum):
    NONE = 0
    READ = 1
    EDIT = 2
    CREATE = 4
    UPLOAD = 8
    DELETE = 16

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
    sizechange: int | None

class GetPageHistoryResult(BaseModel):
    result: list[PageHistoryInfo] | None = None
    error: Error


class GetPageHtmlResult(BaseModel):
    result: str
    error: Error


class GetPageResult(BaseModel):
    result: str
    error: Error

class AclCheckResult(BaseModel):
    result: int
    error: Error

class User(BaseModel):
    login: str
    name: str
    mail: str
    groups: list[str]
    isadmin: bool
    ismanager: bool

class WhoAmIResult(BaseModel):
    error: Error
    result: User | None = None

class DokuWiki:
    _base_url: str
    _session: requests.Session
    pretty_urls: bool

    def __init__(self, config: DokuWikiConfig) -> None:
        self._base_url = config.base_url
        self._session = requests.Session()
        self._session.headers.update({ "Content-Type": "application/json" })
        if config.auth_token:
            self._session.headers.update({ "Authorization": f"Bearer {config.auth_token}", "Content-Type": "application/json" })
            self._session.headers.update({ "X-DokuWiki-Token": config.auth_token })
        if config.auth_basic:
            self._session.auth = (config.auth_basic.username, config.auth_basic.password)
        self.pretty_urls = config.pretty_urls

    def call(self, rpc_method: str, args: Any | None = None) -> Any:
        url = urljoin(self._base_url, JSONRPC_PATH + rpc_method)
        resp = self._session.post(url, json=args)
        LOG.debug(f"Call {rpc_method} returned {resp.text}")
        if not resp.ok:
            raise Exception(f"Call {rpc_method} did not succeed: {resp.status_code} {resp.text}")
        json_resp = resp.json()
        if "error" in json_resp:
            error = Error(**json_resp["error"])
            if not error.no_error:
                raise RpcError(rpc_method, error.code, error.message)
        return json_resp

    def who_am_i(self) -> User:
        result = WhoAmIResult(**self.call("/core.whoAmI"))
        if result.result is None:
            raise RuntimeError("Call to whoAmI returned no data")
        return result.result

    def list_pages(self) -> list[PageInfo]:
        args = {
            "namespace": "",
            "depth": 0
        }
        result = ListPagesResult(**self.call("/core.listPages", args))
        if result.result is None:
            raise RuntimeError("Call to listPages returned no data")
        return result.result



    def get_page_history(self, id: str, skip: int = 0) -> list[PageHistoryInfo]:
        args = {
            "page": id,
            "first": skip
        }
        result = GetPageHistoryResult(**self.call("/core.getPageHistory", args))
        if result.result is None:
            raise RuntimeError("Call to getPageHistory returned no data")
        return result.result

    def get_page(self, id: str, revision: int = 0) -> str:
        result = GetPageResult(**self.call("/core.getPage", { "page": id, "rev": revision }))
        return result.result


    def get_page_html(self, id: str, revision: int = 0) -> str:
        result = GetPageResult(**self.call("/core.getPageHTML", { "page": id, "rev": revision }))
        LOG.debug(f"Result of getPageHTML for {id} {revision}: {result}")
        return result.result

    def acl_check(self, page_id: str, user: str = "", groups: list[str] = []) -> int:
        result = AclCheckResult(**self.call("/core.aclCheck", { "page": page_id, "user": user, "groups": groups }))
        return result.result