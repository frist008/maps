"""Обработка карт ISW: обрезка, проверка, разделение, нормализация, выборка, видео.

<YY.MM> — папка сессии: квартал, в котором пользователь пришёл за сбором (26.10 = Q4 2026).
В ней все дни диапазона этой сессии (первый раз — с 1 января 2026), а не только дни квартала.

Структура папки сессии (см. CLAUDE.md):
  <YY.MM>/_raw/<Направление>/<yy.mm.dd>.<ext>   оригиналы с сайта
  <YY.MM>/_manifest/<yyyy-mm-dd>.json           откуда что скачано (по дню)
  <YY.MM>/<Папка>/<yy.mm.dd>.png                 обрезанные карты (то, что проверяет пользователь)
  <YY.MM>/_removed/<Направление>/...              убранные по просьбе пользователя дни (без диапазона и _old)
  <YY.MM>/_norm/<Папка>/<yy.mm.dd>.png            одного размера, для видео
  <YY.MM>/<Папка>.mp4                            видео — рядом с папками, все видео сессии в одном месте

Команды:
  python scripts/maps.py next                          папка текущей сессии и с какого дня собирать
  python scripts/maps.py crop      <YY.MM> [--force]    --force — обрезать заново уже обрезанные
  python scripts/maps.py mark      <YY.MM> [--text FRIST_008 --opacity 0.25]
  python scripts/maps.py check     <YY.MM>
  python scripts/maps.py sheet     <YY.MM> <Папка> [--max 60]   лист миниатюр + поиск смены карты
  python scripts/maps.py split     <YY.MM> <Папка> <yy.mm.dd>
  python scripts/maps.py remove    <YY.MM> <Папка> <yy.mm.dd> [<yy.mm.dd> ...]
  python scripts/maps.py merge     <YY.MM> <Цель> <Папка> [<Папка> ...]   склеить папки в одну
  python scripts/maps.py ranges    <YY.MM>     имена папок -> <Имя>_<первый день>-<последний день>
  python scripts/maps.py prune     <YY.MM> [--force]   убрать папки: < 3 карт или охват < 15 дней
                                                (не идёт, пока есть необрезанные оригиналы или нет сбора)
  python scripts/maps.py handoff   <YY.MM> [--to <след.>]   по последней карте каждого направления -> следующая сессия
  python scripts/maps.py number    <YY.MM>     префикс «NN_» папкам и видео по порядку на YouTube
  python scripts/maps.py cleanup   <YY.MM> [<Папка> ...]   удалить _norm/_removed/лишние _raw готовых направлений, _skipped
  python scripts/maps.py normalize <YY.MM> [<Папка> ...]
  python scripts/maps.py pick      <YY.MM> [<Папка> ...] [--step 7]
  python scripts/maps.py video     <YY.MM> [<Папка> ...] [--step 7 --hold 2 --fade 0.3]   -> <YY.MM>/<Папка>.mp4
"""
import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from croplib import Image, crop_bottom  # noqa: E402
from PIL import ImageDraw, ImageFont  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = "C:/Windows/Fonts/arialbd.ttf"
MARK_SIZE = 0.022   # высота шрифта водяного знака как доля ширины карты
MARK_PAD = 0.012    # отступ от правого и верхнего края как доля ширины
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")
ASPECT_TOL = 0.01  # допустимое расхождение соотношения сторон внутри папки


def qdir(q):
    return os.path.join(ROOT, q)


RANGE_RE = r"_\d\d\.\d\d\.\d\d-\d\d\.\d\d\.\d\d$"  # «_26.01.11-26.10.10» в конце имени папки


def move_keep(src, dst):
    """shutil.move без затирания: если в dst уже есть файл с тем же именем — <имя>_dup<N>.<ext>."""
    root, ext = os.path.splitext(dst)
    k = 1
    while os.path.exists(dst):
        dst = f"{root}_dup{k if k > 1 else ''}{ext}"
        k += 1
    shutil.move(src, dst)
    return dst


def strip_range(folder):
    """Имя папки без диапазона дат в конце."""
    import re
    return re.sub(RANGE_RE, "", folder)


def _load_names():
    import json
    with open(os.path.join(ROOT, "scripts", "names.json"), encoding="utf-8") as fh:
        return {k: v for k, v in json.load(fh).items() if not k.startswith("_")}


NAMES = _load_names()  # имя ISW -> наше имя папки (шаблон — в names.json)


def nice(isw):
    """Наше имя направления по имени ISW (если нет в таблице — как есть, с предупреждением)."""
    if isw not in NAMES:
        print(f"   !! {isw}: нет в scripts/names.json — придумать имя по шаблону, спросить пользователя")
    return NAMES.get(isw, isw)


DONE = "+"  # префикс папки, из которой уже сделано видео (в Windows в именах допустим)


ORDER_RE = r"^\d\d_"  # «01_» — номер в порядке заливки/публикации на YouTube (после «+»)


def key(folder):
    """Имя для сравнения: без «+», без номера «NN_» и без диапазона дат в конце."""
    import re
    return re.sub(ORDER_RE, "", strip_range(folder).lstrip(DONE))


def plain(folder):
    """Имя без «+» в начале (так называются видео и папки в _norm; номер «NN_» остаётся)."""
    return folder.lstrip(DONE)


def base_name(folder):
    """Направление: без «+», диапазона дат и пометки _old (так называется папка в _raw)."""
    return key(folder).split("_old")[0]


def resolve(q, name):
    """Папку можно назвать с диапазоном дат или без него."""
    if os.path.isdir(os.path.join(qdir(q), name)):
        return name
    hits = [d for d in map_folders(q) if key(d) == key(name)]
    if len(hits) != 1:
        sys.exit(f"!! папка {name}: найдено {hits or 'ничего'}")
    return hits[0]


