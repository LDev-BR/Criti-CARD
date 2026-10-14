"""Exercise public image storage without contacting any real bucket."""
import importlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, PngImagePlugin
from werkzeug.datastructures import FileStorage

from criticard.uploads import remove_image, save_image


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(('put', kwargs))
        self.objects[(kwargs['Bucket'], kwargs['Key'])] = kwargs['Body']
        return {'ETag': 'fake-etag'}

    def delete_object(self, **kwargs):
        self.calls.append(('delete', kwargs))
        self.objects.pop((kwargs['Bucket'], kwargs['Key']), None)
        return {}


def picture():
    content = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('Untrusted', 'metadata-that-must-be-removed')
    Image.new('RGBA', (12, 10), '#c5a46d').save(content, format='PNG', pnginfo=metadata)
    content.seek(0)
    return FileStorage(stream=content, filename='cover.png', content_type='application/octet-stream')


def storage_module():
    try:
        return importlib.import_module('criticard.storage')
    except ModuleNotFoundError:
        pytest.fail('Public image storage adapter is not implemented yet')


@pytest.fixture
def remote_storage(app, monkeypatch):
    fake = FakeS3()
    options = []
    def client(service, **kwargs):
        assert service == 's3'
        options.append(kwargs)
        return fake
    monkeypatch.setitem(sys.modules, 'boto3', SimpleNamespace(client=client))
    app.config.update(STORAGE_BACKEND='s3', S3_BUCKET='test-public-images',
        S3_ENDPOINT_URL='https://storage.example.test', S3_REGION='us-east-1',
        S3_ACCESS_KEY_ID='test-only-key', S3_SECRET_ACCESS_KEY='test-only-secret',
        S3_PUBLIC_BASE_URL='https://cdn.example.test/images', S3_PREFIX='criticard')
    return fake, options


def test_remote_upload_receives_clean_pillow_bytes_and_rollback_removes_same_object(app, remote_storage):
    fake, options = remote_storage
    with app.app_context():
        filename = save_image(picture(), app.config['CAPA_FOLDER'], required=True)
        key = ('test-public-images', 'criticard/covers/' + filename)
        assert key in fake.objects
        assert not (Path(app.config['CAPA_FOLDER']) / filename).exists()
        with Image.open(io.BytesIO(fake.objects[key])) as cleaned:
            assert cleaned.size == (12, 10)
            assert 'Untrusted' not in cleaned.info
        assert fake.calls[0][1]['ContentType'] == 'image/png'
        assert options[0]['aws_access_key_id'] == 'test-only-key'
        assert options[0]['aws_secret_access_key'] == 'test-only-secret'
        assert options[0]['endpoint_url'] == 'https://storage.example.test'
        remove_image(app.config['CAPA_FOLDER'], filename)
        assert key not in fake.objects
        assert fake.calls[-1][0] == 'delete'


def test_public_image_url_keeps_legacy_local_files_and_escapes_remote_names(app, remote_storage):
    storage = storage_module()
    cover_folder = Path(app.config['CAPA_FOLDER'])
    Image.new('RGB', (12, 10), '#c5a46d').save(cover_folder / 'legacy.png', format='PNG')
    with app.test_request_context():
        local_url = storage.image_url('cover', 'legacy.png')
        assert local_url == '/media/cover/legacy.png'
        assert storage.image_url('cover', 'remote cover.png') == 'https://cdn.example.test/images/criticard/covers/remote%20cover.png'
        assert storage.image_url('avatar', None) == '/static/default-avatar.svg'
        assert storage.image_url('cover', '../unsafe.png') == '/static/default-cover.svg'
        assert storage.image_url('avatar', '..\\unsafe.png') == '/static/default-avatar.svg'
        assert storage.public_image_origin() == 'https://cdn.example.test'
    response = app.test_client().get(local_url)
    assert response.status_code == 200 and response.mimetype == 'image/png'
    with Image.open(io.BytesIO(response.data)) as actual:
        assert actual.size == (12, 10)
    csp = response.headers['Content-Security-Policy']
    assert "img-src 'self' blob: data: https://cdn.example.test;" in csp
    assert "script-src 'self';" in csp


@pytest.mark.parametrize('prefix', ['/', '/criticard'])
def test_image_urls_without_request_are_relative_and_preserve_application_root(app, prefix):
    storage = storage_module()
    app.config['APPLICATION_ROOT'] = prefix
    expected = '' if prefix == '/' else prefix
    with app.app_context():
        assert storage.image_url('avatar', None) == expected + '/static/default-avatar.svg'
        filename = save_image(picture(), app.config['CAPA_FOLDER'], required=True)
        assert storage.image_url('cover', filename) == expected + '/media/cover/' + filename


def test_local_images_are_clean_and_adapter_refuses_path_traversal(app, tmp_path):
    storage = storage_module()
    with app.test_request_context():
        filename = save_image(picture(), app.config['UPLOAD_FOLDER'])
        uploaded = Path(app.config['UPLOAD_FOLDER']) / filename
        assert uploaded.is_file()
        local_url = storage.image_url('avatar', filename)
        assert local_url == '/media/avatar/' + filename
        assert storage.image_url('cover', None) == '/static/default-cover.svg'
        assert storage.public_image_origin() is None
        outside = tmp_path / 'outside.png'
        outside.write_bytes(b'keep')
        remove_image(app.config['UPLOAD_FOLDER'], '../outside.png')
        assert outside.read_bytes() == b'keep'
    response = app.test_client().get(local_url)
    assert response.status_code == 200 and response.mimetype == 'image/png'
    with Image.open(io.BytesIO(response.data)) as actual:
        assert actual.size == (12, 10) and 'Untrusted' not in actual.info
    response.close()
    with app.app_context():
        remove_image(app.config['UPLOAD_FOLDER'], filename)
        assert not uploaded.exists()


def test_s3_does_not_read_ambient_credentials_when_explicit_settings_are_missing(app, remote_storage):
    fake, options = remote_storage
    app.config['S3_ACCESS_KEY_ID'] = ''
    with app.app_context():
        with pytest.raises(ValueError, match='S3'):
            save_image(picture(), app.config['CAPA_FOLDER'])
    assert not options and not fake.calls


@pytest.mark.parametrize('base', ['javascript:alert(1)', 'https://cdn.example.test/a?token=secret',
    'https://user:pass@cdn.example.test', 'https://cdn.example.test;script-src/images',
    'https://cdn.example.test\"/images', "https://cdn.example.test'/images"])
def test_invalid_public_origin_is_rejected_before_upload(app, remote_storage, base):
    fake, _ = remote_storage
    app.config['S3_PUBLIC_BASE_URL'] = base
    with app.app_context():
        with pytest.raises(ValueError):
            save_image(picture(), app.config['CAPA_FOLDER'])
    assert not fake.objects


def test_invalid_image_never_reaches_remote_store(app, remote_storage):
    fake, _ = remote_storage
    image = FileStorage(stream=io.BytesIO(b'not an image'), filename='cover.png')
    with app.app_context():
        with pytest.raises(ValueError, match='inválida'):
            save_image(image, app.config['CAPA_FOLDER'])
    assert not fake.calls
