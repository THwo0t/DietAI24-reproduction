"""Thread-local hash-only observation of an already constructed Provider.

No client construction, credential access, file writes, or retry policy. The
underlying adapter remains responsible for validation, cache integrity and HTTP.
`cache_present_before` is a local-path existence observation, NOT a cache-hit or
network-call assertion; inherited embeddings and concurrency can affect service.
Messages, embedding text, responses and exception text are never kept in refs.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import threading

from opt_provider import CHAT_MODEL, CHAT_URL, EMBED_MODEL, EMBED_URL, ProviderStop, fingerprint

NAMESPACE = 'external-gallery-r4.1'
EMBED_NAMESPACE = 'official-query-v1'


class TraceError(RuntimeError):
    """Fixed non-sensitive tracing-contract error."""


class TraceProvider:
    def __init__(self, provider):
        # Retain only the caller's provider reference; do not inspect/copy keys,
        # transport, client, run logs, environment or credential-file state.
        self._provider = provider
        self._local = threading.local()
        self._check_namespace()

    @property
    def namespace(self):
        return NAMESPACE

    def _check_namespace(self):
        if self._provider.namespace != NAMESPACE:
            raise TraceError('underlying_provider_namespace_mismatch')

    def _refs(self):
        if not hasattr(self._local, 'refs'):
            self._local.refs = []
        return self._local.refs

    def mark(self):
        """Return a cursor valid only for the caller's current thread."""
        return len(self._refs())

    def refs_since(self, start):
        refs = self._refs()
        if type(start) is not int or not 0 <= start <= len(refs):
            raise TraceError('invalid_current_thread_trace_cursor')
        return deepcopy(refs[start:])

    def _call(self, role, payload, invoke):
        self._check_namespace()
        url = CHAT_URL if role == 'chat' else EMBED_URL
        cache_id = fingerprint({'url': url, 'payload': payload,
            'namespace': NAMESPACE if role == 'chat' else EMBED_NAMESPACE})
        cache_path = Path(self._provider.cache) / role / (cache_id + '.json')
        reference = {'role': role, 'request_hash': cache_id, 'value_hash': None,
                     'status': 'pending', 'cache_present_before': cache_path.is_file()}
        self._refs().append(reference)
        try:
            value = invoke()
            self._check_namespace()
            reference['value_hash'] = fingerprint(value)
            reference['status'] = 'returned'
            return value
        except BaseException:
            # ProviderStop derives from BaseException. Preserve it verbatim,
            # without retaining its message, response body, or credentials.
            reference['value_hash'] = None
            reference['status'] = 'raised'
            raise

    def chat(self, messages, max_completion_tokens=4096):
        payload = {'model': CHAT_MODEL, 'temperature': 1,
                   'max_completion_tokens': max_completion_tokens, 'messages': messages}
        return self._call('chat', payload,
            lambda: self._provider.chat(messages, max_completion_tokens=max_completion_tokens))

    def embed(self, texts):
        self._check_namespace()
        # Preserve the original batch bound. One-element calls expose the exact
        # per-text returned value before a later text can raise; no new requests
        # are introduced because Provider.embed already sends one request/text.
        if not isinstance(texts, list) or not texts or len(texts) > 12:
            raise ProviderStop('Only bounded query embedding batches are supported')
        values = []
        for text in texts:
            if not isinstance(text, str) or not text.strip() or len(text) > 12000:
                raise ProviderStop('Invalid retrieval query')
            payload = {'model': EMBED_MODEL, 'input': [text], 'encoding_format': 'float'}

            def invoke():
                result = self._provider.embed([text])
                if not isinstance(result, list) or len(result) != 1:
                    raise TraceError('underlying_embedding_result_shape_changed')
                return result[0]

            values.append(self._call('embedding', payload, invoke))
        return values
