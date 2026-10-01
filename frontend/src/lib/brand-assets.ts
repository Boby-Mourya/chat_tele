/** The upload UI accepts WebP; the server wire format is a bounded PNG.
 * Canvas strips animation/metadata. The server independently decodes and checks
 * the result; browser checks are usability checks, never the security boundary.
 */
export async function readBrandImage(file: File): Promise<string> {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 350_000) {
    throw new Error('Use a PNG, JPG or WebP image no larger than 350 KB');
  }
  const image = await createImageBitmap(file).catch(() => { throw new Error('The selected image could not be decoded'); });
  try {
    if (!image.width || !image.height || image.width > 2048 || image.height > 2048 || image.width * image.height > 2_000_000) {
      throw new Error('Images must be at most 2048 pixels per side and 2 megapixels');
    }
    const canvas = document.createElement('canvas');
    canvas.width = image.width; canvas.height = image.height;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Image conversion is unavailable in this browser');
    context.drawImage(image, 0, 0);
    const value = canvas.toDataURL('image/png');
    const encoded = value.slice(value.indexOf(',') + 1);
    const bytes = encoded.length * 3 / 4 - (encoded.endsWith('==') ? 2 : encoded.endsWith('=') ? 1 : 0);
    if (!value.startsWith('data:image/png;base64,') || bytes > 350_000) {
      throw new Error('The normalized image exceeds 350 KB. Resize the image and upload it again.');
    }
    return value;
  } finally { image.close(); }
}