def ranged_name(q, folder):
    """<Имя>_<первый день>-<последний день> по картам в папке."""
    fs = images(os.path.join(qdir(q), folder))
    if not fs:
        return folder
    return f"{strip_range(folder)}_{fs[0][:8]}-{fs[-1][:8]}"


def rename_ranges(q, quiet=False):
    """Привести имена всех папок направлений к виду <Имя>_<первый>-<последний>."""
    for d in map_folders(q):
        if d.startswith(DONE):
            continue  # видео сделано — имя папки = имя видео, не трогаем
        new = ranged_name(q, d)
        if new != d:
            if os.path.exists(os.path.join(qdir(q), new)):
                print(f"   !! {d}: имя {new} уже занято — не переименовано, разобрать вручную (merge)")
                continue
            os.rename(os.path.join(qdir(q), d), os.path.join(qdir(q), new))
            if not quiet:
                print(f"{d} -> {new}")
        elif not os.listdir(os.path.join(qdir(q), d)):
            os.rmdir(os.path.join(qdir(q), d))  # пустую папку убираем


MIN_MAPS = 3    # правило пользователя: в папке минимум 3 карты
MIN_SPAN = 15   # и от первой до последней даты минимум 15 дней


def cmd_prune(a):
    """Папки, где меньше 3 карт или охват дат меньше 15 дней, целиком уезжают в _removed/<Направление>."""
    base = qdir(a.quarter)
    # prune до сбора/обрезки снёс бы отправную точку (папки по 1 карте) и навсегда — _raw (purge_orphans)
    if not a.force:
        if not os.path.isdir(os.path.join(base, "_manifest")):
            sys.exit(f"!! {a.quarter}: сбора ещё не было (нет _manifest) — prune снесёт отправную точку. "
                     f"Сначала сбор и crop (или --force)")
        left = uncropped(a.quarter)
        if left:
            sys.exit(f"!! {a.quarter}: есть необрезанные оригиналы ({len(left)}) — сначала crop (или --force)")
    for d in map_folders(a.quarter):
        if d.startswith(DONE):
            continue  # видео сделано, в папке оставлены только его кадры — не трогать
        fs = images(os.path.join(base, d))
        span = (parse_day(fs[-1]) - parse_day(fs[0])).days if fs else 0
        if len(fs) >= MIN_MAPS and span >= MIN_SPAN:
            continue
        dst = os.path.join(base, "_removed", base_name(d))
        os.makedirs(dst, exist_ok=True)
        for f in fs:
            move_keep(os.path.join(base, d, f), os.path.join(dst, f))
        os.rmdir(os.path.join(base, d))
        print(f"убрана {d}: карт {len(fs)}, охват {span} дн.")
    purge_orphans(a.quarter)


def cmd_ranges(a):
    rename_ranges(a.quarter)


def map_folders(q):
    """Папки направлений квартала (без служебных _raw/_norm/_video/...)."""
    base = qdir(q)
    return sorted(d for d in os.listdir(base)
                  if not d.startswith("_") and os.path.isdir(os.path.join(base, d)))


def images(folder):
    return sorted(f for f in os.listdir(folder) if f.lower().endswith(IMG_EXT))


def parse_day(name):
    # первые 8 символов: у некоторых файлов есть суффикс (_scaled, _1, _1-scaled)
    return dt.datetime.strptime(os.path.splitext(name)[0][:8], "%y.%m.%d").date()


def cmd_next(a):
    """Папка текущей сессии (квартал сегодняшней даты) и начало сбора — день после последнего собранного."""
    import glob
    import re
    today = dt.date.today()
    session = f"{today.year % 100:02d}.{(today.month - 1) // 3 * 3 + 1:02d}"
    sessions = sorted(d for d in os.listdir(ROOT) if re.fullmatch(r"\d\d\.\d\d", d) and os.path.isdir(qdir(d)))
    days = set()
    for f in glob.glob(os.path.join(ROOT, "*", "_manifest", "*.json")):
        if re.fullmatch(r"\d\d\.\d\d", os.path.basename(os.path.dirname(os.path.dirname(f)))):
            days.add(dt.date.fromisoformat(os.path.basename(f)[:-5]))
    last = max(days) if days else None
    if last is None:
        # манифестов нет (папку прошлой сессии удалили): последний день — по картам отправной точки
        mdays = [parse_day(f) for q in sessions for d in map_folders(q) for f in images(os.path.join(qdir(q), d))]
        last = max(mdays) if mdays else None
        if last:
            print(f"!! манифестов нет — последний день взят по картам отправной точки: {last}")
    start = last + dt.timedelta(days=1) if last else dt.date(2026, 1, 1)
    # дыры: дни без манифеста между первым и последним собранным (недокачанные — iswRun их перекачает)
    if days:
        gaps = [min(days) + dt.timedelta(days=i) for i in range((last - min(days)).days)]
        gaps = [g for g in gaps if g not in days]
        if gaps:
            print(f"!! дни без манифеста ({len(gaps)}): {', '.join(g.strftime('%y.%m.%d') for g in gaps[:20])}"
                  f"{' …' if len(gaps) > 20 else ''} — перекачать: iswRun('{gaps[0]}', '{gaps[-1]}', '<сессия этих дней>')")
    # сессия по календарю может не совпасть с той, куда handoff положил отправную точку
    if session in sessions and map_folders(session) and all(d.startswith(DONE) for d in map_folders(session)):
        print(f"!! {session}: все папки уже с «+» (сессия закрыта) — новые карты сюда класть нельзя")
    starts = [q for q in sessions if q != session and map_folders(q)
              and not os.path.isdir(os.path.join(qdir(q), "_manifest"))]
    if starts:
        print(f"!! отправная точка (папки без сбора) лежит в {', '.join(starts)}, а сессия по дате — {session}. "
              f"Решить с пользователем, какую папку брать")
    print(f"сессия: {session}")
    print(f"последний собранный день: {last or '—'}")
    print(f"собирать: iswRun('{start}', '{today}', '{session}')")


