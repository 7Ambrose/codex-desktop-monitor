"""Build the small local dashboard application icon."""
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parent.parent
assets = root / 'assets'; assets.mkdir(exist_ok=True)
icon = Image.new('RGBA', (256, 256))
draw = ImageDraw.Draw(icon)
draw.rounded_rectangle((8, 8, 248, 248), radius=56, fill='#123C3A')
draw.rounded_rectangle((43, 58, 213, 181), radius=18, outline='#E7F4EE', width=10)
draw.line([(67, 128), (98, 128), (116, 96), (138, 151), (155, 120), (187, 120)], fill='#7FE2B1', width=10, joint='curve')
draw.line([(128, 183), (128, 205)], fill='#E7F4EE', width=10)
draw.rounded_rectangle((94, 201, 162, 211), radius=5, fill='#E7F4EE')
icon.save(assets / 'monitor.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
icon.save(assets / 'monitor.png')
print('Monitor icon created.')
