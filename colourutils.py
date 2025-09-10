import colorsys

def hex_to_rgb_tuple(hex_color):
    """#RRGGBB -> (r, g, b)."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def hsv_to_hex(h_deg, s_pct, v_pct):
    h = (h_deg % 360) / 360.0
    s = max(0.0, min(1.0, s_pct / 100.0))
    v = max(0.0, min(1.0, v_pct / 100.0))
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    r_i = int(round(r * 255))
    g_i = int(round(g * 255))
    b_i = int(round(b * 255))
    return f"#{r_i:02x}{g_i:02x}{b_i:02x}"

def is_light(hex_color):
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) > 140