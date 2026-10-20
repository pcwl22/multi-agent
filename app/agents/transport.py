"""Allowlisted exception-chain diagnostics without messages, URLs or headers."""
import ssl

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
    (TimeoutError, 'TimeoutError', 'unknown'),
]


def transport_diagnostics(exc: Exception, *, streaming: bool | None = None) -> dict:
    seen: set[int] = set()
    names: list[str] = []
    phase = 'unknown'
    current: BaseException | None = exc
    while current is not None and len(names) < 8 and id(current) not in seen:
        seen.add(id(current))
        name, candidate = next(((name, stage) for kind, name, stage in _KNOWN
                                if isinstance(current, kind)), ('OtherException', 'unknown'))
        names.append(name)
        if candidate != 'unknown':
            phase = candidate
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return TransportDiagnostics(phase=phase, exception_types=names, chain_truncated=current is not None,
                                streaming_requested=streaming).model_dump()
