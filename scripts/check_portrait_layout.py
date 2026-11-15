"""Is this image a single portrait, or a tiled sheet of several prints?

Settles the question locally and objectively, without sending the file
anywhere and without an AI opinion. Nothing about the image's content is
printed — only geometry and similarity numbers.

    venv\\Scripts\\python.exe scripts\\check_portrait_layout.py "C:\\path\\photo.jpg"

A studio "2x2" order is usually delivered as one sheet holding 4 or 8
identical prints. That is a legitimate thing for a person to have, and it is
also legitimately not a single portrait, so the validator rejects it. This
tells you which one you actually uploaded.
"""
import sys

try:
    from PIL import Image, ImageChops, ImageStat
except ImportError:
    sys.exit("Pillow is required: venv\\Scripts\\python.exe -m pip install Pillow")


def similarity(a, b):
    """0..1, where 1 means the two crops are pixel-identical."""
    a = a.convert("L").resize((96, 96))
    b = b.convert("L").resize((96, 96))
    diff = ImageChops.difference(a, b)
    return 1.0 - (ImageStat.Stat(diff).mean[0] / 255.0)


def tiles(im, cols, rows):
    w, h = im.size
    tw, th = w // cols, h // rows
    return [im.crop((c * tw, r * th, (c + 1) * tw, (r + 1) * th))
            for r in range(rows) for c in range(cols)]


def report(path):
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        print(f"file            : {path}")
        print(f"pixels          : {w} x {h}")
        print(f"aspect ratio    : {w / h:.3f}  "
              f"({'square-ish' if 0.9 <= w / h <= 1.1 else 'not square'})")
        print()

        verdicts = []
        for cols, rows, label in ((2, 2, "2x2 grid"), (2, 1, "side-by-side"),
                                  (1, 2, "stacked"), (4, 2, "4x2 sheet"),
                                  (2, 4, "2x4 sheet")):
            parts = tiles(im, cols, rows)
            scores = [similarity(parts[0], p) for p in parts[1:]]
            worst = min(scores)
            print(f"{label:<14}: panels match first panel at "
                  f"{', '.join(f'{s:.2f}' for s in scores)}  (worst {worst:.2f})")
            verdicts.append((label, worst))

        print()
        best = max(verdicts, key=lambda v: v[1])
        label, score = best
        if score >= 0.92:
            print(f"VERDICT: looks like a TILED SHEET ({label}). The panels are "
                  f"near-identical ({score:.2f}).")
            print("         The rejection is correct. Crop ONE of the prints and")
            print("         upload just that.")
        elif score >= 0.80:
            print(f"VERDICT: AMBIGUOUS. Best repeat pattern is {label} at "
                  f"{score:.2f}.")
            print("         Could be a sheet, could be a plain background that")
            print("         makes panels look alike. Open the file and look.")
        else:
            print(f"VERDICT: looks like a SINGLE image (best repeat only "
                  f"{score:.2f} for {label}).")
            print("         If the validator still calls it a composite, that is")
            print("         a model error worth reporting with this output.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    report(sys.argv[1])