def cmd_crop(a):
    raw = os.path.join(qdir(a.quarter), "_raw")
    if not os.path.isdir(raw):
        sys.exit(f"!! {a.quarter}: нет _raw — сначала сбор")
    made = {}   # обрезанный файл -> из какой папки ISW (в этом прогоне)
    by_name = {}
    for d in os.listdir(raw):
        by_name.setdefault(NAMES.get(d, d), []).append(d)
    for name, ds in by_name.items():
        if len(ds) > 1:
            print(f"   !! в одну папку {name} идут разные имена ISW: {', '.join(sorted(ds))} — "
                  f"проверить с пользователем, одна ли это карта (иначе split)")
    for d in sorted(os.listdir(raw)):
        name = nice(d)
        hits = [x for x in map_folders(a.quarter) if key(x) == name]  # уже есть (с датами/«+»)
        # дни, уже разложенные по другим папкам направления (split → _old) или убранные (remove/prune → _removed),
        # повторный crop не возвращает
        elsewhere = {os.path.splitext(f)[0][:8]
                     for x in map_folders(a.quarter) if base_name(x) == name and x not in hits[:1]
                     for f in images(os.path.join(qdir(a.quarter), x))}
        rem = os.path.join(qdir(a.quarter), "_removed", name)
        elsewhere |= {os.path.splitext(f)[0][:8] for f in images(rem)} if os.path.isdir(rem) else set()
        todo = [f for f in images(os.path.join(raw, d)) if os.path.splitext(f)[0][:8] not in elsewhere]
        target = hits[0] if hits else name
        if target.startswith(DONE) and any(not os.path.exists(os.path.join(qdir(a.quarter), target,
                                                                           os.path.splitext(f)[0] + ".png"))
                                           for f in todo):
            # в папку с готовым видео пришли новые дни — видео надо делать заново: снимаем «+» (как split)
            os.rename(os.path.join(qdir(a.quarter), target), os.path.join(qdir(a.quarter), plain(target)))
            print(f"   !! {target}: новые дни — «+» снят, видео надо сделать заново")
            target = plain(target)
        src, dst = os.path.join(raw, d), os.path.join(qdir(a.quarter), target)
        os.makedirs(dst, exist_ok=True)
        print(f"== {d}")
        for f in todo:
            out = os.path.join(dst, os.path.splitext(f)[0] + ".png")
            if out in made:
                print(f"  !! {f}: этот день уже взят из {made[out]} — две разные карты ISW на одну дату, "
                      f"не перезаписано; разобрать с пользователем")
                continue
            made[out] = d
            if os.path.exists(out) and not a.force:
                continue
            im = Image.open(os.path.join(src, f))
            c, cut, ok = crop_bottom(im)
            c.convert("RGB").save(out)
            w, h = im.size
            flag = "" if ok else "   !! легенды нет, не обрезано (норма для макета без легенды)"
            print(f"  {f}: {w}x{h} -> {w}x{cut}  aspect h/w={cut / w:.4f}{flag}")
    rename_ranges(a.quarter)  # новые дни меняют диапазон в имени папки (а по нему потом названо видео)


def raw_for(q, folder, name, strict=False):
    """Оригинал в _raw для обрезанной карты. _raw — под именами ISW; ищем во всех папках ISW,
    которые по scripts/names.json дают это направление (и в папке с нашим именем, если есть).
    Несколько оригиналов на один день (разные карты ISW в одной папке): strict — None, иначе первый."""
    base = base_name(folder)
    stem = os.path.splitext(name)[0]
    cands = dict.fromkeys([isw for isw, n in NAMES.items() if n == base] + [base])
    found = []
    for c in cands:
        raw = os.path.join(qdir(q), "_raw", c)
        if os.path.isdir(raw):
            found += [os.path.join(raw, f) for f in images(raw) if os.path.splitext(f)[0] == stem]
    if len(found) > 1:
        print(f"  !! {folder}/{name}: несколько оригиналов ({', '.join(os.path.relpath(x, qdir(q)) for x in found)})")
        if strict:
            return None
    return found[0] if found else None


def uncropped(q):
    """Оригиналы в _raw, у которых нет обрезанной карты ни в одной папке направления и ни в _removed."""
    root = qdir(q)
    have = {}
    for d in map_folders(q):
        for f in images(os.path.join(root, d)):
            have.setdefault(base_name(d), set()).add(os.path.splitext(f)[0][:8])
    rem = os.path.join(root, "_removed")
    for d in os.listdir(rem) if os.path.isdir(rem) else []:
        for f in images(os.path.join(rem, d)):
            have.setdefault(d, set()).add(os.path.splitext(f)[0][:8])
    out = []
    raw = os.path.join(root, "_raw")
    for d in os.listdir(raw) if os.path.isdir(raw) else []:
        for f in images(os.path.join(raw, d)):
            if os.path.splitext(f)[0][:8] not in have.get(NAMES.get(d, d), set()) | have.get(d, set()):
                out.append(f"{d}/{f}")
    return out


def header_bottom(im):
    """Нижняя граница тёмно-синей шапки у правого края (или None, если шапки нет)."""
    px = im.load()
    x = im.width - 10
    for y in range(5, int(im.height * 0.25)):
        if sum(px[x, y][:3]) > 300:  # кончилась тёмная шапка
            return y if y > im.height * 0.03 else None
    return None


