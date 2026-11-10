"""Synthetic part images for the demonstration dataset: a shaded render of the generated CAD model.

These stand in for part photographs and are labelled as synthetic renders on the image itself, so they cannot be
mistaken for photographs of a real component. Pure Python + Pillow (painter's algorithm, Lambert shading).
"""
from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw, ImageFilter, ImageFont

LABEL = "SYNTHETIC RENDER - SAMPLE IMAGE, NOT A PHOTOGRAPH"


def _rotate(p, yaw, pitch):
    x, y, z = p
    cy, sy = math.cos(yaw), math.sin(yaw)
    x, y = x * cy - y * sy, x * sy + y * cy
    cp, sp = math.cos(pitch), math.sin(pitch)
    y, z = y * cp - z * sp, y * sp + z * cp
    return x, y, z


def _normal(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    n = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / n, ny / n, nz / n


def render_png(tris, *, title: str, tint=(150, 158, 168), size=(1280, 960), yaw_deg=-35.0, pitch_deg=-62.0, jpeg=True) -> bytes:
    """Render triangles to a studio-style image. Returns JPEG (default) or PNG bytes."""
    ss = 2  # supersampling for smooth edges
    w, h = size[0] * ss, size[1] * ss
    img = Image.new("RGB", (w, h))
    bg = ImageDraw.Draw(img)
    for yy in range(h):  # vertical studio gradient
        t = yy / h
        bg.line([(0, yy), (w, yy)], fill=(int(236 - 40 * t), int(239 - 38 * t), int(243 - 34 * t)))

    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    rot = [tuple(_rotate(p, yaw, pitch) for p in t) for t in tris]
    xs = [p[0] for t in rot for p in t]
    ys = [p[1] for t in rot for p in t]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    scale = 0.62 * min(w, h) / span
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2

    # soft floor shadow
    shadow = Image.new("L", (w, h), 0)
    sd = ImageDraw.Draw(shadow)
    sw = (max(xs) - min(xs)) * scale * 0.55
    sd.ellipse([w / 2 - sw, h * 0.80 - sw * 0.16, w / 2 + sw, h * 0.80 + sw * 0.16], fill=110)
    shadow = shadow.filter(ImageFilter.GaussianBlur(28 * ss))
    img.paste((70, 74, 82), (0, 0), shadow)

    light = _unit((-0.35, 0.55, 0.76))  # key light from above-left (view space)
    fill = _unit((0.6, -0.4, 0.4))
    draw = ImageDraw.Draw(img)
    faces = []
    for t in rot:
        n = _normal(*t)
        if n[2] <= 0:  # back-facing (viewer looks along -z)
            continue
        depth = sum(p[2] for p in t) / 3
        diffuse = max(0.0, sum(a * b for a, b in zip(n, light)))
        rim = max(0.0, sum(a * b for a, b in zip(n, fill))) * 0.25
        spec = max(0.0, n[2]) ** 24 * 0.35
        k = 0.30 + 0.62 * diffuse + rim
        color = tuple(min(255, int(c * k + 255 * spec)) for c in tint)
        pts = [(w / 2 + (p[0] - cx) * scale, h * 0.47 - (p[1] - cy) * scale) for p in t]
        faces.append((depth, pts, color))
    for _, pts, color in sorted(faces, key=lambda f: f[0]):
        draw.polygon(pts, fill=color, outline=color)

    img = img.resize(size, Image.LANCZOS)
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=22)
    small = ImageFont.load_default(size=18)
    d.rectangle([0, size[1] - 46, size[0], size[1]], fill=(178, 34, 34))
    d.text((18, size[1] - 36), LABEL, fill="white", font=font)
    d.text((18, 16), title, fill=(40, 44, 52), font=small)
    out = io.BytesIO()
    if jpeg:
        img.save(out, format="JPEG", quality=88)
    else:
        img.save(out, format="PNG")
    return out.getvalue()


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)
