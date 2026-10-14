/** Source rectangle for a crop that fills the requested ratio without gaps. */
export function cropRectangle(width, height, ratio, zoom = 1, x = 0.5, y = 0.5) {
    if (![width, height, ratio].every((value) => Number.isFinite(value) && value > 0)) throw new RangeError('Invalid image dimensions');
    zoom = Math.min(3, Math.max(1, Number.isFinite(zoom) ? zoom : 1));
    const cropWidth = Math.min(width, height * ratio) / zoom;
    const cropHeight = cropWidth / ratio;
    const clamp = (value) => Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0.5));
    return {x: (width - cropWidth) * clamp(x), y: (height - cropHeight) * clamp(y), width: cropWidth, height: cropHeight};
}