def watermark(im, text, opacity):
    """Малозаметная чёрная надпись справа вверху — у строки с датой в шапке.

    Справа во второй строке шапки всегда пусто, а в первой длинные заголовки
    доходят до края, поэтому знак ставим по низу шапки. Нет шапки — в угол.
    """
    im = im.convert("RGBA")
    w = im.width
    font = ImageFont.truetype(FONT, max(12, int(w * MARK_SIZE)))
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    pad = int(w * MARK_PAD)
    hb = header_bottom(im)
    y = hb - pad - b if hb else pad - t
    d.text((w - pad - r, y), text, font=font, fill=(0, 0, 0, int(255 * opacity)))
    return Image.alpha_composite(im, layer).convert("RGB")


def cmd_mark(a):
    """Заново из _raw: обрезка + водяной знак. Повторный запуск знак не удваивает."""
    for d in map_folders(a.quarter):
        n = 0
        for f in images(os.path.join(qdir(a.quarter), d)):
            src = raw_for(a.quarter, d, f, strict=True)
            if not src:
                print(f"  !! {d}/{f}: нет оригинала в _raw (или их несколько) — не помечено")
                continue
            c, _, _ = crop_bottom(Image.open(src))
            watermark(c, a.text, a.opacity).save(os.path.join(qdir(a.quarter), d, f))
            n += 1
        print(f"== {d}: {n} карт помечено")


def folder_stats(folder):
    rows = []
    for f in images(folder):
        with Image.open(os.path.join(folder, f)) as im:
            w, h = im.size
        rows.append((f, w, h, h / w))
    return rows


