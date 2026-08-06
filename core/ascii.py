from PIL import Image

from core.charset import CHARSETS
from core.imagefx import improve


def frame_to_ascii(frame, width, height, mode):

    charset = CHARSETS[mode]

    # تحويل إطار OpenCV إلى صورة Pillow
    img = Image.fromarray(frame)

    # تحسين الصورة
    img = improve(img)

    # تغيير الحجم ليملأ الطرفية
    img = img.resize(
        (width, height),
        Image.Resampling.LANCZOS
    )

    # تحويل إلى رمادي
    img = img.convert("L")

    pixels = img.load()

    ascii_frame = []

    max_index = len(charset) - 1

    for y in range(height):

        line = []

        for x in range(width):

            gray = pixels[x, y]

            index = gray * max_index // 255

            line.append(charset[index])

        ascii_frame.append("".join(line))

    return ascii_frame
