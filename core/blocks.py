"""
Block programs for the visual Stage 0 editor: a data model, validation, and generation of the same Python
the code editor runs (so ScriptRunner executes block programs unchanged).

A program is the content of an endless loop, a list of nodes. Data flows implicitly between blocks through
named values (kinds): camera image, grayscale image, black-and-white image, blob mask, spot position.
"""
import copy
import itertools

# Kind -> (python variable, wording for messages)
KINDS = {
    "color": ("frame", "a camera image"),
    "gray": ("gray", "a grayscale image"),
    "binary": ("binary", "a black-and-white image"),
    "mask": ("mask", "a blob mask"),
    "point": ("spot", "a spot position"),
    "xy": ("x, y", "spot coordinates"),
}
KIND_FIX = {
    "color": "add 'Capture frame' above",
    "gray": "add 'Grayscale' above",
    "binary": "add 'Threshold' above",
    "mask": "add 'Largest blob' above",
    "point": "add 'Spot coordinates' above",
    "xy": "put it inside 'If spot found'",
}

CATEGORY_COLORS = {
    "flow": "#d9962b",
    "image": "#3b82c4",
    "process": "#2f9e6b",
    "detect": "#d36a3a",
    "output": "#b8478a",
}


class BlockDef:
    def __init__(self, title, category, gives=None, needs=(), params=(), container=False, has_else=False,
                 help="", preview=False):
        self.title = title
        self.category = category
        self.gives = gives
        self.needs = needs          # tuple of kinds, or a callable(params) -> tuple
        self.params = params
        self.container = container
        self.has_else = has_else
        self.help = help
        self.preview = preview      # shows a thumbnail of its result


def _int(key, label, lo, hi, default, step=1, unit=""):
    return {"key": key, "label": label, "kind": "int", "min": lo, "max": hi, "default": default, "step": step, "unit": unit}


def _choice(key, label, choices, default):
    return {"key": key, "label": label, "kind": "choice", "choices": choices, "default": default}


_IMAGES = [("frame", "camera image"), ("gray", "grayscale image"), ("binary", "black-and-white image")]
_VAR_KIND = {"frame": "color", "gray": "gray", "binary": "binary"}


def _display_needs(p):
    return tuple(_VAR_KIND[v] for v in (p.get("top"), p.get("bottom")) if v in _VAR_KIND)


BLOCKS = {
    "capture": BlockDef("Capture frame", "image", gives="color", preview=True,
                        help="Takes the latest picture from the camera."),
    "if_frame": BlockDef("If frame received", "flow", needs=("color",), container=True,
                         help="Runs the blocks inside only when the camera delivered a picture."),
    "gray": BlockDef("Grayscale", "process", needs=("color",), gives="gray", preview=True,
                     help="One brightness number per pixel instead of three colours."),
    "blur": BlockDef("Blur", "process", needs=("gray",), gives="gray", preview=True,
                     params=(_int("size", "Size", 1, 31, 5, 2),),
                     help="Smooths the picture to reduce noise. A bigger size smooths more."),
    "threshold": BlockDef("Threshold", "detect", needs=("gray",), gives="binary", preview=True,
                          params=(_int("value", "Brightness", 0, 255, 200),),
                          help="Pixels brighter than the value become white, all the others black."),
    "blobs": BlockDef("Largest blob", "detect", needs=("binary",), gives="mask", preview=True,
                      help="Finds the white areas and keeps only the largest one: the laser spot."),
    "erode": BlockDef("Shrink to a point", "detect", needs=("mask",), gives="mask", preview=True,
                      params=(_int("times", "Repeats", 1, 30, 10),),
                      help="Removes one layer of pixels from the edge, repeatedly, until a single point remains."),
    "coords": BlockDef("Spot coordinates", "detect", needs=("mask",), gives="point",
                       help="Reads the x and y position of the remaining point."),
    "if_spot": BlockDef("If spot found", "flow", needs=("point",), container=True, has_else=True,
                        help="Left: runs when a spot was found. Else: runs when there is no spot."),
    "report": BlockDef("Report spot position", "output", needs=("xy",),
                       help="Sends x and y to the application (the Spot Location panel and the tracking)."),
    "report_none": BlockDef("Report: no spot", "output",
                            help="Tells the application that no spot is visible."),
    "cross": BlockDef("Mark the spot with a cross", "output", needs=("xy", "binary"), gives="binary", preview=True,
                      params=(_int("size", "Size", 5, 100, 40),),
                      help="Draws a cross on the black-and-white image at the spot."),
    "display": BlockDef("Show on screen", "output", needs=_display_needs,
                        params=(_choice("top", "Top", _IMAGES, "frame"),
                                _choice("bottom", "Bottom", [("", "(nothing)")] + _IMAGES, "binary")),
                        help="Shows one or two pictures on the screen, one above the other."),
    "wait": BlockDef("Wait", "flow",
                     params=(_int("ms", "Time", 10, 500, 10, 10, "ms"),),
                     help="Pauses a short moment before the next picture."),
}

