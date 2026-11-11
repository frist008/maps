"""Тест maps.py в песочнице (временная копия scripts/, синтетические карты): python -X utf8 scripts/test_maps.py.
Запускать после любых правок maps.py — настоящие папки сессий не трогает."""
import json, os, shutil, subprocess, sys, tempfile
from PIL import Image

SRC = os.path.dirname(os.path.abspath(__file__))  # scripts/ рядом с этим файлом
T = tempfile.mkdtemp(prefix='mapsT_')
shutil.copytree(SRC, os.path.join(T, 'scripts'), ignore=shutil.ignore_patterns('*.js'))
M = [sys.executable, os.path.join(T, 'scripts', 'maps.py')]
fails = []


def run(*a, ok=True):
    r = subprocess.run(M + list(a), capture_output=True, text=True, encoding='utf-8')
    out = r.stdout + r.stderr
    print(f'$ maps.py {" ".join(a)} -> {r.returncode}\n' + ''.join('   ' + l + '\n' for l in out.strip().splitlines()))
    if ok is not None and (r.returncode == 0) != ok:
        fails.append(' '.join(a))
    return out


def img(path, w=200, h=150):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new('RGB', (w, h), 'white').save(path)


def ls(p):
    p = os.path.join(T, p)
    return sorted(os.listdir(p)) if os.path.isdir(p) else None


def check(cond, what):
    print(('  OK  ' if cond else '  FAIL ') + what)
    if not cond:
        fails.append(what)


# --- сессия 27.01: отправная точка, сбора ещё нет
img(f'{T}/27.01/Kherson_26.10.13-26.10.13/26.10.13.png')
img(f'{T}/27.01/_raw/Kherson/26.10.13.png')
run('prune', '27.01', ok=False)
check(ls('27.01/_raw/Kherson') == ['26.10.13.png'], 'prune до сбора не трогает _raw и отправную точку')
check(ls('27.01/Kherson_26.10.13-26.10.13') == ['26.10.13.png'], 'папка отправной точки на месте')

# --- после сбора, но до crop: свежие оригиналы
os.makedirs(f'{T}/27.01/_manifest'); open(f'{T}/27.01/_manifest/2026-10-20.json', 'w').write('{}')
for d in ('26.10.20', '26.10.27', '26.11.05'):
    img(f'{T}/27.01/_raw/Kherson/{d}.png')
img(f'{T}/27.01/_raw/Brand-New-ISW-Name/26.10.20.png')
run('prune', '27.01', ok=False)
check(len(ls('27.01/_raw/Kherson')) == 4, 'prune до crop отказывается')
run('cleanup', '27.01')
check(ls('27.01/_raw/Brand-New-ISW-Name') == ['26.10.20.png'], 'cleanup не удаляет необрезанный _raw нового имени ISW')

# --- crop + prune
run('crop', '27.01')
fs = [d for d in ls('27.01') if d.startswith('Kherson')]
print('  папки Kherson:', fs)
run('ranges', '27.01')
run('prune', '27.01')
check(any(d.startswith('Kherson_') for d in ls('27.01')), 'Kherson (4 карты, 23 дня) остался')
check(ls('27.01/_raw/Brand-New-ISW-Name') is None, 'Brand-New (1 карта) убрана prune, её _raw удалён после crop')

# --- remove с суффиксом и несуществующий день
k = [d for d in ls('27.01') if d.startswith('Kherson_')][0]
img(f'{T}/27.01/{k}/26.11.05_1.png')
run('remove', '27.01', 'Kherson', '26.11.05')
check(sorted(ls('27.01/_removed/Kherson')) == ['26.11.05.png', '26.11.05_1.png'], 'remove берёт и суффиксы')
run('remove', '27.01', 'Kherson', '26.12.31')

# --- split дважды: вторая старая часть докладывается в ту же _old
img(f'{T}/27.01/{[d for d in ls("27.01") if d.startswith("Kherson_")][0]}/26.11.20.png')
img(f'{T}/27.01/{[d for d in ls("27.01") if d.startswith("Kherson_")][0]}/26.10.24.png')
run('ranges', '27.01')
run('split', '27.01', 'Kherson', '26.10.27')
run('split', '27.01', 'Kherson', '26.11.20')
olds = [d for d in ls('27.01') if '_old' in d]
check(len(olds) == 1, f'одна папка _old после двух split: {olds}')

# --- video: _norm не совпадает с папкой
img(f'{T}/27.01/{[d for d in ls("27.01") if "_old" in d][0]}/26.10.01.png')
run('ranges', '27.01')
run('normalize', '27.01', 'Kherson_old')
o = [d for d in ls('27.01') if '_old' in d][0]
os.remove(f'{T}/27.01/{o}/{ls("27.01/" + o)[-1]}')
out = run('video', '27.01', 'Kherson_old', ok=None)
check('_norm не совпадает' in out, 'video отказывается при устаревшем _norm')
run('normalize', '27.01', 'Kherson_old')
run('video', '27.01', 'Kherson_old')
mp4 = [f for f in ls('27.01') if f.endswith('.mp4')]
check(len(mp4) == 1 and '.tmp' not in mp4[0], f'видео собрано, без .tmp: {mp4}')
check(any(d.startswith('+Kherson_old') for d in ls('27.01')), 'папка помечена +')
o2 = run('upload-prep', '27.01')
check('квадрат' in o2, 'upload-prep: широкое видео сразу в квадрат')
o3 = run('upload-prep', '27.01')
check(o3.strip() == '', 'upload-prep: свежая копия не пересобирается')

