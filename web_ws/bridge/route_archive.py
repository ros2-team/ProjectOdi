"""Atomic per-session map snapshots. Never reads the shared live map on replay."""
import base64
import hashlib
from io import BytesIO
from PIL import Image, ImageDraw
import json
import math
import os
from pathlib import Path
import tempfile
import time

import config


def archive_path(session_id):
    key = hashlib.sha256(session_id.encode('utf-8')).hexdigest()
    return config.DATASET_DIR / 'routes' / (key + '.json')


def load(session_id):
    if not session_id:
        return None
    try:
        data = json.loads(archive_path(session_id).read_text(encoding='utf-8'))
        if data.get('version') in (1, 2) and data.get('session_id') == session_id:
            return data
    except (OSError, ValueError, AttributeError):
        pass
    return None


def composite_png(image_bytes, segments, start, end):
    """Bake the existing map-pixel trail into a PNG; never recompute robot poses."""
    with Image.open(BytesIO(image_bytes)) as source:
        image = source.convert('RGB')
    # Keep thin route lines legible on small occupancy-grid images.
    scale = max(1, min(4, 960 // max(image.size)))
    image = image.resize((image.width*scale, image.height*scale), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(image)
    size = max(image.size) / 100
    def point(p):
        return (round(p[0]*scale), round(p[1]*scale))
    for segment in segments:
        if len(segment) >= 2:
            draw.line([point(p) for p in segment], fill='#d49a24',
                      width=max(2, round(size*.7)), joint='curve')
    for p, color in ((start, '#548b59'), (end, '#c77b28')):
        if p is None:
            continue
        x, y = point(p)
        radius = max(3, round(size*1.3))
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color,
                     outline='white', width=max(1, round(size*.4)))
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def write_png(target, content):
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            name = handle.name
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def save(session_id, view, png, world_path, pose, final=False):
    if not session_id:
        return
    previous = load(session_id)
    if previous and previous.get('complete'):
        return  # A completed diary never changes during later missions.
    path = []
    segments = []
    segment = []
    last = None
    for x, y in world_path:
        if not all(math.isfinite(v) for v in (x, y)):
            last = None
            if segment:
                segments.append(segment); segment = []
            continue
        path.append([x, y])
        px = view.to_px(x, y)
        if not view.inside(px) or (last and math.hypot(x-last[0], y-last[1]) > .75):
            if segment:
                segments.append(segment); segment = []
        if view.inside(px):
            segment.append(px)
        last = (x, y)
    if segment:
        segments.append(segment)
    def point(value):
        if value is None:
            return None
        px = view.to_px(*value)
        return px if view.inside(px) else None
    start = point(path[0]) if path else None
    end = point(pose)
    png_bytes = composite_png(Path(png).read_bytes(), segments, start, end)
    data = dict(version=2, session_id=session_id, complete=bool(final),
        saved_at=time.time(), width=view.width, height=view.height,
        image='data:image/png;base64,'+base64.b64encode(png_bytes).decode('ascii'),
        segments=segments, start=start, end=end,
        world_path=path,
        map_geometry=dict(resolution=view.res, origin_x=view.origin_x,
            origin_y=view.origin_y, origin_yaw=view.origin_yaw,
            grid_height=view.grid_h, crop_x=view.crop_x0, crop_y=view.crop_y0))
    target = archive_path(session_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    # PNG is directly usable outside the app. JSON retains an atomic matching
    # image + metadata checkpoint for reliable replay and restart recovery.
    write_png(target.with_suffix('.png'), png_bytes)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         delete=False) as handle:
            name = handle.name
            json.dump(data, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def public(session_id):
    data = load(session_id)
    if data is None:
        return None
    image = data['image']
    if data['version'] == 1:
        # Compatibility for snapshots saved before raster composition.
        raw = base64.b64decode(image.split(',', 1)[1])
        image = 'data:image/png;base64,' + base64.b64encode(composite_png(
            raw, data['segments'], data['start'], data['end'])).decode('ascii')
    return dict(image=image, complete=data['complete'])
