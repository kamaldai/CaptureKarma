from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from capturekarma.scene import (
    ClickStep, CursorStep, MoveStep, PressStep, Region, SceneError, ScrollStep,
    StepTarget, Target, TypeStep, WaitStep, dump_scene, load_scene, parse_scene, scene_to_dict,
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


def test_empty_container_and_window_are_rejected():
    with pytest.raises(SceneError) as ei:
        parse_scene({**WEB, "steps": [{"scroll": {"by": 1, "in": ""}}]})
    assert "in" in str(ei.value) and "non-empty" in str(ei.value)

    with pytest.raises(SceneError) as ei:
        parse_scene({"version": 1, "name": "d", "steps": [],
                     "target": {"kind": "desktop", "window": "", "region": [0, 0, 10, 10]}})
    assert "window" in str(ei.value) and "non-empty" in str(ei.value)


def test_round_trip_preserves_container_and_window(tmp_path: Path):
    web = parse_scene({**WEB, "steps": [{"scroll": {"by": 300, "in": "#box"}}]})
    assert web.steps[0] == ScrollStep(by=300, container="#box")
    p = tmp_path / "web.yaml"
    dump_scene(web, p)
    assert load_scene(p) == web
    assert yaml.safe_load(p.read_text(encoding="utf-8"))["steps"][0]["scroll"]["in"] == "#box"

    desk = parse_scene({"version": 1, "name": "d", "target": {"kind": "desktop", "window": "Notepad"},
                        "steps": [{"scroll": {"by": 120}}]})
    assert desk.target.window == "Notepad"
    q = tmp_path / "desk.yaml"
    dump_scene(desk, q)
    assert load_scene(q) == desk
    assert yaml.safe_load(q.read_text(encoding="utf-8"))["target"]["window"] == "Notepad"


def test_scene_to_dict_never_silently_drops_a_set_field():
    """Model-built scenes can hold values parse_scene rejects; dumping must not swallow them."""
    web = parse_scene(WEB)
    d = scene_to_dict(replace(web, steps=(ScrollStep(by=1, container=""),)))
    assert d["steps"][0]["scroll"]["in"] == ""

    d = scene_to_dict(replace(web, target=Target(kind="desktop", window="", region=Region(0, 0, 8, 6))))
    assert d["target"]["window"] == ""


EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
FIXTURE_PAGE = Path(__file__).resolve().parent / "fixtures" / "page.html"


@pytest.mark.parametrize("section", ["output", "cursor", "defaults"])
def test_scalar_section_is_rejected_as_not_a_mapping(section):
    bad = {**WEB, section: 5}
    with pytest.raises(SceneError, match=f"{section} must be a mapping"):
        parse_scene(bad)


@pytest.mark.parametrize("section", ["output", "cursor", "defaults"])
def test_list_section_is_rejected_as_not_a_mapping(section):
    with pytest.raises(SceneError, match=f"{section} must be a mapping"):
        parse_scene({**WEB, section: ["fps"]})


@pytest.mark.parametrize("section", ["output", "cursor", "defaults"])
def test_null_section_falls_back_to_defaults(section):
    scene = parse_scene({**WEB, section: None})
    assert getattr(scene, section if section != "cursor" else "cursor") is not None


@pytest.mark.parametrize("name", ["a/b", "a\\b", "c:name", "star*", "q?", 'quo"te', "lt<", "gt>", "pipe|",
                                  ".hidden", "trailing.", " leading", "trailing "])
def test_name_rejects_characters_illegal_in_file_names(name):
    with pytest.raises(SceneError, match="name contains characters not allowed in file names"):
        parse_scene({**WEB, "name": name})


@pytest.mark.parametrize("name", ["demo", "web-demo", "my scene 2", "v1.2 demo"])
def test_name_accepts_ordinary_names(name):
    assert parse_scene({**WEB, "name": name}).name == name


def test_step_target_without_selector_or_coordinates_raises_scene_error():
    from capturekarma.scene.loader import _target_out

    with pytest.raises(SceneError, match="step target needs a selector or coordinates"):
        _target_out(StepTarget())


def test_dump_scene_reports_an_empty_step_target_as_a_scene_error(tmp_path: Path):
    scene = parse_scene(WEB)
    broken = replace(scene, steps=(MoveStep(to=StepTarget()),))
    with pytest.raises(SceneError, match="step target needs a selector or coordinates"):
        dump_scene(broken, tmp_path / "broken.yaml")


# ---- portable (scene-relative) web URLs ----

def _write(path: Path, url: str) -> Path:
    path.write_text(f"version: 1\nname: rel\ntarget: {{kind: web, url: {url!r}}}\nsteps: []\n",
                    encoding="utf-8")
    return path


def test_relative_web_url_resolves_against_the_scene_directory(tmp_path: Path):
    page = tmp_path / "page.html"
    page.write_text("<!doctype html><title>x</title>", encoding="utf-8")
    scene = load_scene(_write(tmp_path / "s.yaml", "page.html"))
    assert scene.target.url == page.resolve().as_uri()


def test_relative_web_url_may_climb_out_of_the_scene_directory(tmp_path: Path):
    sub = tmp_path / "scenes"
    sub.mkdir()
    page = tmp_path / "page.html"
    page.write_text("<!doctype html><title>x</title>", encoding="utf-8")
    scene = load_scene(_write(sub / "s.yaml", "../page.html"))
    assert scene.target.url == page.resolve().as_uri()


def test_missing_relative_web_url_raises_scene_error(tmp_path: Path):
    with pytest.raises(SceneError, match="nope.html"):
        load_scene(_write(tmp_path / "s.yaml", "nope.html"))


@pytest.mark.parametrize("url", ["https://example.com/pricing", "http://localhost:8000/",
                                 "file:///C:/tmp/page.html", "about:blank"])
def test_urls_with_a_scheme_are_left_untouched(tmp_path: Path, url):
    assert load_scene(_write(tmp_path / "s.yaml", url)).target.url == url


def test_parse_scene_leaves_relative_urls_alone():
    """parse_scene has no file context, so it cannot (and must not) resolve a relative path."""
    assert parse_scene({**WEB, "target": {"kind": "web", "url": "page.html"}}).target.url == "page.html"


@pytest.mark.parametrize("path", sorted(EXAMPLES_DIR.glob("*.yaml")), ids=lambda p: p.name)
def test_shipped_examples_load(path: Path):
    scene = load_scene(path)
    assert scene.steps
    if scene.target.kind == "web":
        assert scene.target.url and ("://" in scene.target.url or scene.target.url.startswith("about:"))


def test_web_example_points_at_the_bundled_fixture_page():
    scene = load_scene(EXAMPLES_DIR / "web-demo.yaml")
    assert scene.target.url == FIXTURE_PAGE.resolve().as_uri()
