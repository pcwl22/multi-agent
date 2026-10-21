"""Allowlisted exception-chain diagnostics without messages, URLs or headers."""
import hashlib
import re
import ssl
from importlib.metadata import PackageNotFoundError, version

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.models.reliability import TransportDiagnostics

_KNOWN = [
    (httpx.ConnectTimeout, 'ConnectTimeout', 'connect'),
    (httpx.ReadTimeout, 'ReadTimeout', 'read'),
    (httpx.WriteTimeout, 'WriteTimeout', 'write'),
    (httpx.PoolTimeout, 'PoolTimeout', 'pool'),
    (httpx.ProxyError, 'ProxyError', 'proxy'),
    (httpx.RemoteProtocolError, 'RemoteProtocolError', 'protocol'),
    (httpx.LocalProtocolError, 'LocalProtocolError', 'protocol'),
    (httpx.ConnectError, 'ConnectError', 'connect'),
    (httpx.ReadError, 'ReadError', 'read'),
    (httpx.WriteError, 'WriteError', 'write'),
    (httpx.CloseError, 'CloseError', 'unknown'),
    (ssl.SSLCertVerificationError, 'SSLCertVerificationError', 'connect'),
    (ssl.SSLError, 'SSLError', 'connect'),
    (ConnectionRefusedError, 'ConnectionRefusedError', 'connect'),
    (ConnectionResetError, 'ConnectionResetError', 'unknown'),
    (BrokenPipeError, 'BrokenPipeError', 'write'),
    (APITimeoutError, 'APITimeoutError', 'unknown'),
    (APIConnectionError, 'APIConnectionError', 'unknown'),
    (APIStatusError, 'APIStatusError', 'response'),
    (httpx.HTTPStatusError, 'HTTPStatusError', 'response'),
    (TimeoutError, 'TimeoutError', 'unknown'),
]


def sdk_versions() -> dict[str, str]:
    """Local package metadata only, never provider-supplied version strings."""
    result = {}
    for package in ('openai', 'httpx', 'langchain-openai'):
        try:
            value = version(package)
        except PackageNotFoundError:
            continue
        if re.fullmatch(r'[A-Za-z0-9.+_-]{1,64}', value):
            result[package] = value
    return result


def response_identity(response: httpx.Response | None) -> dict:
    """Allowlisted integer status and hashed correlation ID; no raw headers."""
    if not isinstance(response, httpx.Response):
        return {}
    result = {}
    status = response.status_code
    if type(status) is int and 100 <= status <= 599:
        result['http_status'] = status
    for name in ('x-request-id', 'request-id', 'x-amzn-requestid'):
        value = response.headers.get(name)
        if value and len(value) <= 512:
            result['request_id_sha256'] = hashlib.sha256(value.encode('utf-8')).hexdigest()
            break
    return result


def transport_diagnostics(exc: Exception, *, streaming: bool | None = None) -> dict:
    seen: set[int] = set()
    names: list[str] = []
    phase = 'unknown'
    identity = {}
    current: BaseException | None = exc
    while current is not None and len(names) < 8 and id(current) not in seen:
        seen.add(id(current))
        if not identity and isinstance(current, (APIStatusError, httpx.HTTPStatusError)):
            identity = response_identity(current.response)
        name, candidate = next(((name, stage) for kind, name, stage in _KNOWN
                                if isinstance(current, kind)), ('OtherException', 'unknown'))
        names.append(name)
        if candidate != 'unknown':
            phase = candidate
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return TransportDiagnostics(phase=phase, exception_types=names, chain_truncated=current is not None,
                                streaming_requested=streaming, **identity).model_dump()
