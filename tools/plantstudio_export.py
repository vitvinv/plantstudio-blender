"""Reference exporter — drives PlantStudio.exe to produce part-tagged OBJ files.

One-time tool per reference set (the resulting OBJ files are static inputs for
tools/compare_reference_obj.py). Needs an interactive desktop session; the
user runs it manually:

    python tools/plantstudio_export.py --exe "C:\\Path\\To\\PlantStudio.exe" ^
        --pla plantstudio_blender\\data\\New version 2 plants.pla ^
        --out-dir data\\reference --ages 100

What it does per (pla, age) pair:
1. Builds a driver .pla by surgical text edit (only 'Age for drawing
   [kStateAge]' lines change; age 100 uses the file unchanged).
2. Starts PlantStudio.exe with the driver file and waits for its main
   window (all window handling is scoped to the launched process id —
   the script never enumerates or messages other applications' windows).
3. Discovers the File -> Export -> OBJ menu item IDs at runtime via GetMenu
   (no hardcoded IDs) and sends WM_COMMAND.
4. Fills the '3D Export Options' dialog via window messages: include all
   plants, group by type of plant part, rotation 0, scale 100 percent —
   then presses Save.
5. Fills the save dialog with the target path, answers the overwrite prompt,
   waits for the output file to be written, closes the app.

The unregistered build caps lifetime exports (20) and exports per session
(2 once the cap is reached); the script uses one app session per export and
reports if the cap blocks the remaining runs.
"""

import argparse
import ctypes
import os
import re
import shutil
import subprocess
import sys
import time

from ctypes import wintypes

user32 = ctypes.windll.user32
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_SETTEXT = 0x000C
BM_CLICK = 0x00F5
BM_SETCHECK = 0x00F1
BST_CHECKED = 0x0005
BM_GETCHECK = 0x00F0
GW_ENABLEDPOPUP = 6

GA_ROOT = 2
SW_SHOWNORMAL = 1


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def enumerate_top_windows():
    handles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, lparam):
        handles.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return handles


def enumerate_children(hwnd):
    handles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(child, lparam):
        handles.append(child)
        return True

    user32.EnumChildWindows(hwnd, callback, 0)
    return handles


def window_text(hwnd):
    length = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, length + 1, buf)
    return buf.value


def window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def is_visible(hwnd):
    return bool(user32.IsWindowVisible(hwnd))


# ── window helpers ──────────────────────────────────────────────────────────
#
# Every window lookup is scoped to the launched process id (PID). The script
# must never enumerate or message windows of other applications: titles alone
# are not safe (e.g. a VS Code window titled '... plantstudio-blender ...'
# would match a title-substring search). All find/wait/close operations take
# the pid of the PlantStudio instance this script started.


def windows_for_pid(pid, visible_only=True):
    """Top-level windows owned by the given process id only."""
    out = []
    for hwnd in enumerate_top_windows():
        if visible_only and not is_visible(hwnd):
            continue
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value == pid:
            out.append(hwnd)
    return out


def wait_for_window(title_substring, timeout=30.0, pid=None,
                    require_menu=False):
    """Wait for a window of the given pid (required for app windows) whose
    title contains title_substring. With require_menu, prefer windows that
    own a Win32 menu — Delphi apps have a hidden TApplication window with
    the same title but no menu, which must not be mistaken for the main
    form."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        candidates = windows_for_pid(pid) if pid is not None else []
        fallback = None
        for hwnd in candidates:
            if title_substring.lower() not in window_text(hwnd).lower():
                continue
            if require_menu:
                if user32.GetMenu(hwnd):
                    return hwnd
                if fallback is None:
                    fallback = hwnd
                continue
            return hwnd
        if fallback is not None and time.time() > deadline - timeout / 2:
            # no menu-owning window appeared; use the title-only fallback
            # late in the wait so menu setup latency can't cause a miss
            return fallback
        time.sleep(0.25)
    raise TimeoutError(f"window with title containing "
                       f"{title_substring!r} not found for pid {pid} "
                       f"within {timeout}s")


def wait_for_new_window(pid, known_handles, timeout=60.0):
    """Wait for any NEW top-level window of the process (not in
    known_handles). Returns its hwnd. This avoids caption-guessing: the
    runtime dialog captions can differ from the .lfm source."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd in windows_for_pid(pid):
            if hwnd not in known_handles:
                return hwnd
        time.sleep(0.25)
    log("no new window appeared; current process windows:")
    for hwnd in windows_for_pid(pid):
        log(f"  window: class={window_class(hwnd)!r} "
            f"title={window_text(hwnd)!r}")
    raise TimeoutError(f"no new window appeared for pid {pid} "
                       f"within {timeout}s")


