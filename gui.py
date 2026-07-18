import json
import os
import math
import tkinter as tk
from calculator import (
    BallisticsToTarget, OutOfRangeException,
    calibrate, apply_calibration, reset_calibration,
    load_calibration, save_calibration, simulate_distance,
    generate_range_map, get_params
)
import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

root = ctk.CTk()
root.title("CBC : Ultimate Ballistic Computer + Range Map")

CONFIG_FILE = "cannon_calibrated_config.json"
CALIBRATION_FILE = "calibration_config.json"
CALIBRATION_POINTS_FILE = "calibration_points.json"
WINDOW_STATE_FILE = "window_state.json"

current_mode = "cannon"
calib_mode = "cannon"
calibration_points = []

last_res = None
last_cannon = None
last_target = None
last_range_map = None
last_max_dist = None
resize_timer = None
range_overlay_visible = False

PROJECTILES = ["HE Shell", "Heavy Shot", "AP Shot", "AP Shell", "APHE", "Mortar Stone"]

cam_side = {"ox": 0, "oy": 0, "scale": 1.0, "min_scale": 0.001, "max_scale": 1000.0, "drag_start": None, "initialized": False}
cam_top = {"ox": 0, "oy": 0, "scale": 1.0, "min_scale": 0.001, "max_scale": 1000.0, "drag_start": None, "initialized": False}


def save_window_state():
    try:
        data = {"geometry": root.geometry()}
        with open(WINDOW_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception:
        pass


def load_window_state():
    if os.path.exists(WINDOW_STATE_FILE):
        try:
            with open(WINDOW_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                geo = data.get("geometry", "1500x850")
                root.geometry(geo)
        except Exception:
            root.geometry("1500x850")
    else:
        root.geometry("1500x850")


def save_config():
    data = {
        "xCannon": xCannon.get(), "yCannon": yCannon.get(), "zCannon": zCannon.get(),
        "xTarget": xTarget.get(), "yTarget": yTarget.get(), "zTarget": zTarget.get(),
        "powder": entryPowder.get(), "barrel": entryBarrel.get(),
        "mode": current_mode,
        "projectile": projectile_selector.get()
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception:
        pass


def load_config():
    global current_mode
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                xCannon.insert(0, data.get("xCannon", "500"))
                yCannon.insert(0, data.get("yCannon", "0"))
                zCannon.insert(0, data.get("zCannon", "0"))
                xTarget.insert(0, data.get("xTarget", ""))
                yTarget.insert(0, data.get("yTarget", "0"))
                zTarget.insert(0, data.get("zTarget", ""))
                entryPowder.insert(0, data.get("powder", "2"))
                entryBarrel.insert(0, data.get("barrel", "4"))
                projectile_selector.set(data.get("projectile", "HE Shell"))
                saved_mode = data.get("mode", "cannon")
                mode_selector.set("Миномёт" if saved_mode == "mortar" else "Пушка")
                handle_mode_switch(mode_selector.get())
        except Exception:
            pass


def save_calibration_points():
    try:
        serializable = []
        for pt in calibration_points:
            pt_copy = pt.copy()
            pt_copy["cannon"] = list(pt_copy["cannon"])
            pt_copy["landing"] = list(pt_copy["landing"])
            serializable.append(pt_copy)
        with open(CALIBRATION_POINTS_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=4)
    except Exception:
        pass


def load_calibration_points():
    global calibration_points
    if os.path.exists(CALIBRATION_POINTS_FILE):
        try:
            with open(CALIBRATION_POINTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                calibration_points = []
                for pt in data:
                    pt["cannon"] = tuple(pt["cannon"])
                    pt["landing"] = tuple(pt["landing"])
                    calibration_points.append(pt)
        except Exception:
            calibration_points = []
    else:
        calibration_points = []


def callback(P):
    if P in ("", "-", ".", "-."):
        return True
    try:
        float(P)
        return True
    except ValueError:
        return False


def handle_mode_switch(value):
    global current_mode
    if value == "Миномёт":
        current_mode = "mortar"
        params_frame.pack_forget()
    else:
        current_mode = "cannon"
        params_frame.pack(side="left", padx=10)
    save_config()
    controlButton()
    getAngles()


def controlButton(*args):
    fields = [xCannon, yCannon, zCannon, xTarget, yTarget, zTarget]
    if current_mode == "cannon":
        fields.extend([entryPowder, entryBarrel])
    if all(var.get() for var in fields):
        button.configure(state="normal")
        return True
    else:
        button.configure(state="disabled")
        return False


# ===== КАМЕРА И УТИЛИТЫ =====

def get_grid_step(scale):
    if scale <= 0:
        return 1
    raw = 80.0 / scale
    if raw <= 0:
        return 1
    exponent = math.floor(math.log10(raw))
    mantissa = raw / (10.0 ** exponent)
    if mantissa < 1.5:
        step = 1.0 * (10.0 ** exponent)
    elif mantissa < 3.5:
        step = 2.0 * (10.0 ** exponent)
    elif mantissa < 7.5:
        step = 5.0 * (10.0 ** exponent)
    else:
        step = 10.0 * (10.0 ** exponent)
    return step


def world_to_screen(canvas, wx, wy, cam, invert_y=False):
    sx = cam["ox"] + wx * cam["scale"]
    if invert_y:
        sy = cam["oy"] + wy * cam["scale"]
    else:
        sy = cam["oy"] - wy * cam["scale"]
    return sx, sy


def screen_to_world(canvas, sx, sy, cam, invert_y=False):
    wx = (sx - cam["ox"]) / cam["scale"]
    if invert_y:
        wy = (sy - cam["oy"]) / cam["scale"]
    else:
        wy = -(sy - cam["oy"]) / cam["scale"]
    return wx, wy


def fit_camera(canvas, cam, wx_min, wx_max, wy_min, wy_max, invert_y=False):
    w = canvas.winfo_width()
    h = canvas.winfo_height()
    if w < 20 or h < 20:
        return
    world_w = wx_max - wx_min
    world_h = wy_max - wy_min
    if world_w <= 0 or world_h <= 0:
        return
    pad = 60
    scale_x = (w - 2 * pad) / world_w
    scale_y = (h - 2 * pad) / world_h
    cam["scale"] = min(scale_x, scale_y)
    cam["scale"] = max(cam["min_scale"], min(cam["max_scale"], cam["scale"]))
    cx = (wx_min + wx_max) / 2.0
    cy = (wy_min + wy_max) / 2.0
    cam["ox"] = w / 2.0 - cx * cam["scale"]
    if invert_y:
        cam["oy"] = h / 2.0 - cy * cam["scale"]
    else:
        cam["oy"] = h / 2.0 + cy * cam["scale"]
    cam["initialized"] = True


def zoom_at(canvas, cam, sx, sy, factor, invert_y=False):
    wx, wy = screen_to_world(canvas, sx, sy, cam, invert_y)
    new_scale = cam["scale"] * factor
    new_scale = max(cam["min_scale"], min(cam["max_scale"], new_scale))
    cam["scale"] = new_scale
    cam["ox"] = sx - wx * new_scale
    if invert_y:
        cam["oy"] = sy - wy * new_scale
    else:
        cam["oy"] = sy + wy * new_scale


def draw_grid(canvas, cam, wx_min, wx_max, wy_min, wy_max, invert_y=False):
    w = canvas.winfo_width()
    h = canvas.winfo_height()
    if w < 20 or h < 20:
        return
    step = get_grid_step(cam["scale"])
    texts = []
    x_min = min(wx_min, wx_max)
    x_max = max(wx_min, wx_max)
    y_min = min(wy_min, wy_max)
    y_max = max(wy_min, wy_max)

    start_x = math.floor(x_min / step) * step
    end_x = math.ceil(x_max / step) * step
    x = start_x
    while x <= end_x:
        sx, _ = world_to_screen(canvas, x, 0, cam, invert_y)
        if -2 <= sx <= w + 2:
            canvas.create_line(sx, 0, sx, h, fill="#2a2a2a", width=1)
            if abs(x) > 0.01:
                texts.append((sx, h - 18, str(int(x)), "#ffffff", False, "n"))
            else:
                texts.append((sx, h - 18, "0", "#ffffff", True, "n"))
        x += step

    start_y = math.floor(y_min / step) * step
    end_y = math.ceil(y_max / step) * step
    y = start_y
    while y <= end_y:
        _, sy = world_to_screen(canvas, 0, y, cam, invert_y)
        if -2 <= sy <= h + 2:
            canvas.create_line(0, sy, w, sy, fill="#2a2a2a", width=1)
            if abs(y) > 0.01:
                texts.append((8, sy, str(int(y)), "#ffffff", False, "w"))
            else:
                texts.append((8, sy, "0", "#ffffff", True, "w"))
        y += step

    sx0, _ = world_to_screen(canvas, 0, 0, cam, invert_y)
    _, sy0 = world_to_screen(canvas, 0, 0, cam, invert_y)
    if -2 <= sx0 <= w + 2:
        canvas.create_line(sx0, 0, sx0, h, fill="#444444", width=1.5)
    if -2 <= sy0 <= h + 2:
        canvas.create_line(0, sy0, w, sy0, fill="#444444", width=1.5)

    for tx, ty, txt, color, bold, anchor in texts:
        font = ("Roboto", 8, "bold") if bold else ("Roboto", 8)
        canvas.create_text(tx, ty, text=txt, fill=color, font=font, anchor=anchor)


def update_scrollbars(canvas, hbar, vbar, cam, canvas_w, canvas_h, world_x_min, world_x_max, world_y_min, world_y_max, invert_y=False):
    left_wx = screen_to_world(canvas, 0, 0, cam, invert_y)[0]
    right_wx = screen_to_world(canvas, canvas_w, 0, cam, invert_y)[0]
    top_wy = screen_to_world(canvas, 0, 0, cam, invert_y)[1]
    bottom_wy = screen_to_world(canvas, 0, canvas_h, cam, invert_y)[1]
    world_w = world_x_max - world_x_min
    world_h = world_y_max - world_y_min
    if world_w > 0:
        x0 = (left_wx - world_x_min) / world_w
        x1 = (right_wx - world_x_min) / world_w
        hbar.set(max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1)))
    else:
        hbar.set(0, 1)
    if world_h > 0:
        y0 = (world_y_max - top_wy) / world_h
        y1 = (world_y_max - bottom_wy) / world_h
        vbar.set(max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1)))
    else:
        vbar.set(0, 1)


