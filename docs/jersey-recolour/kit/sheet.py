"""python3 docs/jersey-recolour/kit/sheet.py -- before | v1 | v2 | a native teammate, one row per player."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

R = Path(__file__).resolve().parent.parent
IMG = Path('d12ball/images/player_images')
ROWS = [('Quantor', 'purple', 'Quillon'), ('Gearclaw', 'black', 'Slitheron'),
        ('Ozul', 'teal', 'Strider'), ('Hellguard', 'purple', 'Dravox'),
        ('Kindlefinger', 'teal', 'Pulsar'), ('Zenith', 'teal', 'Bulwark'),
        ('Umbrik', 'black', 'Shpritz')]
H, PAD, TOP = 340, 14, 34
BG = (43, 45, 49)
font = ImageFont.truetype('d12ball/fonts/RobotoSlab-Bold.ttf', 22)

def fit(path):
    im = Image.open(path).convert('RGBA')
    return im.resize((round(im.width * H / im.height), H), Image.LANCZOS)

rows = []
for name, kit, native in ROWS:
    v2 = R / 'v2/out' / (f'{name}_{kit}_foot.png' if name == 'Zenith' else f'{name}_{kit}.png')
    rows.append([(f'{name} before', fit(IMG / f'{name}.png')),
                 (f'{name} v1', fit(R / 'v1/out' / f'{name}_{kit}.png')),
                 (f'{name} v2', fit(v2)),
                 (f'{native} (native {kit})', fit(IMG / f'{native}.png'))])
widths = [max(r[k][1].width for r in rows) for k in range(4)]
sheet = Image.new('RGBA', (sum(widths) + PAD * 5, len(rows) * (H + TOP + PAD) + PAD), BG)
d = ImageDraw.Draw(sheet)
for i, row in enumerate(rows):
    y, x = PAD + i * (H + TOP + PAD), PAD
    for k, (label, im) in enumerate(row):
        d.text((x, y), label, fill='white', font=font)
        sheet.alpha_composite(im, (x, y + TOP))
        x += widths[k] + PAD
sheet.convert('RGB').save(R / 'v1_vs_v2.png', optimize=True)
print(sheet.size)
