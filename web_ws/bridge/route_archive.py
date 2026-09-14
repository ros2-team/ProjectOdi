"""Atomic per-session map snapshots. Never reads the shared live map on replay."""
import base64
import hashlib
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
        if data.get('version') == 1 and data.get('session_id') == session_id:
            return data
    except (OSError, ValueError, AttributeError):
        pass
    return None


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
    data = dict(version=1, session_id=session_id, complete=bool(final),
        saved_at=time.time(), width=view.width, height=view.height,
        image='data:image/png;base64,'+base64.b64encode(Path(png).read_bytes()).decode('ascii'),
        segments=segments, start=point(path[0]) if path else None, end=point(pose),
        world_path=path,
        map_geometry=dict(resolution=view.res, origin_x=view.origin_x,
            origin_y=view.origin_y, origin_yaw=view.origin_yaw,
            grid_height=view.grid_h, crop_x=view.crop_x0, crop_y=view.crop_y0))
    target = archive_path(session_id)
    target.parent.mkdir(parents=True, exist_ok=True)
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
    return {k: data[k] for k in ('image', 'width', 'height', 'segments', 'start', 'end', 'complete')}