def draw_scale_bar(canvas, cam, w, h):
    target_px = 100
    world_len = target_px / cam["scale"]
    if world_len <= 0:
        return
    exp = 10.0 ** math.floor(math.log10(world_len))
    mant = world_len / exp
    if mant < 1.5:
        nice = 1.0 * exp
    elif mant < 3.5:
        nice = 2.0 * exp
    elif mant < 7.5:
        nice = 5.0 * exp
    else:
        nice = 10.0 * exp
    actual_px = nice * cam["scale"]
    if actual_px < 20:
        return
    margin = 15
    x2 = w - margin
    x1 = x2 - actual_px
    y = h - 25
    canvas.create_line(x1, y, x2, y, fill="white", width=2)
    canvas.create_line(x1, y - 4, x1, y + 4, fill="white", width=2)
    canvas.create_line(x2, y - 4, x2, y + 4, fill="white", width=2)
    if nice >= 1000:
        label = f"{int(nice / 1000)}км"
    elif nice == int(nice):
        label = f"{int(nice)}м"
    else:
        label = f"{nice:.1f}м"
    canvas.create_text((x1 + x2) / 2, y - 10, text=label, fill="white", font=("Roboto", 9), anchor="s")


# ===== ОТРИСОВКА ГРАФИКОВ =====