def classify_dialog(hwnd):
    """Classify a newly appeared window: 'options', 'save', or 'other'.

    This build's options form is class TGeneric3DOptionsForm titled 'Save
    WaveFront OBJ File (ASCII)' — a caption starting with 'Save' — so the
    classification checks structure/class BEFORE titles.
    """
    title = window_text(hwnd)
    cls = window_class(hwnd).lower()
    children_text = " | ".join(window_text(c)
                               for c in enumerate_children(hwnd)).lower()
    if "tgeneric3doptions" in cls or \
            ("group by" in children_text and "reorient" in children_text):
        return "options"
    if cls == "#32770" and ("file &name" in children_text
                            or "file name" in children_text):
        return "save"
    return "other"


def strip_mnemonic(caption):
    return caption.replace("&", "").replace("...", "").strip().lower()


# ── menu helpers ────────────────────────────────────────────────────────────


def menu_items(menu):
    """Yield (position, id_or_None, caption) for a menu handle."""
    count = user32.GetMenuItemCount(menu)
    for pos in range(count):
        item_id = user32.GetMenuItemID(menu, pos)
        submenu = user32.GetSubMenu(menu, pos)
        size = user32.GetMenuStringW(menu, pos, None, 0, 0x0400)  # MF_BYPOSITION
        buf = ctypes.create_unicode_buffer(size + 1)
        user32.GetMenuStringW(menu, pos, buf, size + 1, 0x0400)
        yield pos, (None if submenu else item_id), buf.value


def dump_menu_tree(hwnd):
    """Log the full menu tree — for diagnosing wrong path labels."""
    menu = user32.GetMenu(hwnd)
    if not menu:
        log("  (window has no menu)")
        return
    for pos, item_id, caption in menu_items(menu):
        sub = user32.GetSubMenu(menu, pos)
        pad = ""
        log(f"  menu: {pad}{caption!r} id={item_id}")
        if sub:
            _dump_submenu(sub, pad + "  ")


def _dump_submenu(menu, pad):
    for pos, item_id, caption in menu_items(menu):
        sub = user32.GetSubMenu(menu, pos)
        log(f"  menu: {pad}{caption!r} id={item_id}")
        if sub:
            _dump_submenu(sub, pad + "  ")


def find_menu_path(hwnd, path_labels):
    """Walk GetMenu matching caption substrings; return the leaf command id."""
    menu = user32.GetMenu(hwnd)
    if not menu:
        raise RuntimeError("main window has no menu")
    current = menu
    for depth, label in enumerate(path_labels):
        needle = label.lower()
        found = None
        for pos, item_id, caption in menu_items(current):
            clean = strip_mnemonic(caption)
            # captions may carry accelerators ("Export 3D...\tCtrl+E")
            clean = clean.split("\t")[0]
            if needle in clean:
                found = (pos, item_id)
                break
        if found is None:
            log("menu tree dump:")
            dump_menu_tree(hwnd)
            raise RuntimeError(f"menu item {label!r} not found at depth "
                               f"{depth}")
        pos, item_id = found
        if depth < len(path_labels) - 1:
            current = user32.GetSubMenu(current, pos)
            if not current:
                raise RuntimeError(f"menu item {label!r} has no submenu")
        else:
            if item_id is None:
                raise RuntimeError(f"menu item {label!r} is not a command")
            return item_id
    raise RuntimeError("unreachable")


# ── dialog helpers ──────────────────────────────────────────────────────────


def find_child_by_class_and_text(hwnd, class_name, text_substring):
    """Find a child whose class matches exactly OR ends with the requested
    class name (Delphi VCL uses custom classes like TButton/TRadioButton
    that behave like their Win32 counterparts) and whose caption matches."""
    needle = strip_mnemonic(text_substring).lower()
    for child in enumerate_children(hwnd):
        child_class = window_class(child).lower()
        if child_class == class_name.lower() \
                or child_class.endswith(class_name.lower()):
            if needle in strip_mnemonic(window_text(child)).lower():
                return child
    return None


def click_button(hwnd, caption_substring):
    button = find_child_by_class_and_text(hwnd, "Button", caption_substring)
    if button is None:
        raise RuntimeError(f"button {caption_substring!r} not found "
                           f"in dialog {window_text(hwnd)!r}")
    user32.SendMessageW(button, BM_CLICK, 0, 0)
    return button


def set_checkbox(hwnd, caption_substring, checked):
    box = find_child_by_class_and_text(hwnd, "CheckBox", caption_substring)
    if box is None:
        raise RuntimeError(f"checkbox {caption_substring!r} not found")
    is_checked = user32.SendMessageW(box, BM_GETCHECK, 0, 0) == BST_CHECKED
    if is_checked != checked:
        user32.SendMessageW(box, BM_CLICK, 0, 0)
    return box