def cmd_check(a):
    for d in map_folders(a.quarter):
        rows = folder_stats(os.path.join(qdir(a.quarter), d))
        if not rows:
            continue
        aspects = sorted(r[3] for r in rows)
        med = aspects[len(aspects) // 2]
        print(f"== {d}: {len(rows)} карт, медиана h/w={med:.4f}")
        for f, w, h, asp in rows:
            bad = abs(asp - med) / med > ASPECT_TOL
            print(f"  {f}: {w}x{h} h/w={asp:.4f}{'   !! другое соотношение' if bad else ''}")


def _thumb_sig(path):
    """Грубый «отпечаток» карты: серая миниатюра 48×48 без шапки (где дата/знак)."""
    with Image.open(path) as im:
        w, h = im.size
        g = im.convert("L").crop((0, int(h * 0.12), w, h)).resize((48, 48))
    return list(g.getdata())


def cmd_sheet(a):
    """Лист миниатюр папки для проверки пользователем и подозрительные скачки между соседними днями.

    Скачок = средняя разница отпечатков соседних карт заметно выше обычной для папки
    (другой масштаб/область карты) или другое соотношение сторон.
    """
    a.folder = resolve(a.quarter, a.folder)
    folder = os.path.join(qdir(a.quarter), a.folder)
    files = images(folder)
    if not files:
        sys.exit(f"!! {a.folder}: пустая папка")
    sigs = [_thumb_sig(os.path.join(folder, f)) for f in files]
    diffs = [sum(abs(x - y) for x, y in zip(sigs[i - 1], sigs[i])) / len(sigs[i]) for i in range(1, len(sigs))]
    stats = folder_stats(folder)
    med_d = sorted(diffs)[len(diffs) // 2] if diffs else 0
    asp = sorted(r[3] for r in stats)[len(stats) // 2]
    jumps = []
    for i, dv in enumerate(diffs, start=1):
        if dv > max(5, med_d * 4):
            jumps.append((files[i], round(dv, 1), "резкая смена картинки"))
    for f, w, h, r in stats:
        if abs(r - asp) / asp > ASPECT_TOL:
            jumps.append((f, round(r, 4), f"другое h/w ({w}x{h})"))
    # миниатюры: равномерная выборка + все подозрительные дни и соседние с ними
    keep = set(files[:: max(1, len(files) // a.max)]) | {files[0], files[-1]}
    for f, *_ in jumps:
        i = files.index(f)
        keep |= set(files[max(0, i - 1): i + 1])
    sel = [f for f in files if f in keep]
    tw, th, cols = 240, 270, 8
    rows = (len(sel) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), "white")
    d = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(FONT, 16)
    bad = {f for f, *_ in jumps}
    for k, f in enumerate(sel):
        with Image.open(os.path.join(folder, f)) as im:
            im = im.convert("RGB")
            im.thumbnail((tw - 8, th - 30))
            x, y = (k % cols) * tw + 4, (k // cols) * th + 4
            sheet.paste(im, (x, y + 22))
        d.text((x, y), os.path.splitext(f)[0], font=font, fill=(200, 0, 0) if f in bad else (0, 0, 0))
    out_dir = os.path.join(qdir(a.quarter), "_review")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, a.folder + ".jpg")
    sheet.save(out, quality=85)
    print(f"{a.folder}: {len(files)} карт, {os.path.splitext(files[0])[0]} … {os.path.splitext(files[-1])[0]}, "
          f"на листе {len(sel)}; медиана разницы {med_d:.1f}")
    for f, v, why in jumps:
        print(f"  !! {os.path.splitext(f)[0]}: {why} ({v})")
    print(out)


def cmd_split(a):
    """Дни раньше даты уезжают в <Папка>_old_<первый>-<последний>, новые — <Папка>_<первый>-<последний>."""
    base = qdir(a.quarter)
    a.folder = resolve(a.quarter, a.folder)
    src = os.path.join(base, a.folder)
    cut = parse_day(a.date + ".png")
    old = [f for f in images(src) if parse_day(f) < cut]
    if not old:
        print("нечего переносить")
        return
    # обе части — без «+»: видео надо делать заново; уже есть <Папка>_old — докладываем в неё
    olds = [d for d in map_folders(a.quarter) if key(d) == key(a.folder) + "_old"]
    if olds and olds[0].startswith(DONE):  # в старую часть приходят дни — её видео тоже делать заново
        os.rename(os.path.join(base, olds[0]), os.path.join(base, plain(olds[0])))
        olds[0] = plain(olds[0])
    dst = os.path.join(base, olds[0] if olds else f"{key(a.folder)}_old")
    os.makedirs(dst, exist_ok=True)
    for f in old:
        move_keep(os.path.join(src, f), os.path.join(dst, f))
    print(f"{len(old)} карт -> старая часть")
    if a.folder.startswith(DONE):
        os.rename(src, os.path.join(base, plain(a.folder)))
    rename_ranges(a.quarter)


def cmd_remove(a):
    """Не удаляем навсегда — переносим в _removed/<Направление>."""
    base = qdir(a.quarter)
    a.folder = resolve(a.quarter, a.folder)
    dst = os.path.join(base, "_removed", base_name(a.folder))
    os.makedirs(dst, exist_ok=True)
    for day in a.dates:
        hit = False
        for f in images(os.path.join(base, a.folder)):
            if os.path.splitext(f)[0][:8] == day:  # и с суффиксом: 26.10.17_1.png
                move_keep(os.path.join(base, a.folder, f), os.path.join(dst, f))
                print(f"убрано: {a.folder}/{f}")
                hit = True
        if not hit:
            print(f"!! {day}: в {a.folder} нет такого дня")
    rename_ranges(a.quarter)


def cmd_merge(a):
    """Склеить папки одного направления (ISW переименовал карту) в папку-цель.

    Переносятся и обрезанные карты, и их оригиналы в _raw (содержимое не меняется),
    пути в манифестах обновляются — чтобы `mark` и дальше находил оригиналы.
    Совпадение дат — ошибка, ничего не переносим.
    """
    import glob
    import json
    base = qdir(a.quarter)
    a.sources = [resolve(a.quarter, x) for x in a.sources]
    hits = [d for d in map_folders(a.quarter) if key(d) == key(a.target)]
    a.target = hits[0] if hits else key(a.target)
    plan = []
    taken = {os.path.splitext(f)[0] for f in images(os.path.join(base, a.target))}         if os.path.isdir(os.path.join(base, a.target)) else set()
    for src in a.sources:
        for f in images(os.path.join(base, src)):
            stem = os.path.splitext(f)[0]
            if stem in taken:
                sys.exit(f"!! {stem} уже есть в {a.target} (из {src}) — ничего не перенесено")
            taken.add(stem)
            plan.append((src, f))
    moved_raw = {}
    for src, f in plan:
        os.makedirs(os.path.join(base, a.target), exist_ok=True)
        shutil.move(os.path.join(base, src, f), os.path.join(base, a.target, f))
        raw = raw_for(a.quarter, src, f)
        if raw:
            dst = os.path.join(base, "_raw", base_name(a.target), os.path.basename(raw))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(raw, dst)
            # ключ — путь как в манифесте: оригинал лежит под именем ISW, а не под нашим
            moved_raw[os.path.relpath(raw, ROOT).replace("\\", "/")] = os.path.relpath(dst, ROOT).replace("\\", "/")
    raw_dirs = {os.path.dirname(os.path.join(ROOT, k)) for k in moved_raw}
    for src in a.sources:
        for d in [os.path.join(base, src), os.path.join(base, "_raw", base_name(src)), *raw_dirs]:
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
    for mf in glob.glob(os.path.join(base, "_manifest", "*.json")):
        with open(mf, encoding="utf-8") as fh:
            j = json.load(fh)
        changed = False
        for x in j.get("maps", []):
            if x.get("file") in moved_raw:
                x["file"] = moved_raw[x["file"]]
                x["merged_into"] = a.target
                changed = True
        if changed:
            with open(mf, "w", encoding="utf-8") as fh:
                json.dump(j, fh, ensure_ascii=False, indent=1)
    print(f"{len(plan)} карт -> {a.target} (из {', '.join(a.sources)}); оригиналов перенесено {len(moved_raw)}")
    rename_ranges(a.quarter)


def cmd_normalize(a):
    """Всё в папке приводим к размеру самой маленькой карты (чётные стороны для видео)."""
    base = qdir(a.quarter)
    rename_ranges(a.quarter)  # имя _norm/<Папка> = имя видео: диапазон дат должен быть свежим
    ok_all = True
    for d in [resolve(a.quarter, x) for x in a.folders] or map_folders(a.quarter):
        rows = folder_stats(os.path.join(base, d))
        if not rows:
            continue
        aspects = sorted(r[3] for r in rows)
        med = aspects[len(aspects) // 2]
        bad = [r[0] for r in rows if abs(r[3] - med) / med > ASPECT_TOL]
        if bad:
            ok_all = False
            print(f"!! {d}: другое соотношение сторон у {bad} — пропускаю папку, спросить пользователя")
            continue
        w = min(r[1] for r in rows) // 2 * 2
        h = int(round(w * med)) // 2 * 2
        # _norm — производные файлы: пересоздаём с нуля (и убираем версии со старым диапазоном в имени)
        for old in os.listdir(os.path.join(base, "_norm")) if os.path.isdir(os.path.join(base, "_norm")) else []:
            if key(old) == key(d):
                shutil.rmtree(os.path.join(base, "_norm", old))
        out = os.path.join(base, "_norm", plain(d))
        os.makedirs(out, exist_ok=True)
        for f, *_ in rows:
            with Image.open(os.path.join(base, d, f)) as im:
                im.convert("RGB").resize((w, h), Image.LANCZOS).save(os.path.join(out, f))
        print(f"== {d}: {len(rows)} карт -> {w}x{h}")
    if not ok_all:
        sys.exit(1)


def pick(days, step):
    """Раз в step дней; если нужного дня нет — ближайший после него.

    Следующая цель считается от фактически взятого дня.
    """
    days = sorted(days)
    chosen, i = [], 0
    while i < len(days):
        chosen.append(days[i])
        target = days[i] + dt.timedelta(days=step)
        while i < len(days) and days[i] < target:
            i += 1
    # последний день папки — всегда финальный кадр: даты в имени видео = первый и последний кадр
    if days and chosen[-1] != days[-1]:
        chosen.append(days[-1])
    return chosen


def picked_files(folder, step):
    files = images(folder)
    by_day = {}
    for f in files:
        if parse_day(f) in by_day:
            print(f"   !! {os.path.basename(folder)}: два файла на день — {by_day[parse_day(f)]} и {f}, взят {f}")
        by_day[parse_day(f)] = f
    return [by_day[d] for d in pick(by_day, step)]


def cmd_pick(a):
    base = os.path.join(qdir(a.quarter), "_norm")
    for d in [plain(resolve(a.quarter, x)) for x in a.folders] or sorted(os.listdir(base)):
        sel = picked_files(os.path.join(base, d), a.step)
        print(f"== {d}: {len(sel)} кадров: {', '.join(os.path.splitext(f)[0] for f in sel)}")


def cleanup(q, base):
    """После видео (по просьбе пользователя) удалить навсегда хвосты направления:
    _norm/<папки направления>, _removed/<направление>, а в _raw оставить только оригиналы карт,
    которые лежат в папках направления (т.е. кадры видео). _raw чистим, только если ВСЕ папки
    этого направления уже с «+» — иначе оригиналы ещё нужны для разбора."""
    root = qdir(q)
    folders = [d for d in map_folders(q) if base_name(d) == base]
    for d in os.listdir(os.path.join(root, "_norm")) if os.path.isdir(os.path.join(root, "_norm")) else []:
        if base_name(d) == base and DONE + d in folders:
            shutil.rmtree(os.path.join(root, "_norm", d))
    if not folders or not all(d.startswith(DONE) for d in folders):
        return  # другие папки направления (_old и т.п.) ещё разбираются — их _removed и _raw нужны
    # необрезанные (докачанные после видео) — оставить: манифест дня уже есть, второй раз не скачаются.
    # Считать ДО удаления _removed: иначе убранные видео дни тоже покажутся необрезанными и не удалятся
    fresh = set(uncropped(q))
    rem = os.path.join(root, "_removed", base)
    if os.path.isdir(rem):
        shutil.rmtree(rem)
    keep = {os.path.splitext(f)[0] for d in folders for f in images(os.path.join(root, d))}
    gone = 0
    for c in {isw for isw, n in NAMES.items() if n == base} | {base}:
        raw = os.path.join(root, "_raw", c)
        if not os.path.isdir(raw):
            continue
        for f in images(raw):
            if os.path.splitext(f)[0] not in keep and f"{c}/{f}" not in fresh:
                os.remove(os.path.join(raw, f))
                gone += 1
        if not os.listdir(raw):
            os.rmdir(raw)
    print(f"   очищено: {base} — _norm, _removed, из _raw удалено {gone}")


def purge_orphans(q):
    """Направления, убранные целиком (ни одной папки не осталось): удалить навсегда их _raw и _removed."""
    root = qdir(q)
    active = {base_name(d) for d in map_folders(q)}
    # необрезанные оригиналы (свежий сбор до crop, новое имя ISW) — не сироты, их не трогать
    fresh = {x.split("/")[0] for x in uncropped(q)}
    for sub in ("_raw", "_removed"):
        d0 = os.path.join(root, sub)
        for d in os.listdir(d0) if os.path.isdir(d0) else []:
            if NAMES.get(d, d) not in active and d not in active:
                if sub == "_raw" and d in fresh:
                    print(f"   !! _raw/{d}: есть необрезанные оригиналы — не удаляю (сначала crop)")
                    continue
                shutil.rmtree(os.path.join(d0, d))
                print(f"   удалено: {sub}/{d}")


def next_session(q):
    """Следующая сессия (квартал): 26.10 -> 27.01, 27.01 -> 27.04."""
    y, m = int(q[:2]), int(q[3:])
    return f"{y + 1:02d}.01" if m == 10 else f"{y:02d}.{m + 3:02d}"


def handoff(q, nxt=None):
    """Отправная точка следующей сессии: по одной последней карте каждого направления (и её оригиналу
    из _raw) переносится в папку следующей сессии. Делается, когда сделано последнее видео сессии."""
    nxt = nxt or next_session(q)
    root, dst_root = qdir(q), qdir(nxt)
    latest = {}
    for d in map_folders(q):
        for f in images(os.path.join(root, d)):
            b = base_name(d)
            if b not in latest or parse_day(f) > parse_day(latest[b][1]):
                latest[b] = (d, f)
    have = {key(x) for x in map_folders(nxt)} if os.path.isdir(dst_root) else set()
    for b, (d, f) in sorted(latest.items()):
        if b in have:  # уже перенесено (повторный handoff / пересобрали видео) — второй кадр не забирать
            print(f"   {nxt}/{b}: уже есть — пропущено")
            continue
        raw = raw_for(q, d, f)
        os.makedirs(os.path.join(dst_root, b), exist_ok=True)
        shutil.move(os.path.join(root, d, f), os.path.join(dst_root, b, f))
        if raw:
            rdir = os.path.join(dst_root, "_raw", os.path.basename(os.path.dirname(raw)))
            os.makedirs(rdir, exist_ok=True)
            shutil.move(raw, os.path.join(rdir, os.path.basename(raw)))
        print(f"   {nxt}/{b}: {os.path.splitext(f)[0]} (из {d})")
    rename_ranges(nxt, quiet=True)
    print(f"отправная точка {nxt}: {len(latest)} направлений")


def cmd_handoff(a):
    handoff(a.quarter, a.to)


UPLOAD_MAX = 9_500_000  # байт: браузерный загрузчик принимает < 10 МБ за раз


def cmd_upload_prep(a):
    """Копии видео для заливки: ширина 1080 (больше Shorts всё равно не показывает), CRF подбирается,
    пока файл не станет < 9.5 МБ. Выход — <YY.MM>/_upload/<видео>.mp4 (удалить после заливки)."""
    ffmpeg = shutil.which("ffmpeg") or sys.exit("ffmpeg не найден")
    root = qdir(a.quarter)
    out_dir = os.path.join(root, "_upload")
    os.makedirs(out_dir, exist_ok=True)
    for f in sorted(x for x in os.listdir(root) if x.endswith(".mp4") and not x.endswith(".tmp.mp4")):
        out = os.path.join(out_dir, f)
        if (os.path.exists(out) and os.path.getsize(out) < UPLOAD_MAX and not a.force
                and os.path.getmtime(out) >= os.path.getmtime(os.path.join(root, f))):
            continue  # копия свежее видео — не пересобирать
        w, h, dur = probe(os.path.join(root, f))
        # широкое (w > h) Shorts не примет — сразу квадрат 1080×1080 с чёрными полями (isw-youtube)
        vf = "scale=1080:-2:flags=lanczos" + (",pad=1080:1080:(ow-iw)/2:(oh-ih)/2:black" if w > h else "")
        for crf in range(20, 41, 2):
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", os.path.join(root, f),
                            "-vf", vf, "-c:v", "libx264", "-preset", "slow",
                            "-tune", "stillimage", "-crf", str(crf), "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", out], check=True)
            if os.path.getsize(out) < UPLOAD_MAX:
                break
        warn = []
        if os.path.getsize(out) >= UPLOAD_MAX:
            warn.append("больше 9.5 МБ — загрузчик не примет")
        if dur > SHORTS_MAX:
            warn.append(f"{dur:.0f} с — длиннее {SHORTS_MAX} с, это не будет Shorts")
        print(f"{f}: crf {crf}, {os.path.getsize(out) / 1e6:.1f} МБ, {dur:.1f} с"
              f"{', квадрат' if w > h else ''}{'   !! ' + '; '.join(warn) if warn else ''}")


SHORTS_MAX = 179  # с: Shorts — до 3 минут


def probe(path):
    """Ширина, высота и длительность видео (ffprobe)."""
    ffprobe = shutil.which("ffprobe") or sys.exit("ffprobe не найден")
    out = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "default=nw=1", path],
                         capture_output=True, text=True, check=True).stdout
    v = dict(x.split("=", 1) for x in out.split() if "=" in x)
    return int(v["width"]), int(v["height"]), float(v.get("duration", 0))


def cmd_number(a):
    """Префикс «NN_» к папкам и видео по порядку заливки на YouTube (план <YY.MM>/_youtube_план.json)."""
    import json
    import re
    root = qdir(a.quarter)
    with open(os.path.join(root, "_youtube_план.json"), encoding="utf-8") as fh:
        plan = json.load(fh)
    for p in plan:
        stem = p["file"][:-4]                       # имя видео без номера
        num = f"{p['n']:02d}_"
        for sub, name in (("", stem + ".mp4"), ("_upload", stem + ".mp4")):
            src = os.path.join(root, sub, name)
            if os.path.exists(src):
                os.rename(src, os.path.join(root, sub, num + name))
        hits = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))
                and d.lstrip(DONE) == stem]
        for d in hits:
            os.rename(os.path.join(root, d), os.path.join(root, DONE + num + stem))
        done = os.path.isdir(os.path.join(root, DONE + num + stem))
        print(f"{num}{stem}: {'ok' if hits else 'уже с номером' if done else '!! папки нет'}")