def draw_side_graph():
    canvas = canvas_side
    cam = cam_side
    canvas.delete("all")
    if last_res is None or last_cannon is None:
        return
    w = canvas.winfo_width()
    h = canvas.winfo_height()
    if w < 50 or h < 50:
        return
    res = last_res
    c_y = last_cannon[1]
    t_y = last_target[1]
    dist = res["distance"]
    path_pts = []
    if res["low"]:
        path_pts.extend(res["low"]["path"])
    if res["high"]:
        path_pts.extend(res["high"]["path"])
    if not path_pts:
        path_pts = [(0.0, c_y), (dist, t_y)]
    xs = [p[0] for p in path_pts]
    ys = [p[1] for p in path_pts]
    xmin = min(xs + [0.0, dist]) - 20
    xmax = max(xs + [0.0, dist]) + 20
    ymin = min(ys + [c_y, t_y]) - 20
    ymax = max(ys + [c_y, t_y]) + 20
    if not cam["initialized"]:
        fit_camera(canvas, cam, xmin, xmax, ymin, ymax)
    left_wx = screen_to_world(canvas, 0, 0, cam)[0]
    right_wx = screen_to_world(canvas, w, 0, cam)[0]
    top_wy = screen_to_world(canvas, 0, 0, cam)[1]
    bottom_wy = screen_to_world(canvas, 0, h, cam)[1]
    draw_grid(canvas, cam, left_wx - 50, right_wx + 50, bottom_wy - 50, top_wy + 50)
    if res["low"]:
        coords = []
        for px, py in res["low"]["path"]:
            sx, sy = world_to_screen(canvas, px, py, cam)
            coords.extend([sx, sy])
        if len(coords) >= 4:
            canvas.create_line(coords, fill="#50bc54", width=2.5, smooth=True)
    if res["high"]:
        coords = []
        for px, py in res["high"]["path"]:
            sx, sy = world_to_screen(canvas, px, py, cam)
            coords.extend([sx, sy])
        if len(coords) >= 4:
            canvas.create_line(coords, fill="#ffb03a", width=2.5, smooth=True)
    cx_c, cy_c = world_to_screen(canvas, 0, c_y, cam)
    canvas.create_rectangle(cx_c - 6, cy_c - 6, cx_c + 6, cy_c + 6, fill="#1E538D", outline="white")
    canvas.create_text(cx_c, cy_c - 15, text=f"Орудие Y={int(c_y)}", fill="#7cb1f2", anchor="s", font=("Roboto", 10))
    cx_t, cy_t = world_to_screen(canvas, dist, t_y, cam)
    canvas.create_oval(cx_t - 6, cy_t - 6, cx_t + 6, cy_t + 6, fill="#980404", outline="white")
    canvas.create_text(cx_t, cy_t - 15, text=f"Цель Y={int(t_y)}", fill="#ff4d4d", anchor="s", font=("Roboto", 10))
    tol = res.get("tolerance", 2.0)
    if tol > 0:
        canvas.create_line(cx_t - 15, cy_t, cx_t + 15, cy_t, fill="#ff4d4d", width=1, dash=(3, 2))
    update_scrollbars(canvas, hbar_side, vbar_side, cam, w, h, xmin - 200, xmax + 200, ymin - 200, ymax + 200)


def draw_range_overlay(canvas, cam, w, h, c_x, c_z, left_wx, right_wx, top_wz, bottom_wz):
    """Рисует heatmap досягаемости поверх canvas (до сетки)."""
    if last_range_map is None or last_max_dist is None:
        return
    range_map = last_range_map
    max_dist = last_max_dist

    cell_w = max(5, int(20 / cam["scale"]))
    cell_w = max(cell_w, 5)

    x_min_vis = min(left_wx, right_wx)
    x_max_vis = max(left_wx, right_wx)
    z_min_vis = min(top_wz, bottom_wz)
    z_max_vis = max(top_wz, bottom_wz)

    start_x = math.floor(x_min_vis / cell_w) * cell_w
    end_x = math.ceil(x_max_vis / cell_w) * cell_w
    start_z = math.floor(z_min_vis / cell_w) * cell_w
    end_z = math.ceil(z_max_vis / cell_w) * cell_w

    for wx in range(int(start_x), int(end_x) + 1, cell_w):
        for wz in range(int(start_z), int(end_z) + 1, cell_w):
            off_x = wx - c_x
            off_z = wz - c_z
            dist = math.sqrt(off_x * off_x + off_z * off_z)
            rounded_d = round(dist / 10) * 10
            if rounded_d > max_dist:
                color = "#1a1a1a"
            else:
                has_low, has_high = range_map.get(rounded_d, (False, False))
                if has_low and has_high:
                    color = "#8B4513"
                elif has_low:
                    color = "#2d5a2f"
                elif has_high:
                    color = "#8B6508"
                else:
                    color = "#1a1a1a"
            sx1, sy1 = world_to_screen(canvas, wx, wz, cam, invert_y=True)
            sx2, sy2 = world_to_screen(canvas, wx + cell_w, wz + cell_w, cam, invert_y=True)
            canvas.create_rectangle(sx1, sy1, sx2, sy2, fill=color, outline="")

    # Легенда
    legend_x = 10
    legend_y = h - 90
    items = [
        ("#8B4513", "Прямой + Навесной"),
        ("#2d5a2f", "Только прямой"),
        ("#8B6508", "Только навесной"),
        ("#1a1a1a", "Недостижимо"),
    ]
    for color, text in items:
        canvas.create_rectangle(legend_x, legend_y, legend_x + 12, legend_y + 12, fill=color, outline="white")
        canvas.create_text(legend_x + 18, legend_y + 6, text=text, fill="#cccccc", anchor="w", font=("Roboto", 9))
        legend_y += 18


