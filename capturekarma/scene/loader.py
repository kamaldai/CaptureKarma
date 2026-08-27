"""YAML <-> Scene with strict validation."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .model import (
    EASING_NAMES, ClickStep, CursorConfig, CursorStep, Defaults, MoveStep, Output, Point,
    PressStep, Region, Scene, ScrollStep, Step, StepTarget, Target, TypeStep, WaitStep,
)

STEP_KEYS = ("wait", "move", "click", "scroll", "type", "press", "cursor")
OVERRIDE_KEYS = ("duration", "easing", "hold")


class SceneError(ValueError):
    def __init__(self, message: str, step_index: int | None = None):
        prefix = f"step {step_index + 1}: " if step_index is not None else ""
        super().__init__(prefix + message)
        self.step_index = step_index


def _require_keys(d: dict, allowed: tuple[str, ...], where: str, idx: int | None = None) -> None:
    unknown = sorted(set(d) - set(allowed))
    if unknown:
        raise SceneError(f"{where}: unknown key(s) {', '.join(unknown)}", idx)


def _point(v: Any, where: str, idx: int | None) -> Point:
    if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(n, int) for n in v)):
        raise SceneError(f"{where}: expected [x, y] integers, got {v!r}", idx)
    return (int(v[0]), int(v[1]))


def _non_negative(v: Any, name: str, idx: int | None) -> float:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
        raise SceneError(f"{name} must be a non-negative number, got {v!r} (negative or invalid)", idx)
    return float(v)


def _target(v: Any, kind: str, idx: int) -> StepTarget:
    if isinstance(v, str):
        if kind == "desktop":
            raise SceneError("desktop scenes cannot use a selector target; use [x, y]", idx)
        if not v:
            raise SceneError("selector must not be empty", idx)
        return StepTarget(selector=v)
    return StepTarget(at=_point(v, "to", idx))


def _overrides(d: dict, idx: int) -> dict:
    out: dict[str, Any] = {}
    if "duration" in d:
        out["duration"] = _non_negative(d["duration"], "duration", idx)
    if "hold" in d:
        out["hold"] = _non_negative(d["hold"], "hold", idx)
    if "easing" in d:
        if d["easing"] not in EASING_NAMES:
            raise SceneError(f"unknown easing {d['easing']!r}; choose from {', '.join(EASING_NAMES)}", idx)
        out["easing"] = d["easing"]
    return out


def _parse_step(raw: Any, kind: str, idx: int) -> Step:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise SceneError("each step must be a mapping with exactly one key "
                         f"(one of {', '.join(STEP_KEYS)}), got {raw!r}", idx)
    (key, val), = raw.items()
    if key not in STEP_KEYS:
        raise SceneError(f"unknown step type {key!r}; choose from {', '.join(STEP_KEYS)}", idx)

    if key == "wait":
        if isinstance(val, dict):
            _require_keys(val, ("seconds",) + OVERRIDE_KEYS, "wait", idx)
            return WaitStep(seconds=_non_negative(val.get("seconds", 0), "wait", idx), **_overrides(val, idx))
        return WaitStep(seconds=_non_negative(val, "wait", idx))
    if key == "press":
        if isinstance(val, dict):
            _require_keys(val, ("key",) + OVERRIDE_KEYS, "press", idx)
            k = val.get("key")
        else:
            k = val
        if not isinstance(k, str) or not k:
            raise SceneError("press needs a key name, e.g. Enter", idx)
        return PressStep(key=k, **(_overrides(val, idx) if isinstance(val, dict) else {}))
    if key == "cursor":
        if val not in ("visible", "hidden"):
            raise SceneError(f"cursor must be 'visible' or 'hidden', got {val!r}", idx)
        return CursorStep(visible=(val == "visible"))

    if not isinstance(val, dict):
        raise SceneError(f"{key} step must be a mapping, got {val!r}", idx)
    ov = _overrides(val, idx)
    if key == "move":
        _require_keys(val, ("to",) + OVERRIDE_KEYS, "move", idx)
        if "to" not in val:
            raise SceneError("move needs a 'to' target", idx)
        return MoveStep(to=_target(val["to"], kind, idx), **ov)
    if key == "click":
        _require_keys(val, ("to", "button") + OVERRIDE_KEYS, "click", idx)
        button = val.get("button", "left")
        if button not in ("left", "right", "middle"):
            raise SceneError(f"click button must be left/right/middle, got {button!r}", idx)
        to = _target(val["to"], kind, idx) if "to" in val else None
        return ClickStep(to=to, button=button, **ov)
    if key == "scroll":
        _require_keys(val, ("by", "to", "in") + OVERRIDE_KEYS, "scroll", idx)
        has_by, has_to = "by" in val, "to" in val
        if has_by == has_to:
            raise SceneError("scroll needs exactly one of 'by' or 'to'", idx)
        if kind == "desktop":
            if has_to:
                raise SceneError("scroll 'to' is only supported for web scenes; use 'by'", idx)
            if "in" in val:
                raise SceneError("scroll 'in' (container) is only supported for web scenes", idx)
        if "in" in val and (not isinstance(val["in"], str) or not val["in"].strip()):
            raise SceneError("scroll 'in' must be a non-empty selector", idx)
        for k in ("by", "to"):
            if k in val and (not isinstance(val[k], int) or isinstance(val[k], bool)):
                raise SceneError(f"scroll '{k}' must be an integer number of pixels", idx)
        return ScrollStep(by=val.get("by"), to=val.get("to"), container=val.get("in"), **ov)
    # type
    _require_keys(val, ("text", "delay") + OVERRIDE_KEYS, "type", idx)
    if not isinstance(val.get("text"), str):
        raise SceneError("type needs a 'text' string", idx)
    return TypeStep(text=val["text"], delay=_non_negative(val.get("delay", 0.05), "delay", idx), **ov)


def parse_scene(data: Any) -> Scene:
    if not isinstance(data, dict):
        raise SceneError("scene file must be a mapping at the top level")
    _require_keys(data, ("version", "name", "target", "output", "cursor", "defaults", "steps"), "scene")
    if data.get("version") != 1:
        raise SceneError(f"unsupported scene version {data.get('version')!r}; expected 1")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise SceneError("scene needs a non-empty 'name'")

    t = data.get("target")
    if not isinstance(t, dict):
        raise SceneError("scene needs a 'target' mapping")
    _require_keys(t, ("kind", "url", "viewport", "window", "region"), "target")
    kind = t.get("kind")
    if kind not in ("web", "desktop"):
        raise SceneError(f"target.kind must be 'web' or 'desktop', got {kind!r}")
    if kind == "web" and not t.get("url"):
        raise SceneError("web target needs a 'url'")
    if kind == "desktop" and not (t.get("window") or t.get("region")):
        raise SceneError("desktop target needs a 'window' title or a 'region' [x, y, w, h]")
    if t.get("window") is not None and (not isinstance(t["window"], str) or not t["window"].strip()):
        raise SceneError(f"target.window must be a non-empty string, got {t['window']!r}")
    viewport = (1920, 1080)
    if "viewport" in t:
        vp = t["viewport"]
        if not (isinstance(vp, list) and len(vp) == 2 and all(isinstance(n, int) and n > 0 for n in vp)):
            raise SceneError("target.viewport must be [width, height] positive integers")
        viewport = (vp[0], vp[1])
    region = None
    if t.get("region") is not None:
        r = t["region"]
        if not (isinstance(r, list) and len(r) == 4 and all(isinstance(n, int) for n in r)) or r[2] <= 0 or r[3] <= 0:
            raise SceneError("target.region must be [x, y, width, height] with positive size")
        region = Region(*r)
    target = Target(kind=kind, url=t.get("url"), viewport=viewport, window=t.get("window"), region=region)

    o = data.get("output", {}) or {}
    _require_keys(o, ("fps", "dir", "lead_in", "lead_out"), "output")
    fps = o.get("fps", 60)
    if not isinstance(fps, int) or isinstance(fps, bool) or not 1 <= fps <= 240:
        raise SceneError(f"output.fps must be an integer 1..240, got {fps!r}")
    output = Output(fps=fps, dir=str(o.get("dir", Output.dir)),
                    lead_in=_non_negative(o.get("lead_in", 0.5), "output.lead_in", None),
                    lead_out=_non_negative(o.get("lead_out", 0.5), "output.lead_out", None))

    c = data.get("cursor", {}) or {}
    _require_keys(c, ("visible", "style", "ripple", "speed"), "cursor")
    speed = c.get("speed", 1400)
    if not isinstance(speed, (int, float)) or speed <= 0:
        raise SceneError("cursor.speed must be a positive number (px/s)")
    cursor = CursorConfig(visible=bool(c.get("visible", True)), style=str(c.get("style", "default")),
                          ripple=bool(c.get("ripple", True)), speed=float(speed))

    d = data.get("defaults", {}) or {}
    _require_keys(d, ("easing", "hold"), "defaults")
    easing = d.get("easing", "ease_in_out_cubic")
    if easing not in EASING_NAMES:
        raise SceneError(f"defaults.easing unknown easing {easing!r}; choose from {', '.join(EASING_NAMES)}")
    defaults = Defaults(easing=easing, hold=_non_negative(d.get("hold", 0.6), "defaults.hold", None))

    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        raise SceneError("'steps' must be a list")
    steps = tuple(_parse_step(s, kind, i) for i, s in enumerate(raw_steps))
    return Scene(name=name.strip(), target=target, steps=steps, output=output, cursor=cursor,
                 defaults=defaults, version=1)


def load_scene(path: str | Path) -> Scene:
    p = Path(path)
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SceneError(f"{p}: invalid YAML: {exc}") from exc
    except OSError as exc:
        raise SceneError(f"{p}: cannot read scene file: {exc}") from exc
    return parse_scene(data)


def _target_out(t: StepTarget) -> Any:
    return t.selector if t.selector is not None else list(t.at)  # type: ignore[arg-type]


def _step_to_dict(step: Step) -> dict:
    ov = {k: v for k, v in (("duration", step.duration), ("easing", step.easing), ("hold", step.hold)) if v is not None}
    if isinstance(step, WaitStep):
        return {"wait": step.seconds} if not ov else {"wait": {"seconds": step.seconds, **ov}}
    if isinstance(step, MoveStep):
        return {"move": {"to": _target_out(step.to), **ov}}
    if isinstance(step, ClickStep):
        body: dict = {}
        if step.to is not None:
            body["to"] = _target_out(step.to)
        if step.button != "left":
            body["button"] = step.button
        return {"click": {**body, **ov}}
    if isinstance(step, ScrollStep):
        body = {"by": step.by} if step.by is not None else {"to": step.to}
        if step.container is not None:
            body["in"] = step.container
        return {"scroll": {**body, **ov}}
    if isinstance(step, TypeStep):
        body = {"text": step.text}
        if step.delay != 0.05:
            body["delay"] = step.delay
        return {"type": {**body, **ov}}
    if isinstance(step, PressStep):
        return {"press": step.key} if not ov else {"press": {"key": step.key, **ov}}
    if isinstance(step, CursorStep):
        return {"cursor": "visible" if step.visible else "hidden"}
    raise TypeError(f"unknown step {step!r}")


def scene_to_dict(scene: Scene) -> dict:
    t: dict[str, Any] = {"kind": scene.target.kind}
    if scene.target.kind == "web":
        t["url"] = scene.target.url
        t["viewport"] = list(scene.target.viewport)
    else:
        if scene.target.window is not None:
            t["window"] = scene.target.window
        if scene.target.region:
            r = scene.target.region
            t["region"] = [r.x, r.y, r.width, r.height]
    return {
        "version": 1,
        "name": scene.name,
        "target": t,
        "output": asdict(scene.output),
        "cursor": asdict(scene.cursor),
        "defaults": asdict(scene.defaults),
        "steps": [_step_to_dict(s) for s in scene.steps],
    }


class _Dumper(yaml.SafeDumper):
    pass


def _represent_list_flow(dumper: yaml.SafeDumper, data: list):
    # Short numeric lists ([x, y], [w, h], [x, y, w, h]) render inline for readability.
    flow = len(data) <= 4 and all(isinstance(v, (int, float)) for v in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_Dumper.add_representer(list, _represent_list_flow)


def dump_scene(scene: Scene, path: str | Path, header: str | None = None) -> None:
    text = yaml.dump(scene_to_dict(scene), Dumper=_Dumper, sort_keys=False, allow_unicode=True)
    if header:
        text = "# " + header.strip() + "\n" + text
    Path(path).write_text(text, encoding="utf-8", newline="\n")
