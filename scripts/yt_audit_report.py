"""Отчёт по снимкам полей YouTube Studio (yt_audit.js / yt_audit_all.js).

python scripts/yt_audit_report.py <папка снимков> [<папка>.md]
По каждому полю: какие значения встречаются и сколько раз; у редких значений — список видео.
Длинные поясняющие тексты разделов сводятся к значению после подсказки (что реально выбрано).
"""
import collections
import json
import os
import sys

SKIP = {"id", "_saved", "Значок: картинка", "ввод:Теги", "бок:Качество видео"}
# разделы, текст которых совпадает с другими полями (значения уже есть как радио/галочка/список)
SECTION_DUP = {"раздел:Плейлисты", "раздел:Теги", "раздел:Лицензия", "раздел:Язык и причина отсутствия субтитров",
               "раздел:Дата и место съемки", "раздел:Комментарии и оценки", "раздел:Использование ИИ",
               "раздел:Автоматическая разбивка на эпизоды", "раздел:Упомянутые или показанные места",
               "раздел:Автоматическое объяснение понятий", "раздел:Ремиксы Shorts"}


def main():
    d = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else d.rstrip("/\\") + ".md"
    snaps = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".json"):
            try:
                snaps.append(json.load(open(os.path.join(d, f), encoding="utf-8")))
            except ValueError:
                print(f"!! {f}: битый JSON — пропущен, снять заново")
    keys = sorted({k for s in snaps for k in s} - SKIP - SECTION_DUP)
    lines = [f"# Сводка полей: {len(snaps)} видео\n"]
    for k in keys:
        vals = collections.defaultdict(list)
        for s in snaps:
            v = s.get(k, "(нет поля)")
            if k == "Описание":
                v = "(пусто)" if not str(v).strip() else "(есть текст)"
            elif k == "Теги":
                v = "(пусто)" if not v else "(есть теги)"
            elif k in ("бок:Видео по теме", "список:Видео по теме"):
                v = v if v in ("Нет", "", "(нет поля)") else "(есть ссылка)"
            elif k == "Название":
                v = "(пусто)" if not v else ("(длиннее 100)" if len(v) > 100 else "(есть)")
            vals[str(v)[:120]].append(s["id"] + " " + s.get("Название", "")[:50])
        lines.append(f"\n## {k}")
        for v, ids in sorted(vals.items(), key=lambda x: -len(x[1])):
            lines.append(f"- {len(ids)} × «{v}»")
            if len(ids) <= 40 and len(vals) > 1:
                lines += [f"    - {i}" for i in ids]
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(out, len(snaps))


if __name__ == "__main__":
    main()