def draw_topdown_graph():
    canvas = canvas_top
    cam = cam_top
    canvas.delete("all")
    if last_res is None or last_cannon is None:
        return
    w = canvas.winfo_width()
    h = canvas.winfo_height()
    if w < 50 or h < 50:
        return
    cannon = last_cannon
    target = last_target
    c_x, c_z = cannon[0], cannon[2]
    t_x, t_z = target[0], target[2]
    dx = t_x - c_x
    dz = t_z - c_z
    dist = math.sqrt(dx * dx + dz * dz)
    if current_mode == "mortar":
        dispersion = max(dist * 0.10, 8.0)
    else:
        dispersion = max(dist * 0.02, 3.0)
    pitch = 45.0
    if last_res and last_res.get("low"):
        pitch = abs(last_res["low"]["pitch"])
    elif last_res and last_res.get("high"):
        pitch = abs(last_res["high"]["pitch"])
    if pitch < 25.0:
        long_disp = dispersion * 1.6
        lat_disp = dispersion * 0.5
    else:
        long_disp = dispersion
        lat_disp = dispersion
    xmin = min(c_x, t_x) - max(long_disp, dispersion) * 1.5 - 50
    xmax = max(c_x, t_x) + max(long_disp, dispersion) * 1.5 + 50
    zmin = min(c_z, t_z) - max(long_disp, dispersion) * 1.5 - 50
    zmax = max(c_z, t_z) + max(long_disp, dispersion) * 1.5 + 50
    if not cam["initialized"]:
        fit_camera(canvas, cam, xmin, xmax, zmin, zmax, invert_y=True)
    left_wx = screen_to_world(canvas, 0, 0, cam, invert_y=True)[0]
    right_wx = screen_to_world(canvas, w, 0, cam, invert_y=True)[0]
    top_wz = screen_to_world(canvas, 0, 0, cam, invert_y=True)[1]
    bottom_wz = screen_to_world(canvas, 0, h, cam, invert_y=True)[1]

    # Heatmap под сеткой
    if range_overlay_visible:
        draw_range_overlay(canvas, cam, w, h, c_x, c_z, left_wx, right_wx, top_wz, bottom_wz)

    draw_grid(canvas, cam, left_wx - 50, right_wx + 50, top_wz - 50, bottom_wz + 50, invert_y=True)

    # Орудие и цель в АБСОЛЮТНЫХ координатах с округлением
    cx0, cz0 = world_to_screen(canvas, c_x, c_z, cam, invert_y=True)
    cx0, cz0 = int(round(cx0)), int(round(cz0))
    cx_t, cz_t = world_to_screen(canvas, t_x, t_z, cam, invert_y=True)
    cx_t, cz_t = int(round(cx_t)), int(round(cz_t))

    canvas.create_line(cx0, cz0, cx_t, cz_t, fill="#1E538D", width=2, dash=(5, 3))
    if pitch < 25.0:
        theta = math.atan2(dx, dz)
        points = []
        for i in range(64):
            phi = 2 * math.pi * i / 64
            local_x = long_disp * math.cos(phi)
            local_z = lat_disp * math.sin(phi)
            offset_x = local_x * math.sin(theta) - local_z * math.cos(theta)
            offset_z = local_x * math.cos(theta) + local_z * math.sin(theta)
            px = t_x + offset_x
            pz = t_z + offset_z
            sx, sy = world_to_screen(canvas, px, pz, cam, invert_y=True)
            points.extend([sx, sy])
        if len(points) >= 6:
            canvas.create_polygon(points, outline="#ff4d4d", fill="", width=2, dash=(4, 3))
        label_offset_x = long_disp * math.sin(theta)
        label_offset_z = long_disp * math.cos(theta)
        lx, ly = world_to_screen(canvas, t_x + label_offset_x, t_z + label_offset_z, cam, invert_y=True)
        lx += 10
        canvas.create_text(lx, ly, text=f"±{int(long_disp)}×{int(lat_disp)}м", fill="#ff4d4d", anchor="w", font=("Roboto", 10))
    else:
        r = dispersion * cam["scale"]
        canvas.create_oval(cx_t - r, cz_t - r, cx_t + r, cz_t + r, outline="#ff4d4d", width=2, dash=(4, 3))
        label_x = cx_t + r + 8
        if label_x > w - 20:
            label_x = cx_t - r - 8
        canvas.create_text(label_x, cz_t, text=f"±{int(dispersion)}м", fill="#ff4d4d", anchor="w" if label_x > cx_t else "e", font=("Roboto", 10))
    canvas.create_rectangle(cx0 - 7, cz0 - 7, cx0 + 7, cz0 + 7, fill="#1E538D", outline="white")
    canvas.create_text(cx0, cz0 - 18, text=f"Орудие\n({int(c_x)},{int(c_z)})", fill="#7cb1f2", anchor="s", font=("Roboto", 9))
    canvas.create_oval(cx_t - 6, cz_t - 6, cx_t + 6, cz_t + 6, fill="#980404", outline="white")
    canvas.create_text(cx_t, cz_t - 18, text=f"Цель\n({int(t_x)},{int(t_z)})", fill="#ff4d4d", anchor="s", font=("Roboto", 9))
    mid_x = (cx0 + cx_t) / 2
    mid_z = (cz0 + cz_t) / 2
    canvas.create_text(mid_x, mid_z - 12, text=f"{int(dist)}м", fill="#ffffff", font=("Roboto", 10, "bold"))
    draw_scale_bar(canvas, cam, w, h)
    update_scrollbars(canvas, hbar_top, vbar_top, cam, w, h, xmin - 200, xmax + 200, zmin - 200, zmax + 200, invert_y=True)


def redraw_all_graphs():
    draw_side_graph()
    draw_topdown_graph()


# ===== СОБЫТИЯ МЫШИ =====

def on_mousewheel(canvas, cam, event, factor=None, invert_y=False):
    if factor is None:
        if event.delta > 0:
            factor = 1.15
        elif event.delta < 0:
            factor = 0.87
        else:
            return
    sx = canvas.canvasx(event.x)
    sy = canvas.canvasy(event.y)
    zoom_at(canvas, cam, sx, sy, factor, invert_y)
    redraw_all_graphs()


def on_drag_start(event, cam):
    cam["drag_start"] = (event.x, event.y)


def on_drag(event, cam):
    if cam["drag_start"] is None:
        return
    dx = event.x - cam["drag_start"][0]
    dy = event.y - cam["drag_start"][1]
    cam["ox"] += dx
    cam["oy"] += dy
    cam["drag_start"] = (event.x, event.y)
    redraw_all_graphs()


def on_drag_end(event, cam):
    cam["drag_start"] = None


def bind_canvas_events(canvas, cam, invert_y=False):
    canvas.bind("<MouseWheel>", lambda e: on_mousewheel(canvas, cam, e, invert_y=invert_y))
    canvas.bind("<Button-4>", lambda e: on_mousewheel(canvas, cam, e, 1.15, invert_y=invert_y))
    canvas.bind("<Button-5>", lambda e: on_mousewheel(canvas, cam, e, 0.87, invert_y=invert_y))
    canvas.bind("<ButtonPress-1>", lambda e: on_drag_start(e, cam))
    canvas.bind("<B1-Motion>", lambda e: on_drag(e, cam))
    canvas.bind("<ButtonRelease-1>", lambda e: on_drag_end(e, cam))


# ===== РАСЧЁТ =====

def getAngles(*args):
    global last_res, last_cannon, last_target, last_range_map, last_max_dist
    if not controlButton():
        return
    try:
        cannonCoords = tuple(map(float, (xCannon.get(), yCannon.get(), zCannon.get())))
        targetCoords = tuple(map(float, (xTarget.get(), yTarget.get(), zTarget.get())))
        if current_mode == "cannon":
            powder = float(entryPowder.get())
            barrel = float(entryBarrel.get())
            proj = projectile_selector.get()
            if powder <= 0 or barrel <= 0:
                return
        else:
            powder = 1.0
            barrel = 1.0
            proj = "Mortar Shell"
        res = BallisticsToTarget(cannonCoords, targetCoords, powder, barrel, current_mode, proj)
    except OutOfRangeException as e:
        statusMessage.set(str(e))
        status.configure(text_color="#980404")
        varLowPitch.set("Pitch: Недоступно")
        varLowTime.set("Полет: —")
        varHighPitch.set("Pitch: Недоступно")
        varHighTime.set("Полет: —")
        canvas_side.delete("all")
        canvas_top.delete("all")
        last_res = None
    except ValueError:
        pass
    else:
        last_res = res
        last_cannon = cannonCoords
        last_target = targetCoords
        varYaw.set(f"YAW (Поворот): {round(res['yaw'], 1)}°")
        varSpeed.set(f"V0: {res['speed']} бл/т")
        varTolerance.set(f"Погрешность мода: ±{res['tolerance']} бл.")
        if res["low"]:
            varLowPitch.set(f"Pitch: {round(res['low']['pitch'], 1)}°")
            varLowTime.set(f"Полет: {res['low']['time']} сек.")
        else:
            varLowPitch.set("Pitch: Недоступно")
            varLowTime.set("Полет: —")
        if res["high"]:
            varHighPitch.set(f"Pitch: {round(res['high']['pitch'], 1)}°")
            varHighTime.set(f"Полет: {res['high']['time']} сек.")
        else:
            varHighPitch.set("Pitch: Недоступно")
            varHighTime.set("Полет: —")
        statusMessage.set(f"Траектория построена. Точность ±{res['tolerance']} бл.")
        status.configure(text_color="#50bc54")
        save_config()
        try:
            params = get_params(current_mode, barrel if current_mode == "cannon" else None)
            range_map, max_dist = generate_range_map(cannonCoords[1], targetCoords[1], params, current_mode)
            last_range_map = range_map
            last_max_dist = max_dist
        except Exception:
            last_range_map = None
            last_max_dist = None
        cam_side["initialized"] = False
        cam_top["initialized"] = False
        root.update_idletasks()
        root.after(50, redraw_all_graphs)


