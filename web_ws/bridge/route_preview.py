"""Explicitly synthetic diary map for the robot-free preview only."""
import base64
from io import BytesIO
from PIL import Image, ImageDraw


def sample_route():
    image = Image.new('RGB', (480, 300), '#eeeade')
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 25, 450, 275), fill='#fffdf6', outline='#49483f', width=6)
    draw.line([(225, 25), (225, 110)], fill='#49483f', width=6)
    draw.line([(225, 190), (225, 275)], fill='#49483f', width=6)
    buffer = BytesIO(); image.save(buffer, format='PNG')
    route = dict(image='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),
        width=480, height=300, segments=[[[85,220],[85,150],[160,145],[300,145],
            [375,95],[390,220],[295,215],[280,150],[155,155],[110,220]]],
        start=[85,220], end=[110,220], complete=True)

    from bridge.route_archive import composite_png
    png = composite_png(buffer.getvalue(), route['segments'], route['start'], route['end'])
    return dict(image='data:image/png;base64,'+base64.b64encode(png).decode(), complete=True)