def cmd_cleanup(a):
    bases = {base_name(resolve(a.quarter, x)) for x in a.folders} if a.folders else         {base_name(d) for d in map_folders(a.quarter) if d.startswith(DONE)}
    for b in sorted(bases):
        cleanup(a.quarter, b)
    purge_orphans(a.quarter)
    sk = os.path.join(qdir(a.quarter), "_skipped")
    if os.path.isdir(sk):
        shutil.rmtree(sk)
        print("   _skipped удалена")


def mark_done(q, folder):
    """Пометить папку «+» в начале имени: видео из неё сделано."""
    src = resolve(q, folder)
    if not src.startswith(DONE):
        os.rename(os.path.join(qdir(q), src), os.path.join(qdir(q), DONE + src))
        print(f"   папка помечена: {DONE + src}")


def cmd_video(a):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("ffmpeg не найден в PATH")
    base = os.path.join(qdir(a.quarter), "_norm")
    # видео кладём на уровень выше папок с картинками — в папку сессии: все видео сессии в одном месте
    out_dir = qdir(a.quarter)
    for d in [plain(resolve(a.quarter, x)) for x in a.folders] or sorted(os.listdir(base)):
        sel = picked_files(os.path.join(base, d), a.step)
        fs = images(os.path.join(base, d))
        if len(fs) < MIN_MAPS or (parse_day(fs[-1]) - parse_day(fs[0])).days < MIN_SPAN:
            print(f"!! {d}: меньше {MIN_MAPS} карт или охват < {MIN_SPAN} дн. — видео не делаю")
            continue
        # _norm должен совпадать с папкой: после normalize могли убрать день или переименовать папку
        hits = [x for x in map_folders(a.quarter) if plain(x) == d]
        if not hits or set(fs) != set(images(os.path.join(qdir(a.quarter), hits[0]))):
            print(f"!! {d}: _norm не совпадает с папкой — перезапустить normalize, видео не делаю")
            continue
        out = os.path.join(out_dir, d + ".mp4")
        tmp = out[:-4] + ".tmp.mp4"
        clip = a.hold + a.fade  # каждая картинка: hold секунд целиком + fade на переход
        cmd = [ffmpeg, "-y", "-loglevel", "error"]
        for f in sel:
            cmd += ["-loop", "1", "-framerate", str(a.fps), "-t", f"{clip:.3f}",
                    "-i", os.path.join(base, d, f)]
        if len(sel) == 1:
            filt, last = "[0:v]format=yuv420p[v]", "[v]"
        else:
            parts, prev, length = [], "[0:v]", clip
            for k in range(1, len(sel)):
                lab = f"[x{k}]"
                parts.append(f"{prev}[{k}:v]xfade=transition=fade:duration={a.fade}:"
                             f"offset={length - a.fade:.3f}{lab}")
                prev, length = lab, length + clip - a.fade
            parts.append(f"{prev}format=yuv420p[v]")
            filt, last = ";".join(parts), "[v]"
        cmd += ["-filter_complex", filt, "-map", last, "-r", str(a.fps),
                "-c:v", "libx264", "-crf", "18", "-preset", "medium", tmp]
        subprocess.run(cmd, check=True)
        # имя видео = имя папки: <Имя>_<первый кадр>-<последний кадр>.mp4; прежние версии этого направления
        # убираем только после удачной сборки (упал ffmpeg — старое видео осталось)
        for old in os.listdir(out_dir):
            if old.endswith(".mp4") and not old.endswith(".tmp.mp4") and key(old[:-4]) == key(d):
                os.remove(os.path.join(out_dir, old))
        os.replace(tmp, out)
        dur = len(sel) * a.hold + a.fade
        print(f"== {d}: {len(sel)} кадров, {dur:.1f} с -> {a.quarter}/{d}.mp4"
              f"{f'   !! длиннее {SHORTS_MAX} с — не Shorts' if dur > SHORTS_MAX else ''}")
        # в папке оставляем только кадры видео, остальное — в _removed (оригиналы всё равно в _raw)
        src = os.path.join(qdir(a.quarter), resolve(a.quarter, d))
        dst = os.path.join(qdir(a.quarter), "_removed", base_name(d))
        os.makedirs(dst, exist_ok=True)
        for f in images(src):
            if f not in sel:
                move_keep(os.path.join(src, f), os.path.join(dst, f))
        mark_done(a.quarter, d)
        cleanup(a.quarter, base_name(d))
        if all(x.startswith(DONE) for x in map_folders(a.quarter)):
            nxt = next_session(a.quarter)
            if os.path.isdir(qdir(nxt)) and map_folders(nxt):
                print(f"== все видео сессии готовы; отправная точка в {nxt} уже есть — не переношу")
            else:
                print("== это было последнее видео сессии — переношу отправную точку")
                handoff(a.quarter)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")  # сообщения sys.exit — тоже в UTF-8
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("next")
    p = sub.add_parser("crop"); p.add_argument("quarter"); p.add_argument("--force", action="store_true")
    p = sub.add_parser("mark"); p.add_argument("quarter")
    p.add_argument("--text", default="FRIST_008")
    p.add_argument("--opacity", type=float, default=0.25)  # прозрачность 75%
    p = sub.add_parser("check"); p.add_argument("quarter")
    p = sub.add_parser("sheet"); p.add_argument("quarter"); p.add_argument("folder")
    p.add_argument("--max", type=int, default=60)
    p = sub.add_parser("split"); p.add_argument("quarter"); p.add_argument("folder"); p.add_argument("date")
    p = sub.add_parser("ranges"); p.add_argument("quarter")
    p = sub.add_parser("prune"); p.add_argument("quarter"); p.add_argument("--force", action="store_true")
    p = sub.add_parser("upload-prep"); p.add_argument("quarter"); p.add_argument("--force", action="store_true")
    p = sub.add_parser("handoff"); p.add_argument("quarter"); p.add_argument("--to")
    p = sub.add_parser("number"); p.add_argument("quarter")
    p = sub.add_parser("cleanup"); p.add_argument("quarter"); p.add_argument("folders", nargs="*")
    p = sub.add_parser("merge"); p.add_argument("quarter"); p.add_argument("target"); p.add_argument("sources", nargs="+")
    p = sub.add_parser("remove"); p.add_argument("quarter"); p.add_argument("folder"); p.add_argument("dates", nargs="+")
    p = sub.add_parser("normalize"); p.add_argument("quarter"); p.add_argument("folders", nargs="*")
    p = sub.add_parser("pick"); p.add_argument("quarter"); p.add_argument("folders", nargs="*")
    p.add_argument("--step", type=int, default=7)
    p = sub.add_parser("video"); p.add_argument("quarter"); p.add_argument("folders", nargs="*")
    p.add_argument("--step", type=int, default=7)
    p.add_argument("--hold", type=float, default=2.0)
    p.add_argument("--fade", type=float, default=0.3)
    p.add_argument("--fps", type=int, default=30)
    a = ap.parse_args()
    globals()["cmd_" + a.cmd.replace("-", "_")](a)


if __name__ == "__main__":
    main()