def set_radio(hwnd, caption_substring):
    button = find_child_by_class_and_text(hwnd, "Button", caption_substring)
    if button is None:
        raise RuntimeError(f"radio {caption_substring!r} not found")
    if user32.SendMessageW(button, BM_GETCHECK, 0, 0) != BST_CHECKED:
        user32.SendMessageW(button, BM_CLICK, 0, 0)
    return button


def set_spinedit(hwnd, index, text):
    """TSpinEdit controls host an inner EDIT; order by vertical position."""
    spinedits = []
    for child in enumerate_children(hwnd):
        if window_class(child).lower().startswith("tspinedit"):
            rect = wintypes.RECT()
            user32.GetWindowRect(child, ctypes.byref(rect))
            spinedits.append((rect.top, child))
    spinedits.sort()
    if len(spinedits) <= index:
        raise RuntimeError(f"expected > {index} spin edits, found "
                           f"{len(spinedits)}")
    target = spinedits[index][1]
    edits = [c for c in enumerate_children(target)
             if window_class(c).lower() == "edit"]
    inner = edits[0] if edits else target
    user32.SendMessageW(inner, WM_SETTEXT, 0,
                        ctypes.create_unicode_buffer(text))
    return target


def wait_for_dialog(title_substring, timeout=30.0, pid=None):
    return wait_for_window(title_substring, timeout=timeout, pid=pid)