# ===== КАЛИБРОВКА =====

def switch_tab(tab_name):
    if tab_name == "calc":
        calc_frame.pack(fill="both", expand=True, padx=10, pady=5)
        calib_frame.pack_forget()
    else:
        calc_frame.pack_forget()
        calib_frame.pack(fill="both", expand=True, padx=10, pady=5)


def handle_calib_mode_switch(value):
    global calib_mode
    if value == "Миномёт":
        calib_mode = "mortar"
        calib_cannon_params_frame.pack_forget()
    else:
        calib_mode = "cannon"
        calib_cannon_params_frame.pack(fill="x", padx=15, pady=5, after=cf3)
    calib_status.set(f"Режим калибровки: {'Миномёт' if calib_mode == 'mortar' else 'Пушка'}")


def add_calibration_point():
    try:
        c_x = float(calib_cX.get())
        c_y = float(calib_cY.get())
        c_z = float(calib_cZ.get())
        l_x = float(calib_lX.get())
        l_y = float(calib_lY.get())
        l_z = float(calib_lZ.get())
        pitch = float(calib_pitch.get())
        yaw = float(calib_yaw.get())
        point = {
            "cannon": (c_x, c_y, c_z),
            "landing": (l_x, l_y, l_z),
            "pitch": pitch,
            "yaw": yaw,
            "mode": calib_mode
        }
        if calib_mode == "cannon":
            point["power"] = float(calib_powder.get())
            point["length"] = float(calib_barrel.get())
        airtime_str = calib_airtime.get().strip()
        if airtime_str:
            point["airtime"] = float(airtime_str)
        calibration_points.append(point)
        save_calibration_points()
        update_calib_list()
        calib_status.set(f"Точка добавлена. Всего: {len(calibration_points)}")
        calib_status_label.configure(text_color="#50bc54")
    except ValueError:
        calib_status.set("Ошибка: проверьте формат чисел!")
        calib_status_label.configure(text_color="#980404")


def update_calib_list():
    for widget in calib_list_frame.winfo_children():
        widget.destroy()
    for i, pt in enumerate(calibration_points):
        mode_str = "Миномёт" if pt["mode"] == "mortar" else "Пушка"
        text = f"{i+1}. {mode_str} | Pitch:{pt['pitch']:.1f}° | Yaw:{pt['yaw']:.1f}°"
        if pt["mode"] == "cannon":
            text += f" | Порох:{pt.get('power','-')} | Ствол:{pt.get('length','-')}"
        if pt.get("airtime"):
            text += f" | Время:{pt['airtime']:.1f}с"
        row = ctk.CTkFrame(master=calib_list_frame, fg_color="transparent")
        row.pack(fill="x", pady=1)
        lbl = ctk.CTkLabel(master=row, text=text, font=("Roboto", 11))
        lbl.pack(side="left", padx=5)
        btn = ctk.CTkButton(master=row, text="✕", width=30, height=20,
                           command=lambda idx=i: remove_calib_point(idx), fg_color="#980404")
        btn.pack(side="right", padx=5)


def remove_calib_point(idx):
    if 0 <= idx < len(calibration_points):
        calibration_points.pop(idx)
        save_calibration_points()
        update_calib_list()
        calib_status.set(f"Точка удалена. Всего: {len(calibration_points)}")


def run_calibration():
    if len(calibration_points) < 1:
        calib_status.set("Нужна хотя бы 1 точка калибровки!")
        calib_status_label.configure(text_color="#980404")
        return
    mortar_pts = [p for p in calibration_points if p["mode"] == "mortar"]
    cannon_pts = [p for p in calibration_points if p["mode"] == "cannon"]
    results_text = ""
    if mortar_pts:
        params, rmse = calibrate("mortar", mortar_pts)
        apply_calibration("mortar", params)
        results_text += f"【Миномёт】\n"
        results_text += f"  base_v = {params['base_v']:.3f}\n"
        results_text += f"  drag = {params['drag']:.5f}\n"
        results_text += f"  gravity = {params['gravity']:.4f}\n"
        results_text += f"  RMSE = {rmse:.2f} блоков\n\n"
    if cannon_pts:
        lengths = {}
        for p in cannon_pts:
            l = p.get("length", 4.0)
            lengths.setdefault(l, []).append(p)
        for length, pts in lengths.items():
            params, rmse = calibrate("cannon", pts, length)
            apply_calibration("cannon", params, length)
            results_text += f"【Пушка, ствол {length} бл】\n"
            results_text += f"  base_v = {params['base_v']:.3f}\n"
            results_text += f"  slope = {params['slope']:.5f}\n"
            results_text += f"  drag = {params['drag']:.5f}\n"
            results_text += f"  RMSE = {rmse:.2f} блоков\n\n"
    calib_results_box.delete("0.0", "end")
    calib_results_box.insert("0.0", results_text)
    calib_status.set("Калибровка завершена! Параметры сохранены.")
    calib_status_label.configure(text_color="#50bc54")


def reset_calib():
    global calibration_points
    calibration_points = []
    save_calibration_points()
    reset_calibration()
    update_calib_list()
    calib_results_box.delete("0.0", "end")
    calib_results_box.insert("0.0", "Результаты калибровки появятся здесь...")
    calib_status.set("Калибровка сброшена до заводских значений.")
    calib_status_label.configure(text_color="#ffb03a")


# ===== TOGGLE RANGE OVERLAY =====

