"""Verify exact inline image payloads at the final provider boundary."""
from contextlib import contextmanager
import hashlib
import threading


class ImageBindingError(ValueError):
    pass


def payload_hash(url):
    if not isinstance(url, str) or not url.startswith('data:image/png;base64,'):
        raise ImageBindingError('bound_inline_png_required')
    return hashlib.sha256(url.encode('ascii')).hexdigest()


class ImageGuard:
    """Wrap the hash-only tracer; never hold labels or image payloads itself.

    Expected hashes are calculated from verified original bytes, not by
    reopening image paths during a stage. This catches a file changed between
    its manifest verification and the encoder reading it.
    """
    def __init__(self, traced):
        self.traced = traced
        self.local = threading.local()

    @contextmanager
    def expect(self, ordered_hashes):
        if getattr(self.local, 'expected', None) is not None:
            raise ImageBindingError('nested_image_expectation')
        self.local.expected = tuple(ordered_hashes)
        try:
            yield
        finally:
            self.local.expected = None

    def mark(self):
        return self.traced.mark()

    def refs_since(self, mark):
        return self.traced.refs_since(mark)

    def chat(self, messages, max_completion_tokens=4096):
        expected = getattr(self.local, 'expected', None)
        if expected is None or not expected:
            raise ImageBindingError('chat_requires_bound_image_stage')
        actual = []
        for message in messages:
            content = message.get('content')
            if isinstance(content, list):
                for block in content:
                    if block.get('type') == 'image_url':
                        actual.append(payload_hash(block.get('image_url', {}).get('url')))
        if tuple(actual) != expected:
            raise ImageBindingError('sent_images_differ_from_frozen_stage')
        return self.traced.chat(messages, max_completion_tokens=max_completion_tokens)

    def embed(self, texts):
        if getattr(self.local, 'expected', None) != ():
            raise ImageBindingError('embedding_requires_nonimage_stage')
        return self.traced.embed(texts)


def expected_images(name, inputs, payloads):
    stage = name.rsplit(':', 1)[-1]
    if stage == 'description':
        proofs = [inputs['image']]
    elif stage == 'rerank':
        proofs = [inputs['query'], *inputs['candidates']]
    elif stage == 'estimate':
        proofs = [*inputs['supports'], inputs['query']]
    elif stage in ('embedding', 'retrieval'):
        proofs = []
    else:
        raise ImageBindingError('unknown_image_stage')
    try:
        return [payloads[proof['image_sha256']] for proof in proofs]
    except KeyError:
        raise ImageBindingError('stage_image_absent_from_bound_manifest') from None
