"""Adapters for public avatars/covers; local files remain readable in S3 mode."""
import re
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import quote, urlsplit

from flask import current_app, has_app_context, has_request_context, url_for

KINDS = {'avatar': ('UPLOAD_FOLDER', 'uploads', 'avatars', 'default-avatar.svg'),
         'cover': ('CAPA_FOLDER', 'cards', 'covers', 'default-cover.svg')}
CONTENT_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif'}


def valid_image_name(filename):
    return (isinstance(filename, str) and 1 <= len(filename) <= 255
            and '/' not in filename and '\\' not in filename and ':' not in filename
            and not any(ord(char) < 32 for char in filename)
            and Path(filename).suffix.lower() in CONTENT_TYPES)


def _url(value, public=False):
    try:
        parsed = urlsplit(value)
        allowed = ('https',) if public else ('http', 'https')
        if (parsed.scheme not in allowed or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or any(char.isspace() or ord(char) < 32 for char in value)):
            raise ValueError('Invalid URL')
        host = parsed.hostname
        if '%' in host:
            raise ValueError('Invalid hostname')
        try:
            ip_address(host)
        except ValueError:
            label = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
            if len(host) > 253 or not re.fullmatch(label + r'(?:\.' + label + r')*\.?', host):
                raise ValueError('Invalid hostname')
        parsed.port  # Reject malformed ports before creating a client or CSP.
    except (ValueError, TypeError):
        raise ValueError('Configure uma URL S3 válida; a URL pública deve usar HTTPS.') from None
    return value.rstrip('/')


def _settings():
    config = current_app.config
    required = ('S3_BUCKET', 'S3_ACCESS_KEY_ID', 'S3_SECRET_ACCESS_KEY', 'S3_PUBLIC_BASE_URL')
    if any(not isinstance(config.get(key), str) or not config[key].strip() for key in required):
        raise ValueError('Configure bucket, credenciais explícitas e URL pública do armazenamento S3.')
    public_base = _url(config['S3_PUBLIC_BASE_URL'], public=True)
    endpoint = config.get('S3_ENDPOINT_URL') or None
    if endpoint:
        endpoint = _url(endpoint)
    prefix = config.get('S3_PREFIX', 'criticard').strip('/')
    if prefix and not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', prefix):
        raise ValueError('Use um prefixo S3 formado por nomes simples de pastas.')
    return {'bucket': config['S3_BUCKET'], 'public_base': public_base, 'endpoint': endpoint,
        'region': config.get('S3_REGION') or 'us-east-1', 'prefix': prefix,
        'access_key': config['S3_ACCESS_KEY_ID'], 'secret_key': config['S3_SECRET_ACCESS_KEY']}


def _client(settings):
    # Explicit credentials prevent accidental ~/.aws / instance-metadata access.
    import boto3
    from botocore.config import Config
    return boto3.client('s3', endpoint_url=settings['endpoint'], region_name=settings['region'],
        aws_access_key_id=settings['access_key'], aws_secret_access_key=settings['secret_key'],
        config=Config(signature_version='s3v4', connect_timeout=3, read_timeout=10,
                      retries={'max_attempts': 2}, s3={'addressing_style': 'path'}))


class LocalStorage:
    def __init__(self, folder):
        self.folder = Path(folder)

    def save(self, filename, data, content_type):
        if not valid_image_name(filename):
            raise ValueError('Nome de imagem inválido.')
        self.folder.mkdir(parents=True, exist_ok=True)
        with (self.folder / filename).open('xb') as output:
            output.write(data)

    def remove(self, filename):
        if valid_image_name(filename):
            (self.folder / filename).unlink(missing_ok=True)


class S3Storage:
    def __init__(self, client, bucket, prefix):
        self.client = client
        self.bucket = bucket
        self.prefix = prefix

    def _key(self, filename):
        if not valid_image_name(filename):
            raise ValueError('Nome de imagem inválido.')
        return '/'.join(part for part in (self.prefix, filename) if part)

    def save(self, filename, data, content_type):
        from botocore.exceptions import BotoCoreError, ClientError
        try:
            self.client.put_object(Bucket=self.bucket, Key=self._key(filename), Body=data,
                ContentType=content_type, CacheControl='public, max-age=31536000, immutable')
        except (BotoCoreError, ClientError) as error:
            raise ValueError('Não foi possível salvar a imagem. Tente novamente.') from error

    def remove(self, filename):
        if valid_image_name(filename):
            self.client.delete_object(Bucket=self.bucket, Key=self._key(filename))


def storage_backend_for_folder(folder):
    if not has_app_context() or current_app.config.get('STORAGE_BACKEND', 'local') == 'local':
        return LocalStorage(folder)
    if current_app.config['STORAGE_BACKEND'] != 's3':
        raise ValueError('Escolha armazenamento local ou S3.')
    kind = next((name for name, values in KINDS.items()
        if Path(folder).resolve() == Path(current_app.config[values[0]]).resolve()), None)
    if kind is None:
        raise ValueError('O armazenamento S3 aceita apenas capas e avatares públicos.')
    settings = _settings()
    prefix = '/'.join(part for part in (settings['prefix'], KINDS[kind][2]) if part)
    return S3Storage(_client(settings), settings['bucket'], prefix)


def _relative_url(endpoint, **values):
    if has_request_context():
        return url_for(endpoint, **values)
    adapter = current_app.url_map.bind('', script_name=current_app.config.get('APPLICATION_ROOT') or '/')
    return adapter.build(endpoint, values, force_external=False)


def image_url(kind, filename):
    if kind not in KINDS:
        raise ValueError('Escolha capa ou avatar.')
    folder_key, static_prefix, remote_prefix, default = KINDS[kind]
    if kind == 'cover':
        from .catalog_images import art_for_marker, static_cover_name
        art = art_for_marker(filename)
        if art:
            return _relative_url('static', filename=art['filename'])
        if isinstance(filename, str) and filename.startswith('catalog-static:'):
            public_file = static_cover_name(filename.removeprefix('catalog-static:'))
            return _relative_url('static', filename=public_file or default)
    if not valid_image_name(filename):
        return _relative_url('static', filename=default)
    local = Path(current_app.config[folder_key]) / filename
    if local.is_file():
        static_folder = Path(current_app.static_folder).resolve() / static_prefix
        if Path(current_app.config[folder_key]).resolve() == static_folder:
            return _relative_url('static', filename=static_prefix + '/' + filename)
        return _relative_url('public_image', kind=kind, filename=filename)
    if current_app.config.get('STORAGE_BACKEND', 'local') == 's3':
        settings = _settings()
        key = '/'.join(part for part in (settings['prefix'], remote_prefix, filename) if part)
        return settings['public_base'] + '/' + quote(key, safe='/')
    return _relative_url('static', filename=default)


def public_image_origin():
    """Return only the configured S3 public origin for the image CSP."""
    if current_app.config.get('STORAGE_BACKEND', 'local') != 's3':
        return None
    parsed = urlsplit(_settings()['public_base'])
    return f'{parsed.scheme}://{parsed.netloc}'


def init_app(app):
    from .catalog_images import art_for_marker
    app.jinja_env.globals['image_url'] = image_url
    app.jinja_env.globals['art_for_marker'] = art_for_marker
    with app.app_context():
        if app.config.get('STORAGE_BACKEND', 'local') == 's3':
            _settings()  # Validate without contacting the bucket or creating a SDK client.
        elif app.config.get('STORAGE_BACKEND', 'local') != 'local':
            raise ValueError('Escolha armazenamento local ou S3.')
