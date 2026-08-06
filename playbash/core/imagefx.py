from PIL import ImageEnhance

from playbash.core.config import (
    CONTRAST,
    BRIGHTNESS,
    SHARPNESS,
)


def improve(img):

    img = ImageEnhance.Contrast(img).enhance(CONTRAST)

    img = ImageEnhance.Brightness(img).enhance(BRIGHTNESS)

    img = ImageEnhance.Sharpness(img).enhance(SHARPNESS)

    return img