def answer_confirmation(preferred="&Yes", timeout=15.0, pid=None):
    """If a modal confirmation dialog of the launched process pops up, click
    the preferred button."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd in windows_for_pid(pid):
            if window_class(hwnd).lower() != "#32770":
                continue
            text = window_text(hwnd).lower()
            if "export" in text or "save" in text or "confirm" in text \
                    or "replace" in text:
                try:
                    click_button(hwnd, preferred)
                    return True
                except RuntimeError:
                    continue
        time.sleep(0.25)
    return False


def wait_for_file(path, timeout=300.0, stable_checks=4):
    """Wait for the file to exist and its size to stabilise."""
    deadline = time.time() + timeout
    last_size = -1
    stable = 0
    while time.time() < deadline:
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size == last_size and size > 0:
                stable += 1
                if stable >= stable_checks:
                    return
            else:
                stable = 0
            last_size = size
        time.sleep(1.0)
    raise TimeoutError(f"output file {path} not written within {timeout}s")


def close_app(main_hwnd, pid):
    user32.SendMessageW(main_hwnd, WM_CLOSE, 0, 0)
    time.sleep(1.0)
    # if a "save changes?" prompt of OUR process appears, answer No
    for hwnd in windows_for_pid(pid):
        if window_class(hwnd).lower() == "#32770":
            text = window_text(hwnd).lower()
            if "plantstudio" in text or "save" in text:
                for candidate in ("&No", "No", "Don't save", "&Don't save"):
                    try:
                        click_button(hwnd, candidate)
                        break
                    except RuntimeError:
                        continue
    time.sleep(1.0)


# ── driver .pla ─────────────────────────────────────────────────────────────

kStateAge_pattern = re.compile(r"(Age for drawing \[kStateAge\]\s*=\s*)\d+")


def build_driver_pla(source_pla, age, out_path):
    """Copy the .pla, rewriting only the per-plant kStateAge lines."""
    with open(source_pla, "r", encoding="cp1252", newline="") as f:
        content = f.read()
    if age is not None and age != 100:
        content = kStateAge_pattern.sub(lambda m: m.group(1) + str(age), content)
    with open(out_path, "w", encoding="cp1252", newline="") as f:
        f.write(content)
    return out_path


# ── one export run ──────────────────────────────────────────────────────────


def export_once(exe, driver_pla, output_obj, timeout=300.0):
    """Run one PlantStudio session that exports the driver file to OBJ."""
    # PlantStudio resolves relative paths against its own working directory,
    # and the EXE is launched with cwd = its folder — use absolute paths
    driver_pla = os.path.abspath(driver_pla)
    output_obj = os.path.abspath(output_obj)
    log(f"starting {exe} with {driver_pla}")
    proc = subprocess.Popen([exe, driver_pla], cwd=os.path.dirname(exe))
    pid = proc.pid
    log(f"launched process pid={pid}")
    try:
        main_hwnd = wait_for_window("PlantStudio", timeout=60.0, pid=pid,
                                    require_menu=True)
        log(f"main window found: class={window_class(main_hwnd)!r} "
            f"title={window_text(main_hwnd)!r}")
        time.sleep(1.0)  # let the plant file finish loading

        menu_id = find_menu_path(main_hwnd, ["file", "export", "obj"])
        log(f"posting WM_COMMAND for OBJ export (id={menu_id})")
        # PostMessage, NOT SendMessage: the menu handler opens a modal
        # options dialog, so SendMessage would block this script until a
        # human closes the dialog. Post returns immediately; the flow then
        # waits for the dialog windows explicitly.
        known = set(windows_for_pid(pid, visible_only=False))
        user32.PostMessageW(main_hwnd, WM_COMMAND, menu_id, 0)

        # wait for whatever dialog appears (options first, or Save As
        # directly) — classified by structure, not by caption
        hwnd = wait_for_new_window(pid, known, timeout=60.0)
        kind = classify_dialog(hwnd)
        log(f"dialog appeared: class={window_class(hwnd)!r} "
            f"title={window_text(hwnd)!r} -> {kind}")
        if kind == "options":
            set_radio(hwnd, "all plants")
            set_radio(hwnd, "type of plant part")
            set_spinedit(hwnd, 0, "0")      # rotate by (xRotation)
            set_spinedit(hwnd, 1, "100")    # scale by (percent)
            # determinism-relevant export options: the port draws single-
            # sided TDOs and 3-sided cylinders (the original defaults) —
            # persisted user options in the EXE must not leak in
            set_checkbox(hwnd, "Double polygons", False)
            set_checkbox(hwnd, '"Press" plants', False)
            set_spinedit(hwnd, 3, "3")      # stem cylinder faces (3-20)
            click_button(hwnd, "&Save")
            log("options accepted")
            known.add(hwnd)
            hwnd = wait_for_new_window(pid, known, timeout=60.0)
            kind = classify_dialog(hwnd)
            log(f"dialog appeared: class={window_class(hwnd)!r} "
                f"title={window_text(hwnd)!r} -> {kind}")
        if kind != "save":
            raise RuntimeError(f"expected Save As dialog, got "
                               f"class={window_class(hwnd)!r} "
                               f"title={window_text(hwnd)!r}")
        # standard save dialog: the filename edit has control id 1148
        # (edt1) or 1152 (cmb13); fall back to the first plain edit
        edits = [c for c in enumerate_children(hwnd)
                 if window_class(c).lower() == "edit"]
        if not edits:
            raise RuntimeError("save dialog has no filename edit")
        by_id = {user32.GetDlgCtrlID(c): c for c in edits}
        target_edit = by_id.get(1148) or by_id.get(1152) or edits[0]
        user32.SendMessageW(target_edit, WM_SETTEXT, 0,
                            ctypes.create_unicode_buffer(output_obj))
        click_button(hwnd, "&Save")
        log(f"save dialog accepted for {output_obj}")

        answer_confirmation("&Yes", pid=pid)
        try:
            wait_for_file(output_obj, timeout=timeout)
        except TimeoutError:
            if os.path.exists(output_obj):
                pass
            else:
                raise
        log(f"output written: {output_obj} ({os.path.getsize(output_obj)} bytes)")
        close_app(main_hwnd, pid)
        return True
    except (TimeoutError, RuntimeError) as e:
        log(f"EXPORT FAILED: {e}")
        # dump only OUR process's visible windows (registration reminders,
        # error messages from PlantStudio, unexpected save dialogs)
        for hwnd in windows_for_pid(pid):
            cls = window_class(hwnd)
            log(f"  visible window: class={cls!r} "
                f"title={window_text(hwnd)!r}")
            for child in enumerate_children(hwnd):
                text = window_text(child)
                if text:
                    log(f"    child {window_class(child)!r}: {text!r}")
        # close only windows belonging to the process we launched
        for hwnd in windows_for_pid(pid, visible_only=False):
            user32.SendMessageW(hwnd, WM_CLOSE, 0, 0)
        return False
    finally:
        time.sleep(1.0)
        if proc.poll() is None:
            proc.terminate()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exe", required=True, help="path to PlantStudio.exe")
    parser.add_argument("--pla", required=True,
                        help="source .pla species file")
    parser.add_argument("--out-dir", required=True,
                        help="directory for the reference OBJ files")
    parser.add_argument("--ages", nargs="*", type=int, default=[100])
    parser.add_argument("--name", default=None,
                        help="output base name (default: pla file stem)")
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args(argv)

    os.makedirs(args.out_dir, exist_ok=True)
    base = args.name or os.path.splitext(os.path.basename(args.pla))[0]
    failures = []
    for age in args.ages:
        driver = os.path.join(args.out_dir, f"_driver_{base}_{age}.pla")
        build_driver_pla(args.pla, age, driver)
        output = os.path.join(args.out_dir, f"{base}_age{age}.obj")
        if os.path.exists(output):
            log(f"skipping age {age}: {output} already exists")
            continue
        ok = export_once(args.exe, driver, output, timeout=args.timeout)
        if ok:
            os.remove(driver)
        else:
            failures.append(age)
    if failures:
        log(f"FAILED ages: {failures} (unregistered export cap may be "
            f"reached — rerun later or register)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
