"""Linear-gradient text rendering helpers."""
from PIL import Image, ImageDraw


def create_linear_gradient(size, colors, direction):
    """
    size: (width, height)
    colors: list of hex colors
    direction: string
    """
    w, h = size
    gradient = Image.new("RGBA", size)
    draw = ImageDraw.Draw(gradient)

    # Convert hex to RGB
    rgb = [tuple(int(c.lstrip("#")[i:i+2], 16) for i in (0, 2, 4)) for c in colors]

    def lerp(c1, c2, t):
        return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))

    steps = max(w, h)

    for i in range(steps):
        t = i / max(steps - 1, 1)
        seg = min(int(t * (len(rgb) - 1)), len(rgb) - 2)
        local_t = (t * (len(rgb) - 1)) - seg
        col = lerp(rgb[seg], rgb[seg + 1], local_t)

        if direction == "left_to_right":
            draw.line([(i, 0), (i, h)], fill=col)
        elif direction == "right_to_left":
            draw.line([(w - i, 0), (w - i, h)], fill=col)
        elif direction == "top_to_bottom":
            draw.line([(0, i), (w, i)], fill=col)
        elif direction == "bottom_to_top":
            draw.line([(0, h - i), (w, h - i)], fill=col)
        elif direction == "diagonal_tl_br":
            draw.line([(i, 0), (0, i)], fill=col)
        elif direction == "diagonal_bl_tr":
            draw.line([(i, h), (w, h - i)], fill=col)

    return gradient


def draw_text_with_gradient(base_img, position, text, font, gradient_cfg, align="left"):
    # Measure text
    dummy = ImageDraw.Draw(base_img)
    bbox = dummy.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Text mask
    mask = Image.new("L", (tw, th), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text((0, 0), text, font=font, fill=255)

    # Gradient image
    gradient = create_linear_gradient(
        (tw, th),
        gradient_cfg["colors"],
        gradient_cfg.get("direction", "left_to_right"),
    )

    # Composite
    x, y = position
    base_img.paste(gradient, (x, y), mask)