PALETTE = [
    ("Camera", ["capture"]),
    ("Preparation", ["gray", "blur"]),
    ("Detection", ["threshold", "blobs", "erode", "coords"]),
    ("Decisions", ["if_frame", "if_spot"]),
    ("Output", ["report", "report_none", "cross", "display"]),
    ("Timing", ["wait"]),
]

_ids = itertools.count(1)


def new_node(btype, params=None):
    d = BLOCKS[btype]
    p = {x["key"]: x["default"] for x in d.params}
    if params:
        p.update(params)
    node = {"id": next(_ids), "t": btype, "p": p}
    if d.container:
        node["c"] = []
        if d.has_else:
            node["e"] = []
    return node


def new_program(exposure_ms=10):
    return {"exposure_ms": exposure_ms, "children": []}


def _renumber(nodes):
    for n in nodes:
        n["id"] = next(_ids)
        _renumber(n.get("c", []))
        _renumber(n.get("e", []))


def from_dict(data):
    """Program from saved JSON (fresh ids). Unknown or broken data gives an empty program."""
    try:
        prog = copy.deepcopy(data)
        _check(prog["children"])
        prog["exposure_ms"] = int(prog.get("exposure_ms", 10))
        _renumber(prog["children"])
        return prog
    except Exception:
        return new_program()


def _check(nodes):
    for n in nodes:
        d = BLOCKS[n["t"]]
        n["p"] = {x["key"]: n.get("p", {}).get(x["key"], x["default"]) for x in d.params}
        n["c"] = n.get("c", []) if d.container else []
        if d.has_else:
            n["e"] = n.get("e", [])
        _check(n.get("c", []))
        _check(n.get("e", []))
    return nodes


def count_nodes(nodes):
    return sum(1 + count_nodes(n.get("c", [])) + count_nodes(n.get("e", [])) for n in nodes)


def needs_of(node):
    d = BLOCKS[node["t"]]
    return d.needs(node["p"]) if callable(d.needs) else d.needs


# ---------- validation ----------
def validate(program):
    """Returns (errors, warnings): errors = {node_id: message}, warnings = [messages about the program as a whole]."""
    errors = {}
    state = {"wait": False}

    def walk(nodes, have):
        have = set(have)
        for n in nodes:
            d = BLOCKS[n["t"]]
            missing = [k for k in needs_of(n) if k not in have]
            if missing:
                k = missing[0]
                errors[n["id"]] = f"'{d.title}' needs {KINDS[k][1]}: {KIND_FIX[k]}."
            if n["t"] == "wait":
                state["wait"] = True
            if d.container:
                inner = set(have)
                if n["t"] == "if_spot":
                    inner.add("xy")
                walk(n["c"], inner)
                if d.has_else:
                    walk(n["e"], set(have))
            if d.gives:
                have.add(d.gives)
                if d.gives == "gray":
                    have.discard("binary")

    walk(program["children"], set())
    warnings = []
    if not program["children"]:
        warnings.append("The program is empty: drag blocks from the left.")
    elif not state["wait"]:
        warnings.append("Add a 'Wait' block: the loop needs a short pause.")
    return errors, warnings


