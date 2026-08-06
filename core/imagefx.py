from PIL import ImageEnhance

from config import CONTRAST
from config import BRIGHTNESS
from config import SHARPNESS


def improve(img):

    img = ImageEnhance.Contrast(img).enhance(CONTRAST)

    img = ImageEnhance.Brightness(img).enhance(BRIGHTNESS)

    img = ImageEnhance.Sharpness(img).enhance(SHARPNESS)

    return img
