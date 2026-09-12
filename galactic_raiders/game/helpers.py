"""
Small shared utility functions: numeric clamping, bezier interpolation,
and text rendering with an optional glow effect.
"""

import pygame

from .constants import FONT_NAME


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def bezier_point(p0, p1, p2, p3, t):
    """Cubic bezier interpolation between 4 (x, y) control points."""
    u = 1 - t
    x = (u ** 3) * p0[0] + 3 * (u ** 2) * t * p1[0] + 3 * u * (t ** 2) * p2[0] + (t ** 3) * p3[0]
    y = (u ** 3) * p0[1] + 3 * (u ** 2) * t * p1[1] + 3 * u * (t ** 2) * p2[1] + (t ** 3) * p3[1]
    return x, y


def draw_text(surface, text, size, color, center, bold=True, glow=False):
    font = pygame.font.SysFont(FONT_NAME, size, bold=bold)
    if glow:
        glow_surf = font.render(text, True, color)
        glow_surf.set_alpha(70)
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            r = glow_surf.get_rect(center=(center[0] + ox, center[1] + oy))
            surface.blit(glow_surf, r)
    label = font.render(text, True, color)
    rect = label.get_rect(center=center)
    surface.blit(label, rect)
    return rect


def draw_pixel_title(surface, text, size, color, center, outline_color=(8, 24, 12),
                      skew_px=3, bands=8, glow=True):
    """Chunky 'wireframe CRT' title text: a forward-leaning wordmark
    built by slicing the rendered text into horizontal bands and
    stepping each one sideways -- a smooth per-pixel shear reads too
    clean/analog for this game's blocky pixel-art look, so the stepped
    version is used on purpose to fake a stencil-cut italic. A 1px
    outline pass and a soft glow pass sit underneath the fill (same
    layering trick draw_text() already uses for glow) so the title
    stays legible over a busy scanline/static background."""
    font = pygame.font.SysFont(FONT_NAME, size, bold=True)
    label = font.render(text, True, color)
    w, h = label.get_size()
    band_h = max(1, h // bands)

    def sheared(render_color):
        src = font.render(text, True, render_color)
        out = pygame.Surface((w + skew_px * bands, h), pygame.SRCALPHA)
        for i in range(bands):
            y0 = i * band_h
            y1 = h if i == bands - 1 else y0 + band_h
            if y1 <= y0:
                continue
            band_surf = src.subsurface(pygame.Rect(0, y0, w, y1 - y0))
            # earlier (upper) bands lean further right -> forward-
            # leaning "italic" stack, bottom row stays put
            ox = (bands - 1 - i) * skew_px
            out.blit(band_surf, (ox, y0))
        return out

    if glow:
        glow_surf = sheared(color)
        glow_surf.set_alpha(60)
        for ox, oy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
            r = glow_surf.get_rect(center=(center[0] + ox, center[1] + oy))
            surface.blit(glow_surf, r)

    if outline_color:
        outline_surf = sheared(outline_color)
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2), (-2, 2), (2, -2)):
            r = outline_surf.get_rect(center=(center[0] + ox, center[1] + oy))
            surface.blit(outline_surf, r)

    fill_surf = sheared(color)
    rect = fill_surf.get_rect(center=center)
    surface.blit(fill_surf, rect)
    return rect
