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
    "setup": "#8b6fd1",
    "flow": "#e0a43a",
    "image": "#4a90d9",
    "process": "#3fb27f",
    "detect": "#e07b4a",
    "output": "#c9559a",
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
        self.preview = preview      # has a 'Screen' checkbox: can send its picture to the screen


def _int(key, label, lo, hi, default, step=1, unit=""):
    return {"key": key, "label": label, "kind": "int", "min": lo, "max": hi, "default": default, "step": step, "unit": unit}


def _choice(key, label, choices, default):
    return {"key": key, "label": label, "kind": "choice", "choices": choices, "default": default}


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
    "report": BlockDef("Report position", "output", needs=("xy",),
                       help="Sends x and y to the application (the Spot Location panel and the tracking)."),
    "report_none": BlockDef("Report: no spot", "output",
                            help="Tells the application that no spot is visible."),
    "cross": BlockDef("Cross on spot", "output", needs=("xy", "binary"), gives="binary", preview=True,
                      params=(_int("size", "Size", 5, 100, 40),),
                      help="Draws a cross on the black-and-white image at the spot."),
    "wait": BlockDef("Wait", "flow",
                     params=(_int("ms", "Time", 10, 500, 10, 10, "ms"),),
                     help="Pauses a short moment before the next picture."),
}

PALETTE = [
    ("Camera", ["capture"]),
    ("Preparation", ["gray", "blur"]),
    ("Detection", ["threshold", "blobs", "erode", "coords"]),
    ("Decisions", ["if_frame", "if_spot"]),
    ("Output", ["report", "report_none", "cross"]),
    ("Timing", ["wait"]),
]

_ids = itertools.count(1)


def new_node(btype, params=None):
    d = BLOCKS[btype]
    p = {x["key"]: x["default"] for x in d.params}
    if params:
        p.update(params)
    node = {"id": next(_ids), "t": btype, "p": p}
    if d.preview:
        node["show"] = False
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
        _limit_shown(prog["children"], [MAX_SHOWN])
        prog["exposure_ms"] = int(prog.get("exposure_ms", 10))
        _renumber(prog["children"])
        return prog
    except Exception:
        return new_program()


def _check(nodes):
    nodes[:] = [n for n in nodes if n.get("t") in BLOCKS]   # blocks removed from the editor are dropped
    for n in nodes:
        d = BLOCKS[n["t"]]
        n["p"] = {x["key"]: n.get("p", {}).get(x["key"], x["default"]) for x in d.params}
        if d.preview:
            n["show"] = bool(n.get("show"))
        n["c"] = n.get("c", []) if d.container else []
        if d.has_else:
            n["e"] = n.get("e", [])
        _check(n.get("c", []))
        _check(n.get("e", []))
    return nodes


MAX_SHOWN = 2


def count_shown(nodes):
    return sum(bool(n.get("show")) + count_shown(n.get("c", [])) + count_shown(n.get("e", [])) for n in nodes)


def _limit_shown(nodes, left):
    for n in nodes:
        if n.get("show"):
            if left[0] > 0:
                left[0] -= 1
            else:
                n["show"] = False
        _limit_shown(n.get("c", []), left)
        _limit_shown(n.get("e", []), left)


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
_SHOW_VAR = {"capture": "frame", "gray": "gray", "blur": "gray", "threshold": "binary", "blobs": "mask",
             "erode": "mask", "cross": "binary"}


def _gen(nodes, ind, out, any_show):
    pad = "    " * ind

    def line(s=""):
        out.append(pad + s if s else "")

    def shown(n):
        if n.get("show"):
            var = _SHOW_VAR[n["t"]]
            line(f"if {var} is not None:")
            line(f"    screen[{n['slot']}] = {var}.copy()")

    for n in nodes:
        t, p = n["t"], n["p"]
        if t == "capture":
            line("frame = capture_frame()")
            shown(n)
        elif t == "if_frame":
            line("if frame is not None:")
            _gen_body(n["c"], ind + 1, out, any_show)
        elif t == "gray":
            line("gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)")
            shown(n)
        elif t == "blur":
            k = int(p["size"]) | 1
            line(f"gray = cv2.GaussianBlur(gray, ({k}, {k}), 0)")
            shown(n)
        elif t == "threshold":
            line(f"_, binary = cv2.threshold(gray, {int(p['value'])}, 255, cv2.THRESH_BINARY)")
            shown(n)
        elif t == "blobs":
            line("contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)")
            line("mask = None")
            line("if contours:")
            line("    largest = max(contours, key=cv2.contourArea)")
            line("    mask = np.zeros_like(binary)")
            line("    cv2.drawContours(mask, [largest], -1, 255, -1)")
            shown(n)
        elif t == "erode":
            line("if mask is not None:")
            line("    kernel = np.ones((3, 3), np.uint8)")
            line(f"    for _ in range({int(p['times'])}):")
            line("        smaller = cv2.erode(mask, kernel)")
            line("        if np.sum(smaller == 255) == 0:")
            line("            break")
            line("        mask = smaller")
            shown(n)
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
            _gen_body(n["c"], ind + 1, out, any_show)
            line("else:")
            _gen_body(n["e"], ind + 1, out, any_show)
        elif t == "report":
            line("send_location(x, y)")
            line("set_detected_spot(x, y, 255.0)")
        elif t == "report_none":
            line("send_location(-1.0, -1.0)")
            line("set_detected_spot(-1.0, -1.0, 0.0)")
        elif t == "cross":
            line(f"binary = draw_cross_on_location(binary, x, y, size={int(p['size'])})")
            shown(n)
        elif t == "wait":
            if any_show:
                line("if any(s is not None for s in screen):")
                line("    ref = next(s for s in screen if s is not None)")
                line("    send_to_screen(*[s if s is not None else np.zeros(ref.shape[:2], np.uint8) for s in screen])")
            line(f"time.sleep({max(int(p['ms']), 10) / 1000.0})")


def _gen_body(nodes, ind, out, any_show):
    start = len(out)
    _gen(nodes, ind, out, any_show)
    if len(out) == start:
        out.append("    " * ind + "pass")


def _assign_slots(nodes, counter):
    """Each ticked block gets a fixed place on the screen, so a block that did not run (no spot) leaves a black picture."""
    for n in nodes:
        if n.get("show"):
            n["slot"] = counter[0]
            counter[0] += 1
        _assign_slots(n.get("c", []), counter)
        _assign_slots(n.get("e", []), counter)


def generate_code(program):
    """Python text for the program (what ScriptRunner executes). Blocks ticked 'Screen' are sent to the screen."""
    any_show = count_shown(program["children"]) > 0
    _assign_slots(program["children"], [0])
    out = ["import cv2", "import numpy as np", "import time", "",
           f"set_exposure_ms({float(program['exposure_ms'])})", "", "while True:"]
    if any_show:
        out.append(f"    screen = [None] * {count_shown(program['children'])}")
    _gen_body(program["children"], 1, out, any_show)
    return "\n".join(out) + "\n"


# ---------- presets ----------
def full_solution(exposure_ms=10):
    p = new_program(exposure_ms)
    n = new_node
    cap = n("capture")
    cap["show"] = True
    cross = n("cross")
    cross["show"] = True
    inner = [n("gray"), n("blur"), n("threshold"), n("blobs"), n("erode"), n("coords")]
    spot = n("if_spot")
    spot["c"] = [n("report"), cross]
    spot["e"] = [n("report_none")]
    inner += [spot]
    frame_if = n("if_frame")
    frame_if["c"] = inner
    p["children"] = [cap, frame_if, n("wait")]
    return p
