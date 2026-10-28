"""Regression: cold requests must never load an old CDN-cached database."""
import hashlib

import httpx
import pytest

from dealdesk import cloud
from dealdesk.models import Lead


@pytest.fixture
def remote(monkeypatch):
    blobs = {}
    cached_downloads = {}
    monkeypatch.setenv('BLOB_READ_WRITE_TOKEN', 'vercel_blob_rw_teststore_not-a-real-secret')

    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url, params=None, headers=None):
            if url == cloud._API:
                key = params['url']
                if key not in blobs:
                    return httpx.Response(404)
                data, kind, etag = blobs[key]
                return httpx.Response(200, json={'url':'https://teststore.private.blob.vercel-storage.com/'+key,'etag':etag,'contentType':kind})
            key = url.split('.vercel-storage.com/')[1]
            # Delivery caches never refresh overwritten paths in this test.
            cached_downloads.setdefault(key, blobs[key][0])
            return httpx.Response(200, content=cached_downloads[key])

    def put(url, *, params, headers, content, **kwargs):
        key = params['pathname']
        old = blobs.get(key)
        if old and (headers['x-allow-overwrite']=='0' or headers.get('x-if-match') != old[2]):
            return httpx.Response(412)
        etag = hashlib.sha256(content).hexdigest()
        blobs[key] = (content, headers['x-content-type'], etag)
        return httpx.Response(200, json={'etag':etag})

    monkeypatch.setattr(cloud.httpx, 'Client', Client)
    monkeypatch.setattr(cloud.httpx, 'put', put)
    return blobs


def test_fresh_requests_preserve_writes_even_with_stale_delivery_cache(remote):
    def first(s):
        with s.connection() as con:
            con.execute('CREATE TABLE web_requests(id TEXT PRIMARY KEY)')
            con.execute("INSERT INTO web_requests VALUES('reserved')")
    cloud.operation(first, write=True)
    assert cloud.operation(lambda s:s.rows('SELECT * FROM web_requests')) == [{'id':'reserved'}]
    cloud.operation(lambda s:s.add_lead(Lead(id='fresh',name='Test customer',company='Test studio',email='test@example.com',enquiry='We need a website.')),write=True)
    assert cloud.operation(lambda s:s.lead('fresh').name) == 'Test customer'
    assert cloud.operation(lambda s:s.rows('SELECT * FROM web_requests')) == [{'id':'reserved'}]


def test_stale_writer_cannot_replace_newer_saved_state(remote):
    cloud.operation(lambda s:None,write=True)
    snapshot = cloud.BlobSnapshot('vercel_blob_rw_teststore_not-a-real-secret')
    old, etag = snapshot.load()
    cloud.operation(lambda s:s.save_lead(s.lead('L001').model_copy(update={'opted_out':True})),write=True)
    with pytest.raises(cloud.StorageConflict):
        snapshot.save(old,etag)
    assert cloud.operation(lambda s:s.lead('L001').opted_out)
