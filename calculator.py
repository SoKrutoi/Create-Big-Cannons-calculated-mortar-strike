from math import sin, cos, atan2, sqrt, radians, degrees
import json
import os

CALIBRATION_FILE = "calibration_config.json"

class OutOfRangeException(Exception):
    pass

DEFAULT_CONFIG = {
    "mortar": {
        "base_v": 8.32,
        "slope": 0.0,
        "drag": 1.0,
        "gravity": -0.05,
        "actual_length": 1.0,
        "tolerance": 2.0
    },
    "cannon": {
        "length_2": {"base_v": 7.28, "slope": 0.0147, "drag": 1.0, "gravity": -0.05, "actual_length": 2.0},
        "length_4": {"base_v": 10.415, "slope": 0.0140, "drag": 1.0, "gravity": -0.05, "actual_length": 4.0},
        "tolerance": 2.0
    }
}

def load_calibration():
    if os.path.exists(CALIBRATION_FILE):
        try:
            with open(CALIBRATION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_calibration(config):
    with open(CALIBRATION_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

calibration = load_calibration()

def get_params(mode, length=None):
    if mode == "mortar":
        return calibration.get("mortar", DEFAULT_CONFIG["mortar"]).copy()
    else:
        cfg = calibration.get("cannon", DEFAULT_CONFIG["cannon"])
        if length <= 2:
            return cfg.get("length_2", DEFAULT_CONFIG["cannon"]["length_2"]).copy()
        elif length >= 4:
            return cfg.get("length_4", DEFAULT_CONFIG["cannon"]["length_4"]).copy()
        else:
            t = (length - 2) / 2.0
            l2 = cfg.get("length_2", DEFAULT_CONFIG["cannon"]["length_2"])
            l4 = cfg.get("length_4", DEFAULT_CONFIG["cannon"]["length_4"])
            return {
                "base_v": l2["base_v"] + (l4["base_v"] - l2["base_v"]) * t,
                "slope": l2["slope"] + (l4["slope"] - l2["slope"]) * t,
                "drag": l2.get("drag", 1.0),
                "gravity": l2.get("gravity", -0.05),
                "actual_length": length,
                "tolerance": cfg.get("tolerance", 2.0)
            }

def simulate(pitch_deg, params, cannon_y=0, target_y=0, max_ticks=3000):
    base_v = params["base_v"]
    slope = params.get("slope", 0.0)
    drag = params.get("drag", 1.0)
    gravity = params.get("gravity", -0.05)
    actual_length = params.get("actual_length", 1.0)

    initial_speed = base_v - slope * pitch_deg
    pitch_rad = radians(pitch_deg)

    x_start = actual_length * cos(pitch_rad)
    y_start = cannon_y + sin(pitch_rad) * actual_length

    pos_x = 0.0
    pos_y = y_start

    vel_x = cos(pitch_rad) * initial_speed
    vel_y = sin(pitch_rad) * initial_speed

    path = [(0.0, cannon_y), (x_start, y_start)]

    last_x, last_y = pos_x, pos_y
    ticks = 0

    while ticks < max_ticks:
        path.append((pos_x + x_start, pos_y))

        if ticks > 0 and vel_y < 0 and pos_y <= target_y and last_y > target_y:
            if pos_y != last_y:
                t_frac = (last_y - target_y) / (last_y - pos_y)
                exact_x = last_x + t_frac * (pos_x - last_x)
                landing_x = exact_x + x_start
                landing_ticks = (ticks - 1) + t_frac
                return pos_y, landing_ticks, path, True, landing_x

        if vel_y < 0 and pos_y < (target_y - 200):
            break

        last_x, last_y = pos_x, pos_y
        pos_x += vel_x
        pos_y += vel_y

        vel_x *= drag
        vel_y = vel_y * drag + gravity
        ticks += 1

    landing_x = pos_x + x_start
    return pos_y, float(ticks), path, False, landing_x

def simulate_distance(pitch_deg, params, cannon_y=0, target_y=0):
    _, ticks, _, _, landing_x = simulate(pitch_deg, params, cannon_y, target_y)
    return landing_x, ticks

def evaluate_pitch(pitch_deg, cannon, target, params):
    dx = target[0] - cannon[0]
    dz = target[2] - cannon[2]
    distance_to_target = sqrt(dx * dx + dz * dz)

    exact_y, exact_ticks, path, reached, landing_x = simulate(
        pitch_deg, params, cannon[1], target[1]
    )

    target_x_offset = distance_to_target
    for i in range(1, len(path)):
        px1, py1 = path[i-1]
        px2, py2 = path[i]
        if (px1 <= target_x_offset <= px2) or (px1 >= target_x_offset >= px2):
            if px2 != px1:
                t = (target_x_offset - px1) / (px2 - px1)
                exact_y_at_target = py1 + t * (py2 - py1)
                return exact_y_at_target, exact_ticks, path, True

    return exact_y, exact_ticks, path, False

def binary_search_pitch(low, high, cannon, target, params):
    target_y = target[1]
    tolerance = 1e-4
    max_iters = 50

    for _ in range(max_iters):
        mid = (low + high) / 2.0
        exact_y, _, _, reached = evaluate_pitch(mid, cannon, target, params)

        if not reached:
            high = mid
            continue

        diff = exact_y - target_y
        if abs(diff) < tolerance:
            return mid

        low_y, _, _, low_reached = evaluate_pitch(low, cannon, target, params)
        if low_reached:
            if (low_y - target_y) * diff < 0:
                high = mid
            else:
                low = mid
        else:
            low = mid

    return (low + high) / 2.0

def BallisticsToTarget(cannon, target, power, length, mode, projectile_type):
    params = get_params(mode, length)
    tolerance = params.get("tolerance", 2.0)

    dx = target[0] - cannon[0]
    dz = target[2] - cannon[2]
    distance = sqrt(dx * dx + dz * dz)

    yaw = 180.0 + atan2(dx, -dz) * 57.2957795131
    yaw = yaw % 360.0

    if mode == "mortar":
        min_p, max_p = 15.0, 85.0
    else:
        min_p, max_p = -30.0, 60.0

    intervals = []
    steps = 300
    pitches = [min_p + (max_p - min_p) * i / (steps - 1) for i in range(steps)]

    last_pitch = None
    last_diff = None

    for p in pitches:
        exact_y, _, _, reached = evaluate_pitch(p, cannon, target, params)
        if reached:
            current_diff = exact_y - target[1]
        else:
            current_diff = -999999.0

        if last_pitch is not None:
            if last_diff != -999999.0 and current_diff != -999999.0:
                if (last_diff <= 0 and current_diff > 0) or (last_diff >= 0 and current_diff < 0):
                    intervals.append((last_pitch, p))
            elif (last_diff == -999999.0 and current_diff > 0) or (last_diff > 0 and current_diff == -999999.0):
                intervals.append((last_pitch, p))

        last_pitch = p
        last_diff = current_diff

    if not intervals:
        raise OutOfRangeException("Цель недостижима в рамках разрешенных углов орудия!")

    found_pitches = []
    for low_b, high_b in intervals:
        exact_p = binary_search_pitch(low_b, high_b, cannon, target, params)
        found_pitches.append(exact_p)

    found_pitches = sorted(list(set(found_pitches)))

    low_sol = None
    high_sol = None

    if found_pitches:
        p1 = found_pitches[0]
        _, ticks1, path1, _ = evaluate_pitch(p1, cannon, target, params)
        low_sol = {"pitch": p1, "time": round(ticks1 / 20.0, 2), "path": path1}

        high_pitches = [p for p in found_pitches if abs(p - p1) > 1.0]
        if high_pitches:
            p2 = high_pitches[-1]
            _, ticks2, path2, _ = evaluate_pitch(p2, cannon, target, params)
            high_sol = {"pitch": p2, "time": round(ticks2 / 20.0, 2), "path": path2}

    display_speed = params["base_v"] - params.get("slope", 0.0) * (found_pitches[0] if found_pitches else 0)

    return {
        "yaw": yaw,
        "speed": round(display_speed, 2),
        "low": low_sol,
        "high": high_sol,
        "distance": distance,
        "tolerance": tolerance
    }

# ===== ПРЕДВАРИТЕЛЬНЫЙ РАСЧЁТ ДЛЯ КАРТЫ ДОСЯГАЕМОСТИ =====

def precompute_landing_curves(cannon_y, target_y, params, mode):
    """Возвращает список (pitch, distance) для быстрой проверки досягаемости."""
    if mode == "mortar":
        pitches = [i * 3.0 for i in range(5, 29)]   # 15° .. 84°
    else:
        pitches = [i * 3.0 for i in range(-10, 21)] # -30° .. 60°

    curves = []
    for p in pitches:
        dist, _ = simulate_distance(p, params, cannon_y, target_y)
        curves.append((p, dist))
    return curves

def check_trajectories_from_curves(curves, target_distance, threshold=5.0):
    """
    На основе предвычисленных кривых определяет, есть ли low/high решение.
    threshold — допустимая погрешность совпадения дальности.
    Возвращает (has_low, has_high).
    """
    has_low = False
    has_high = False

    for i in range(len(curves) - 1):
        p1, d1 = curves[i]
        p2, d2 = curves[i + 1]

        # Проверяем, пересекает ли target_distance отрезок [d1, d2]
        if (d1 <= target_distance <= d2) or (d2 <= target_distance <= d1):
            mid_pitch = (p1 + p2) / 2.0
            if mid_pitch < 45:
                has_low = True
            else:
                has_high = True

        # Также проверяем прямое совпадение в пределах threshold
        if abs(d1 - target_distance) <= threshold:
            if p1 < 45:
                has_low = True
            else:
                has_high = True

    # Последняя точка
    p_last, d_last = curves[-1]
    if abs(d_last - target_distance) <= threshold:
        if p_last < 45:
            has_low = True
        else:
            has_high = True

    return has_low, has_high

def generate_range_map(cannon_y, target_y, params, mode, max_dist=None, step=10):
    """
    Генерирует словарь {distance: (has_low, has_high)} для быстрой отрисовки heatmap.
    """
    curves = precompute_landing_curves(cannon_y, target_y, params, mode)

    # Определяем максимальную дальность
    all_dists = [d for _, d in curves]
    if max_dist is None:
        max_dist = max(all_dists) * 1.1

    range_map = {}
    d = 0.0
    while d <= max_dist:
        has_low, has_high = check_trajectories_from_curves(curves, d)
        range_map[round(d, 1)] = (has_low, has_high)
        d += step

    return range_map, max_dist

# ===== КАЛИБРОВКА =====

def calibrate(mode, data_points, length=None):
    best_err = float('inf')
    best = None

    def real_distance(pt):
        dx = pt["landing"][0] - pt["cannon"][0]
        dz = pt["landing"][2] - pt["cannon"][2]
        return sqrt(dx * dx + dz * dz)

    def real_time(pt):
        return pt.get("airtime", None)

    if mode == "mortar":
        for base_v in [i * 0.05 for i in range(100, 220)]:
            for drag in [1.0, 0.9999, 0.9995, 0.999, 0.998, 0.995, 0.99]:
                for gravity in [-0.08, -0.07, -0.06, -0.05, -0.045, -0.04, -0.035, -0.03, -0.025, -0.02]:
                    err = 0
                    for pt in data_points:
                        params = {
                            "base_v": base_v, "slope": 0.0, "drag": drag,
                            "gravity": gravity, "actual_length": 1.0
                        }
                        sim_dist, sim_ticks = simulate_distance(pt["pitch"], params, pt["cannon"][1], pt["landing"][1])
                        dist_err = (sim_dist - real_distance(pt)) ** 2
                        t = real_time(pt)
                        if t is not None:
                            time_err = ((sim_ticks / 20.0) - t) ** 2 * 100
                            err += dist_err + time_err
                        else:
                            err += dist_err
                    if err < best_err:
                        best_err = err
                        best = {"base_v": base_v, "slope": 0.0, "drag": drag, "gravity": gravity, "actual_length": 1.0}

        if best:
            bv_c = best["base_v"]
            for base_v in [bv_c + i * 0.002 for i in range(-25, 26)]:
                for drag in [best["drag"]]:
                    for gravity in [best["gravity"]]:
                        err = 0
                        for pt in data_points:
                            params = {
                                "base_v": base_v, "slope": 0.0, "drag": drag,
                                "gravity": gravity, "actual_length": 1.0
                            }
                            sim_dist, sim_ticks = simulate_distance(pt["pitch"], params, pt["cannon"][1], pt["landing"][1])
                            dist_err = (sim_dist - real_distance(pt)) ** 2
                            t = real_time(pt)
                            if t is not None:
                                time_err = ((sim_ticks / 20.0) - t) ** 2 * 100
                                err += dist_err + time_err
                            else:
                                err += dist_err
                        if err < best_err:
                            best_err = err
                            best = {"base_v": base_v, "slope": 0.0, "drag": drag, "gravity": gravity, "actual_length": 1.0}

    else:
        cannon_len = length if length else (data_points[0].get("length", 4.0) if data_points else 4.0)

        for base_v in [i * 0.05 for i in range(100, 300)]:
            for slope in [i * 0.0005 for i in range(0, 50)]:
                for drag in [1.0, 0.9995, 0.999, 0.998, 0.995, 0.99]:
                    err = 0
                    for pt in data_points:
                        params = {
                            "base_v": base_v, "slope": slope, "drag": drag,
                            "gravity": -0.05, "actual_length": pt.get("length", cannon_len)
                        }
                        sim_dist, sim_ticks = simulate_distance(pt["pitch"], params, pt["cannon"][1], pt["landing"][1])
                        dist_err = (sim_dist - real_distance(pt)) ** 2
                        t = real_time(pt)
                        if t is not None:
                            time_err = ((sim_ticks / 20.0) - t) ** 2 * 100
                            err += dist_err + time_err
                        else:
                            err += dist_err
                    if err < best_err:
                        best_err = err
                        best = {"base_v": base_v, "slope": slope, "drag": drag, "gravity": -0.05, "actual_length": cannon_len}

        if best:
            bv_c = best["base_v"]
            s_c = best["slope"]
            for base_v in [bv_c + i * 0.002 for i in range(-25, 26)]:
                for slope in [s_c + i * 0.00005 for i in range(-20, 21)]:
                    for drag in [best["drag"]]:
                        err = 0
                        for pt in data_points:
                            params = {
                                "base_v": base_v, "slope": slope, "drag": drag,
                                "gravity": -0.05, "actual_length": pt.get("length", cannon_len)
                            }
                            sim_dist, sim_ticks = simulate_distance(pt["pitch"], params, pt["cannon"][1], pt["landing"][1])
                            dist_err = (sim_dist - real_distance(pt)) ** 2
                            t = real_time(pt)
                            if t is not None:
                                time_err = ((sim_ticks / 20.0) - t) ** 2 * 100
                                err += dist_err + time_err
                            else:
                                err += dist_err
                        if err < best_err:
                            best_err = err
                            best = {"base_v": base_v, "slope": slope, "drag": drag, "gravity": -0.05, "actual_length": cannon_len}

    rmse = sqrt(best_err / len(data_points)) if data_points and best else 0
    return best, rmse

def apply_calibration(mode, params, length=None):
    global calibration
    if mode == "mortar":
        calibration["mortar"] = params
    else:
        if "cannon" not in calibration:
            calibration["cannon"] = DEFAULT_CONFIG["cannon"].copy()
        if length is None:
            length = params.get("actual_length", 4.0)
        if length <= 2:
            calibration["cannon"]["length_2"] = params
        elif length >= 4:
            calibration["cannon"]["length_4"] = params
        else:
            calibration["cannon"]["length_2"] = params
            calibration["cannon"]["length_4"] = params
    save_calibration(calibration)

def reset_calibration():
    global calibration
    calibration = DEFAULT_CONFIG.copy()
    save_calibration(calibration)
