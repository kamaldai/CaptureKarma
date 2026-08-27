from pathlib import Path

import pytest
import yaml

from capturekarma.scene import (
    ClickStep, CursorStep, MoveStep, PressStep, Region, SceneError, ScrollStep,
    StepTarget, TypeStep, WaitStep, dump_scene, load_scene, parse_scene, scene_to_dict,
)

WEB = {
    "version": 1,
    "name": "demo",
    "target": {"kind": "web", "url": "https://example.com", "viewport": [1280, 720]},
    "steps": [
        {"wait": 1.0},
        {"move": {"to": "text=Pricing"}},
        {"click": {}},
        {"scroll": {"by": 900, "duration": 2.5}},
        {"type": {"text": "hi", "delay": 0.06}},
        {"press": "Enter"},
        {"cursor": "hidden"},
        {"move": {"to": [640, 400], "duration": 1.2}},
        {"cursor": "visible"},
    ],
}


def test_parse_web_scene_defaults_and_steps():
    s = parse_scene(WEB)
    assert s.name == "demo" and s.target.kind == "web" and s.target.viewport == (1280, 720)
    assert s.output.fps == 60 and s.output.lead_in == 0.5 and s.cursor.speed == 1400
    assert s.defaults.easing == "ease_in_out_cubic" and s.defaults.hold == 0.6
    assert s.steps[0] == WaitStep(seconds=1.0)
    assert s.steps[1] == MoveStep(to=StepTarget(selector="text=Pricing"))
    assert s.steps[2] == ClickStep()
    assert s.steps[3] == ScrollStep(by=900, duration=2.5)
    assert s.steps[4] == TypeStep(text="hi", delay=0.06)
    assert s.steps[5] == PressStep(key="Enter")
    assert s.steps[6] == CursorStep(visible=False)
    assert s.steps[7] == MoveStep(to=StepTarget(at=(640, 400)), duration=1.2)


def test_parse_desktop_scene_with_window():
    s = parse_scene({"version": 1, "name": "d", "target": {"kind": "desktop", "window": "Notepad"},
                     "steps": [{"click": {"to": [10, 20]}}]})
    assert s.steps[0] == ClickStep(to=StepTarget(at=(10, 20)))


def test_parse_desktop_scene_with_region():
    s = parse_scene({"version": 1, "name": "d", "target": {"kind": "desktop", "region": [0, 0, 800, 600]},
                     "steps": []})
    assert s.target.region == Region(0, 0, 800, 600)


@pytest.mark.parametrize("bad, msg", [
    ({**WEB, "version": 2}, "version"),
    ({**WEB, "name": ""}, "name"),
    ({**WEB, "target": {"kind": "web"}}, "url"),
    ({**WEB, "target": {"kind": "desktop"}}, "window"),
    ({**WEB, "target": {"kind": "tv", "url": "x"}}, "kind"),
    ({**WEB, "bogus": 1}, "bogus"),
    ({**WEB, "steps": [{"jump": 1}]}, "jump"),
    ({**WEB, "steps": [{"move": {"to": "a"}, "click": {}}]}, "exactly one"),
    ({**WEB, "steps": [{"scroll": {}}]}, "by"),
    ({**WEB, "steps": [{"scroll": {"by": 1, "to": 2}}]}, "by"),
    ({**WEB, "steps": [{"wait": -1}]}, "negative"),
    ({**WEB, "steps": [{"move": {"to": "a", "duration": -1}}]}, "negative"),
    ({**WEB, "steps": [{"move": {"to": "a", "easing": "bouncy"}}]}, "easing"),
    ({**WEB, "steps": [{"cursor": "sometimes"}]}, "cursor"),
    ({**WEB, "steps": [{"move": {"to": "a", "bogus": 1}}]}, "bogus"),
    ({**WEB, "output": {"fps": 0}}, "fps"),
])
def test_invalid_scenes_raise_scene_error(bad, msg):
    with pytest.raises(SceneError) as ei:
        parse_scene(bad)
    assert msg in str(ei.value)


def test_step_index_is_reported():
    with pytest.raises(SceneError) as ei:
        parse_scene({**WEB, "steps": [{"wait": 1}, {"scroll": {}}]})
    assert ei.value.step_index == 1 and "step 2" in str(ei.value)


def test_desktop_rejects_selector_and_container_and_scroll_to():
    base = {"version": 1, "name": "d", "target": {"kind": "desktop", "window": "N"}}
    with pytest.raises(SceneError, match="selector"):
        parse_scene({**base, "steps": [{"move": {"to": "text=x"}}]})
    with pytest.raises(SceneError, match="in"):
        parse_scene({**base, "steps": [{"scroll": {"by": 1, "in": "#m"}}]})
    with pytest.raises(SceneError, match="to"):
        parse_scene({**base, "steps": [{"scroll": {"to": 100}}]})


def test_round_trip_through_yaml(tmp_path: Path):
    s = parse_scene(WEB)
    p = tmp_path / "s.yaml"
    dump_scene(s, p, header="recorded from https://example.com on 2026-08-27")
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# recorded from https://example.com on 2026-08-27\n")
    assert load_scene(p) == s
    assert yaml.safe_load(text)["steps"][6] == {"cursor": "hidden"}


def test_scene_to_dict_omits_defaults():
    d = scene_to_dict(parse_scene(WEB))
    assert d["steps"][2] == {"click": {}}
    assert d["steps"][5] == {"press": "Enter"}
    assert "duration" not in d["steps"][1]["move"]
