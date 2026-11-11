"""Обрезка нижней легенды у карт ISW.

С 2026 года под картой идёт легенда в рамке; её высота разная у разных карт и дней,
поэтому её срезаем, чтобы форм-фактор не плясал. Сама карта (вместе с мини-картой
в правом нижнем углу и подписями авторов поверх карты) остаётся целой.

Граница карты и легенды — тёмная горизонтальная линия почти во всю ширину.
Если такой линии нет (макет 2025 года без легенды), картинка не обрезается.
"""
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

DARK = 100          # порог "тёмного" пикселя (максимум по RGB)
FULL = 0.95         # линия рамки занимает не меньше 95% ширины
SEARCH = 0.40       # рамка легенды лежит в нижних 40% картинки
EDGE = 0.01         # нижний край кадра (своя рамка картинки) пропускаем


def _dark(p):
    r, g, b = p
    # чёрный/серый, а не тёмно-красные линии укреплений
    return max(r, g, b) < DARK and max(r, g, b) - min(r, g, b) < 40


def _full_line(px, y, w):
    """Строка y — тёмная линия почти во всю ширину (с допуском на разрывы в 2 px)."""
    dark = sum(1 for x in range(w) if _dark(px[x, y]))
    return dark >= w * FULL


def find_legend_top(im):
    """Возвращает y верхней линии рамки легенды или None."""
    g = im.convert("RGB")
    w, h = g.size
    px = g.load()
    y = h - 1 - int(h * EDGE)
    while y > int(h * (1 - SEARCH)):
        if _full_line(px, y, w):
            # поднимаемся до первой строки этой (толстой) линии
            while y - 1 > 0 and _full_line(px, y - 1, w):
                y -= 1
            return y
        y -= 1
    return None


def crop_bottom(im):
    """Возвращает (обрезанная картинка, y обрезки, нашли_ли_легенду)."""
    w, h = im.size
    y = find_legend_top(im)
    if y is None:
        return im, h, False
    return im.crop((0, 0, w, y)), y, True