# ---------- code generation ----------
def _gen(nodes, ind, out, probe):
    pad = "    " * ind

    def line(s=""):
        out.append(pad + s if s else "")

    def probed(n, var):
        if probe and BLOCKS[n["t"]].preview:
            line(f"__probe({n['id']}, {var})")

    for n in nodes:
        t, p = n["t"], n["p"]
        if t == "capture":
            line("frame = capture_frame()")
            probed(n, "frame")
        elif t == "if_frame":
            line("if frame is not None:")
            _gen_body(n["c"], ind + 1, out, probe)
        elif t == "gray":
            line("gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)")
            probed(n, "gray")
        elif t == "blur":
            k = int(p["size"]) | 1
            line(f"gray = cv2.GaussianBlur(gray, ({k}, {k}), 0)")
            probed(n, "gray")
        elif t == "threshold":
            line(f"_, binary = cv2.threshold(gray, {int(p['value'])}, 255, cv2.THRESH_BINARY)")
            probed(n, "binary")
        elif t == "blobs":
            line("contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)")
            line("mask = None")
            line("if contours:")
            line("    largest = max(contours, key=cv2.contourArea)")
            line("    mask = np.zeros_like(binary)")
            line("    cv2.drawContours(mask, [largest], -1, 255, -1)")
            probed(n, "mask")
        elif t == "erode":
            line("if mask is not None:")
            line("    kernel = np.ones((3, 3), np.uint8)")
            line(f"    for _ in range({int(p['times'])}):")
            line("        smaller = cv2.erode(mask, kernel)")
            line("        if np.sum(smaller == 255) == 0:")
            line("            break")
            line("        mask = smaller")
            probed(n, "mask")
        elif t == "coords":
            line("spot = None")
            line("if mask is not None:")
            line("    points = np.argwhere(mask == 255)")
            line("    if len(points) > 0:")
            line("        y, x = points[0]")
            line("        spot = (x, y)")
        elif t == "if_spot":
            line("if spot is not None:")
            line("    x, y = spot")
            _gen_body(n["c"], ind + 1, out, probe, keep_empty=False)
            line("else:")
            _gen_body(n["e"], ind + 1, out, probe)
        elif t == "report":
            line("send_location(x, y)")
            line("set_detected_spot(x, y, 255.0)")
        elif t == "report_none":
            line("send_location(-1.0, -1.0)")
            line("set_detected_spot(-1.0, -1.0, 0.0)")
        elif t == "cross":
            line(f"binary = draw_cross_on_location(binary, x, y, size={int(p['size'])})")
            probed(n, "binary")
        elif t == "display":
            if p.get("bottom"):
                line(f"send_to_screen({p['top']}, {p['bottom']})")
            else:
                line(f"send_to_screen({p['top']})")
        elif t == "wait":
            if not probe:
                line(f"time.sleep({max(int(p['ms']), 10) / 1000.0})")


def _gen_body(nodes, ind, out, probe, keep_empty=True):
    start = len(out)
    _gen(nodes, ind, out, probe)
    if len(out) == start:
        out.append("    " * ind + "pass")


def generate_code(program, probe=False):
    """Python text for the program. probe=True gives one loop iteration with __probe(id, value) after image blocks."""
    out = []
    if not probe:
        out += ["import cv2", "import numpy as np", "import time", "",
                f"set_exposure_ms({float(program['exposure_ms'])})", "", "while True:"]
        body_ind = 1
    else:
        body_ind = 0
    _gen_body(program["children"], body_ind, out, probe)
    return "\n".join(out) + "\n"


# ---------- presets ----------
def full_solution(exposure_ms=10):
    p = new_program(exposure_ms)
    n = new_node
    inner = [n("gray"), n("blur"), n("threshold"), n("blobs"), n("erode"), n("coords")]
    spot = n("if_spot")
    spot["c"] = [n("report"), n("cross")]
    spot["e"] = [n("report_none")]
    inner += [spot, n("display")]
    frame_if = n("if_frame")
    frame_if["c"] = inner
    p["children"] = [n("capture"), frame_if, n("wait")]
    return p


# ---------- live preview (thumbnails) ----------
def run_preview(program, frame):
    """Runs one iteration of the program on a frame without side effects; returns {node_id: image or value}."""
    import cv2
    import numpy as np
    out = {}

    def noop(*a, **k):
        return None

    def cross(img, x, y, size=15, thickness=None):
        img = img.copy()
        cv2.line(img, (int(x), int(y) - size), (int(x), int(y) + size), 255, 2)
        cv2.line(img, (int(x) - size, int(y)), (int(x) + size, int(y)), 255, 2)
        return img

    env = {"cv2": cv2, "np": np, "capture_frame": lambda: frame, "send_location": noop,
           "set_detected_spot": noop, "send_to_screen": noop, "draw_cross_on_location": cross,
           "__probe": lambda i, v: out.__setitem__(i, None if v is None else np.asarray(v).copy())}
    try:
        exec(generate_code(program, probe=True), env)
    except Exception:
        pass
    return out