check(ls('27.01/_removed/Kherson') is not None, '_removed направления цел, пока Kherson (новая часть) без +')


# --- handoff дважды
for d in ('26.01.01', '26.01.20', '26.02.10'):
    img(f'{T}/26.04/+X_26.01.01-26.02.10/{d}.png')
    img(f'{T}/26.04/_raw/X/{d}.png')
run('handoff', '26.04')
run('handoff', '26.04')
check(ls('26.04/+X_26.01.01-26.02.10') == ['26.01.01.png', '26.01.20.png'], 'второй handoff не забрал ещё кадр')
check([d for d in ls('26.07') if d.startswith('X')] == ['X_26.02.10-26.02.10'], 'в 26.07 одна папка X')

# --- merge: манифест обновляется, пустой _raw удаляется
names = json.load(open(f'{T}/scripts/names.json', encoding='utf-8'))
isw = next(k2 for k2, v in names.items() if not k2.startswith('_') and k2 != v)
ours = names[isw]
for d in ('26.03.01', '26.03.10', '26.03.20'):
    img(f'{T}/26.07/{ours}_old/{d}.png'); img(f'{T}/26.07/_raw/{isw}/{d}.png')
os.makedirs(f'{T}/26.07/_manifest', exist_ok=True)
json.dump({'maps': [{'file': f'26.07/_raw/{isw}/26.03.01.png'}]}, open(f'{T}/26.07/_manifest/2026-03-01.json', 'w'))
img(f'{T}/26.07/Target/26.04.01.png')
run('ranges', '26.07')
run('merge', '26.07', 'Target', f'{ours}_old')
mf = json.load(open(f'{T}/26.07/_manifest/2026-03-01.json'))
print('  манифест:', mf)
check(mf['maps'][0].get('merged_into', '').startswith('Target'), 'merge обновил путь в манифесте')
check(ls(f'26.07/_raw/{isw}') is None, 'merge убрал пустой _raw под именем ISW')

# --- ревью-2: повторный crop не возвращает дни split/remove; cleanup не удаляет свежие оригиналы
for d in ('26.01.01', '26.01.08', '26.01.22', '26.02.05', '26.02.12'):
    img(f'{T}/26.10/_raw/Kherson/{d}.png')
os.makedirs(f'{T}/26.10/_manifest'); open(f'{T}/26.10/_manifest/2026-01-01.json', 'w').write('{}')
run('crop', '26.10'); run('ranges', '26.10')
run('split', '26.10', 'Kherson', '26.01.22')
run('remove', '26.10', 'Kherson', '26.02.05')
run('crop', '26.10')
k = [d for d in ls('26.10') if d.startswith('Kherson_') and '_old' not in d][0]
check(ls('26.10/' + k) == ['26.01.22.png', '26.02.12.png'], f'повторный crop не вернул дни: {k} {ls("26.10/" + k)}')
# папка с «+», докачали новый день: crop снимает «+»
os.rename(f'{T}/26.10/{k}', f'{T}/26.10/+{k}')
img(f'{T}/26.10/_raw/Kherson/26.03.01.png')
run('cleanup', '26.10')
check('26.03.01.png' in ls('26.10/_raw/Kherson'), 'cleanup не удалил свежий необрезанный оригинал')
run('crop', '26.10')
check(any(d.startswith('Kherson_') and '_old' not in d for d in ls('26.10')) and not any(d.startswith('+Kherson_') for d in ls('26.10')),
      f'новые дни в папке с + → «+» снят: {ls("26.10")}')
# split в существующую +X_old снимает «+»
o = [d for d in ls('26.10') if '_old' in d][0]
os.rename(f'{T}/26.10/{o}', f'{T}/26.10/+{o}')
run('ranges', '26.10')
run('split', '26.10', 'Kherson', '26.02.12')
check(not any(d.startswith('+') for d in ls('26.10')), f'после split «+» нигде нет: {ls("26.10")}')

# --- ревью-3: video → cleanup оставляет в _raw только кадры видео (+ свежие необрезанные)
import datetime as _dt
days = [(_dt.date(2026, 5, 1) + _dt.timedelta(days=i)).strftime('%y.%m.%d') for i in range(30)]
for d in days:
    img(f'{T}/26.10/_raw/Kharkiv/{d}.png')
run('crop', '26.10'); run('ranges', '26.10'); run('normalize', '26.10', 'Kharkiv')
img(f'{T}/26.10/_raw/Kharkiv/26.07.01.png')   # докачан после normalize, ещё не обрезан
out = run('video', '26.10', 'Kharkiv')
frames = [f for d in ls('26.10') if d.startswith('+Kharkiv') for f in ls('26.10/' + d)]
check(sorted(ls('26.10/_raw/Kharkiv')) == sorted(frames + ['26.07.01.png']),
      f'_raw после video = кадры ({len(frames)}) + свежий: {len(ls("26.10/_raw/Kharkiv"))}')
run('crop', '26.10')
check(any(d.startswith('Kharkiv_') for d in ls('26.10')) and
      len([f for d in ls('26.10') if d.startswith('Kharkiv') and not d.endswith('.mp4') for f in ls('26.10/' + d)]) == len(frames) + 1,
      'повторный crop добавил только новый день, убранные не вернулись')

shutil.rmtree(T)
print('\nИТОГ:', 'всё ок' if not fails else 'ПРОВАЛЫ: ' + '; '.join(fails))
