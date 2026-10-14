"""Validate real image content and store it under a unique filename."""
import warnings
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from .storage import LocalStorage, storage_backend_for_folder, valid_image_name

FORMATS = {"PNG": "png", "JPEG": "jpg", "GIF": "gif"}
MAX_IMAGE_BYTES = 3 * 1024 * 1024


def save_image(file, folder, required=False):
    if not file or not file.filename:
        if required:
            raise ValueError("Escolha uma imagem de capa.")
        return None
    if Path(file.filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif"}:
        raise ValueError("Use uma imagem PNG, JPG ou GIF.")
    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > MAX_IMAGE_BYTES:
        raise ValueError("A imagem deve ter até 3 MB. Escolha um arquivo menor.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(file.stream) as image:
                image_format = image.format
                if image_format not in FORMATS or image.width * image.height > 16_000_000:
                    raise ValueError("Imagem inválida ou grande demais (máximo de 16 megapixels).")
                image.verify()
            file.stream.seek(0)
            with Image.open(file.stream) as image:
                image.load()
                clean = ImageOps.exif_transpose(image).convert("RGB" if image_format == "JPEG" else "RGBA")
                filename = f"{uuid4().hex}.{FORMATS[image_format]}"
                output = BytesIO()
                clean.save(output, format=image_format)
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as error:
        raise ValueError("A imagem enviada é inválida. Escolha outro arquivo.") from error
    storage_backend_for_folder(folder).save(filename, output.getvalue(), Image.MIME[image_format])
    return filename


def remove_image(folder, filename):
    if valid_image_name(filename):
        if (Path(folder) / filename).is_file():
            LocalStorage(folder).remove(filename)
        else:
            storage_backend_for_folder(folder).remove(filename)