def toggle_range_overlay():
    global range_overlay_visible
    range_overlay_visible = not range_overlay_visible
    if range_overlay_visible:
        range_toggle_btn.configure(text="🎯 Зона: ВКЛ", fg_color="#50bc54")
    else:
        range_toggle_btn.configure(text="🎯 Зона: ВЫКЛ", fg_color="#1E538D")
    redraw_all_graphs()


# ===== RESIZE =====

def on_resize(event):
    global resize_timer
    if resize_timer:
        root.after_cancel(resize_timer)
    resize_timer = root.after(150, redraw_all_graphs)


# ===== MAIN =====

def main():
    global xCannon, yCannon, zCannon, xTarget, yTarget, zTarget
    global entryPowder, entryBarrel, button, statusMessage, status
    global varLowPitch, varLowTime, varHighPitch, varHighTime, varYaw, varSpeed, varTolerance
    global canvas_side, canvas_top, projectile_selector, mode_selector, params_frame
    global calc_frame, calib_frame
    global hbar_side, vbar_side, hbar_top, vbar_top
    global calib_cX, calib_cY, calib_cZ, calib_lX, calib_lY, calib_lZ
    global calib_pitch, calib_yaw, calib_powder, calib_barrel, calib_airtime
    global calib_status, calib_status_label, calib_list_frame, calib_results_box
    global calib_cannon_params_frame, calib_mode_selector
    global cf3, range_toggle_btn

    load_window_state()

    titre = ctk.CTkLabel(master=root, text="CBC Ballistic Computer + Range Map",
                         font=("Roboto", 24), fg_color="#1E538D", corner_radius=12)
    titre.pack(pady=10, padx=30, fill="x")

    tab_frame = ctk.CTkFrame(master=root, fg_color="transparent")
    tab_frame.pack(pady=4)
    ctk.CTkButton(master=tab_frame, text="🎯 Расчёт траектории", width=200,
                  command=lambda: switch_tab("calc")).pack(side="left", padx=5)
    ctk.CTkButton(master=tab_frame, text="🔧 Калибровка", width=200,
                  command=lambda: switch_tab("calib")).pack(side="left", padx=5)

    calc_frame = ctk.CTkFrame(master=root, corner_radius=15)
    calc_frame.pack(fill="both", expand=True, padx=10, pady=5)

    frame = calc_frame
    isvalidinput = root.register(callback)

    f1 = ctk.CTkFrame(master=frame)
    f1.pack(fill="x", padx=15, pady=4)
    ctk.CTkLabel(master=f1, text="Позиция Орудия (X;Y;Z):", font=("Roboto", 13, "bold"), width=180, anchor="w").pack(
        side="left", padx=5)
    xCannon = ctk.CTkEntry(master=f1, placeholder_text="X", validate="key", validatecommand=(isvalidinput, '%P'))
    yCannon = ctk.CTkEntry(master=f1, placeholder_text="Y", validate="key", validatecommand=(isvalidinput, '%P'))
    zCannon = ctk.CTkEntry(master=f1, placeholder_text="Z", validate="key", validatecommand=(isvalidinput, '%P'))
    xCannon.pack(side="left", padx=5, expand=True, fill="x")
    yCannon.pack(side="left", padx=5, expand=True, fill="x")
    zCannon.pack(side="left", padx=5, expand=True, fill="x")

    f2 = ctk.CTkFrame(master=frame)
    f2.pack(fill="x", padx=15, pady=4)
    ctk.CTkLabel(master=f2, text="Тип Орудия:", font=("Roboto", 13, "bold"), width=180, anchor="w").pack(side="left", padx=5)
    mode_selector = ctk.CTkSegmentedButton(master=f2, values=["Миномёт", "Пушка"], command=handle_mode_switch)
    mode_selector.pack(side="left", padx=5)
    params_frame = ctk.CTkFrame(master=f2, fg_color="transparent")
    params_frame.pack(side="left", padx=10)
    projectile_selector = ctk.CTkOptionMenu(master=params_frame, values=PROJECTILES, width=150, command=getAngles)
    projectile_selector.pack(side="left", padx=5)
    ctk.CTkLabel(master=params_frame, text="Порох:").pack(side="left", padx=5)
    entryPowder = ctk.CTkEntry(master=params_frame, placeholder_text="шт", validate="key",
                               validatecommand=(isvalidinput, '%P'), width=50)
    entryPowder.pack(side="left", padx=2)
    ctk.CTkLabel(master=params_frame, text="Ствол:").pack(side="left", padx=5)
    entryBarrel = ctk.CTkEntry(master=params_frame, placeholder_text="бл", validate="key",
                               validatecommand=(isvalidinput, '%P'), width=50)
    entryBarrel.pack(side="left", padx=2)

    f3 = ctk.CTkFrame(master=frame)
    f3.pack(fill="x", padx=15, pady=4)
    ctk.CTkLabel(master=f3, text="Позиция Цели (X;Y;Z):", font=("Roboto", 13, "bold"), width=180, anchor="w").pack(
        side="left", padx=5)
    xTarget = ctk.CTkEntry(master=f3, placeholder_text="X", validate="key", validatecommand=(isvalidinput, '%P'))
    yTarget = ctk.CTkEntry(master=f3, placeholder_text="Y", validate="key", validatecommand=(isvalidinput, '%P'))
    zTarget = ctk.CTkEntry(master=f3, placeholder_text="Z", validate="key", validatecommand=(isvalidinput, '%P'))
    xTarget.pack(side="left", padx=5, expand=True, fill="x")
    yTarget.pack(side="left", padx=5, expand=True, fill="x")
    zTarget.pack(side="left", padx=5, expand=True, fill="x")

    button = ctk.CTkButton(master=frame, text="Рассчитать Траекторию", command=getAngles, state="disabled", width=300,
                           height=36, font=("Roboto", 14, "bold"))
    button.pack(pady=8)

    res_frame = ctk.CTkFrame(master=frame, fg_color="#1e1e1e", border_width=2, border_color="#1E538D", corner_radius=12)
    res_frame.pack(fill="x", padx=20, pady=4)
    res_frame.columnconfigure(0, weight=1)
    res_frame.columnconfigure(1, weight=1)
    varYaw = ctk.StringVar(value="YAW (Поворот): ?")
    varSpeed = ctk.StringVar(value="V0: ?")
    varTolerance = ctk.StringVar(value="Погрешность: ±2 бл.")
    top_bar = ctk.CTkFrame(master=res_frame, fg_color="transparent")
    top_bar.grid(row=0, column=0, columnspan=2, pady=6, sticky="ew")
    ctk.CTkLabel(master=top_bar, textvariable=varYaw, font=("Roboto", 16, "bold"), text_color="#7cb1f2").pack(
        side="left", expand=True)
    ctk.CTkLabel(master=top_bar, textvariable=varSpeed, font=("Roboto", 14, "italic"), text_color="#aaaaaa").pack(
        side="left", expand=True)
    ctk.CTkLabel(master=top_bar, textvariable=varTolerance, font=("Roboto", 12), text_color="#888888").pack(
        side="left", expand=True)
    low_box = ctk.CTkFrame(master=res_frame, fg_color="#262626", corner_radius=8)
    low_box.grid(row=1, column=0, padx=15, pady=6, sticky="nsew")
    ctk.CTkLabel(master=low_box, text="1. НАСТИЛЬНАЯ (Прямой огонь)", font=("Roboto", 14, "bold"),
                 text_color="#50bc54").pack(pady=4)
    varLowPitch = ctk.StringVar(value="Pitch: ?")
    varLowTime = ctk.StringVar(value="Полет: ?")
    ctk.CTkLabel(master=low_box, textvariable=varLowPitch, font=("Roboto", 15, "bold")).pack(pady=2)
    ctk.CTkLabel(master=low_box, textvariable=varLowTime, font=("Roboto", 13)).pack(pady=2)
    high_box = ctk.CTkFrame(master=res_frame, fg_color="#262626", corner_radius=8)
    high_box.grid(row=1, column=1, padx=15, pady=6, sticky="nsew")
    ctk.CTkLabel(master=high_box, text="2. НАВЕСНАЯ (Гаубица)", font=("Roboto", 14, "bold"), text_color="#ffb03a").pack(
        pady=4)
    varHighPitch = ctk.StringVar(value="Pitch: ?")
    varHighTime = ctk.StringVar(value="Полет: ?")
    ctk.CTkLabel(master=high_box, textvariable=varHighPitch, font=("Roboto", 15, "bold")).pack(pady=2)
    ctk.CTkLabel(master=high_box, textvariable=varHighTime, font=("Roboto", 13)).pack(pady=2)
    statusMessage = ctk.StringVar(value="Ожидание ввода параметров...")
    status = ctk.CTkLabel(master=frame, textvariable=statusMessage, font=("Roboto", 13, "bold"))
    status.pack(pady=2)

    graphs_container = ctk.CTkFrame(master=frame, fg_color="#181818", corner_radius=12)
    graphs_container.pack(fill="both", expand=True, padx=15, pady=8)
    graphs_container.columnconfigure(0, weight=1)
    graphs_container.columnconfigure(1, weight=1)
    graphs_container.rowconfigure(0, weight=1)

    side_frame = ctk.CTkFrame(master=graphs_container, fg_color="#181818")
    side_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
    ctk.CTkLabel(master=side_frame, text="📐 Боковой вид (X-Y)", font=("Roboto", 12, "bold"), text_color="#7cb1f2").pack(pady=2)
    side_inner = ctk.CTkFrame(master=side_frame, fg_color="#181818")
    side_inner.pack(fill="both", expand=True, padx=2, pady=2)
    canvas_side = ctk.CTkCanvas(master=side_inner, bg="#181818", highlightthickness=0)
    canvas_side.pack(side="left", fill="both", expand=True)
    vbar_side = tk.Scrollbar(master=side_inner, orient="vertical")
    vbar_side.pack(side="right", fill="y")
    hbar_side = tk.Scrollbar(master=side_frame, orient="horizontal")
    hbar_side.pack(side="bottom", fill="x")

    top_frame = ctk.CTkFrame(master=graphs_container, fg_color="#181818")
    top_frame.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
    top_header = ctk.CTkFrame(master=top_frame, fg_color="transparent")
    top_header.pack(fill="x", pady=2)
    ctk.CTkLabel(master=top_header, text="🗺️ Вид сверху (X-Z)", font=("Roboto", 12, "bold"), text_color="#ffb03a").pack(side="left", padx=5)
    range_toggle_btn = ctk.CTkButton(master=top_header, text="🎯 Зона: ВЫКЛ", width=140, height=24,
                                     command=toggle_range_overlay, fg_color="#1E538D", font=("Roboto", 11))
    range_toggle_btn.pack(side="right", padx=5)
    top_inner = ctk.CTkFrame(master=top_frame, fg_color="#181818")
    top_inner.pack(fill="both", expand=True, padx=2, pady=2)
    canvas_top = ctk.CTkCanvas(master=top_inner, bg="#181818", highlightthickness=0)
    canvas_top.pack(side="left", fill="both", expand=True)
    vbar_top = tk.Scrollbar(master=top_inner, orient="vertical")
    vbar_top.pack(side="right", fill="y")
    hbar_top = tk.Scrollbar(master=top_frame, orient="horizontal")
    hbar_top.pack(side="bottom", fill="x")

    bind_canvas_events(canvas_side, cam_side)
    bind_canvas_events(canvas_top, cam_top, invert_y=True)

    calib_frame = ctk.CTkFrame(master=root, corner_radius=15)
    ctk.CTkLabel(master=calib_frame, text="🔧 Режим калибровки", font=("Roboto", 20, "bold"),
                 fg_color="#1E538D", corner_radius=10).pack(pady=10, padx=20, fill="x")
    help_text = ("Введите данные реального выстрела. Программа подберёт физические константы "
                 "под ваш модпак и сохранит их в calibration_config.json")
    ctk.CTkLabel(master=calib_frame, text=help_text, font=("Roboto", 12), text_color="#aaaaaa").pack(pady=2)
    cmode_frame = ctk.CTkFrame(master=calib_frame)
    cmode_frame.pack(fill="x", padx=15, pady=5)
    ctk.CTkLabel(master=cmode_frame, text="Тип орудия для калибровки:", font=("Roboto", 12, "bold"), width=250, anchor="w").pack(side="left", padx=5)
    calib_mode_selector = ctk.CTkSegmentedButton(master=cmode_frame, values=["Миномёт", "Пушка"], command=handle_calib_mode_switch)
    calib_mode_selector.pack(side="left", padx=5)
    cf1 = ctk.CTkFrame(master=calib_frame)
    cf1.pack(fill="x", padx=15, pady=5)
    ctk.CTkLabel(master=cf1, text="Позиция орудия (X;Y;Z):", font=("Roboto", 12, "bold"), width=250, anchor="w").pack(side="left", padx=5)
    calib_cX = ctk.CTkEntry(master=cf1, placeholder_text="X", validate="key", validatecommand=(isvalidinput, '%P'), width=100)
    calib_cY = ctk.CTkEntry(master=cf1, placeholder_text="Y", validate="key", validatecommand=(isvalidinput, '%P'), width=100)
    calib_cZ = ctk.CTkEntry(master=cf1, placeholder_text="Z", validate="key", validatecommand=(isvalidinput, '%P'), width=100)
    calib_cX.pack(side="left", padx=5)
    calib_cY.pack(side="left", padx=5)
    calib_cZ.pack(side="left", padx=5)
    cf2 = ctk.CTkFrame(master=calib_frame)
    cf2.pack(fill="x", padx=15, pady=5)
    ctk.CTkLabel(master=cf2, text="Факт. попадание (X;Y;Z):", font=("Roboto", 12, "bold"), width=250, anchor="w").pack(side="left", padx=5)
    calib_lX = ctk.CTkEntry(master=cf2, placeholder_text="X", validate="key", validatecommand=(isvalidinput, '%P'), width=100)
    calib_lY = ctk.CTkEntry(master=cf2, placeholder_text="Y", validate="key", validatecommand=(isvalidinput, '%P'), width=100)
    calib_lZ = ctk.CTkEntry(master=cf2, placeholder_text="Z", validate="key", validatecommand=(isvalidinput, '%P'), width=100)
    calib_lX.pack(side="left", padx=5)
    calib_lY.pack(side="left", padx=5)
    calib_lZ.pack(side="left", padx=5)
    cf3 = ctk.CTkFrame(master=calib_frame)
    cf3.pack(fill="x", padx=15, pady=5)
    ctk.CTkLabel(master=cf3, text="Углы выстрела:", font=("Roboto", 12, "bold"), width=250, anchor="w").pack(side="left", padx=5)
    pitch_frame = ctk.CTkFrame(master=cf3, fg_color="transparent")
    pitch_frame.pack(side="left", padx=5)
    ctk.CTkLabel(master=pitch_frame, text="Pitch (вертикальный):", font=("Roboto", 11), text_color="#7cb1f2").pack(anchor="w")
    calib_pitch = ctk.CTkEntry(master=pitch_frame, placeholder_text="например 43.7", validate="key", validatecommand=(isvalidinput, '%P'), width=120)
    calib_pitch.pack()
    yaw_frame = ctk.CTkFrame(master=cf3, fg_color="transparent")
    yaw_frame.pack(side="left", padx=15)
    ctk.CTkLabel(master=yaw_frame, text="Yaw (горизонтальный):", font=("Roboto", 11), text_color="#ffb03a").pack(anchor="w")
    calib_yaw = ctk.CTkEntry(master=yaw_frame, placeholder_text="например 90.0", validate="key", validatecommand=(isvalidinput, '%P'), width=120)
    calib_yaw.pack()
    airtime_frame = ctk.CTkFrame(master=cf3, fg_color="transparent")
    airtime_frame.pack(side="left", padx=15)
    ctk.CTkLabel(master=airtime_frame, text="Время полёта (сек, опц.):", font=("Roboto", 11), text_color="#50bc54").pack(anchor="w")
    calib_airtime = ctk.CTkEntry(master=airtime_frame, placeholder_text="например 24.5", validate="key", validatecommand=(isvalidinput, '%P'), width=120)
    calib_airtime.pack()
    calib_cannon_params_frame = ctk.CTkFrame(master=calib_frame)
    calib_cannon_params_frame.pack(fill="x", padx=15, pady=5)
    ctk.CTkLabel(master=calib_cannon_params_frame, text="Параметры пушки:", font=("Roboto", 12, "bold"), width=250, anchor="w").pack(side="left", padx=5)
    powder_frame = ctk.CTkFrame(master=calib_cannon_params_frame, fg_color="transparent")
    powder_frame.pack(side="left", padx=5)
    ctk.CTkLabel(master=powder_frame, text="Порох (шт):", font=("Roboto", 11)).pack(anchor="w")
    calib_powder = ctk.CTkEntry(master=powder_frame, placeholder_text="2", validate="key", validatecommand=(isvalidinput, '%P'), width=80)
    calib_powder.pack()
    barrel_frame = ctk.CTkFrame(master=calib_cannon_params_frame, fg_color="transparent")
    barrel_frame.pack(side="left", padx=15)
    ctk.CTkLabel(master=barrel_frame, text="Длина ствола (бл):", font=("Roboto", 11)).pack(anchor="w")
    calib_barrel = ctk.CTkEntry(master=barrel_frame, placeholder_text="4", validate="key", validatecommand=(isvalidinput, '%P'), width=80)
    calib_barrel.pack()
    btn_frame = ctk.CTkFrame(master=calib_frame, fg_color="transparent")
    btn_frame.pack(pady=10)
    ctk.CTkButton(master=btn_frame, text="➕ Добавить точку", command=add_calibration_point, width=160).pack(side="left", padx=5)
    ctk.CTkButton(master=btn_frame, text="🚀 Запустить калибровку", command=run_calibration, width=160, fg_color="#50bc54").pack(side="left", padx=5)
    ctk.CTkButton(master=btn_frame, text="🔄 Сбросить всё", command=reset_calib, width=120, fg_color="#980404").pack(side="left", padx=5)
    list_container = ctk.CTkFrame(master=calib_frame, fg_color="#1e1e1e", corner_radius=8)
    list_container.pack(fill="x", padx=20, pady=5)
    ctk.CTkLabel(master=list_container, text="Точки калибровки:", font=("Roboto", 12, "bold")).pack(anchor="w", padx=10, pady=5)
    calib_list_frame = ctk.CTkFrame(master=list_container, fg_color="transparent")
    calib_list_frame.pack(fill="x", padx=10, pady=5)
    calib_results_box = ctk.CTkTextbox(master=calib_frame, height=140, fg_color="#181818", font=("Consolas", 11))
    calib_results_box.pack(fill="x", padx=20, pady=5)
    calib_results_box.insert("0.0", "Результаты калибровки появятся здесь...")
    calib_status = ctk.StringVar(value="Готов к калибровке")
    calib_status_label = ctk.CTkLabel(master=calib_frame, textvariable=calib_status, font=("Roboto", 13, "bold"))
    calib_status_label.pack(pady=5)

    calc_frame.pack(fill="both", expand=True, padx=10, pady=5)
    calib_frame.pack_forget()
    mode_selector.set("Пушка")
    calib_mode_selector.set("Пушка")
    load_config()
    load_calibration_points()
    for widget in [xCannon, yCannon, zCannon, xTarget, yTarget, zTarget, entryPowder, entryBarrel]:
        widget.bind("<KeyRelease>", getAngles)
    root.bind("<Configure>", on_resize)

    def on_closing():
        save_window_state()
        save_config()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_closing)

    root.mainloop()


if __name__ == "__main__":
    main()
