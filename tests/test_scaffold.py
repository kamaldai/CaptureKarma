import capturekarma
from capturekarma import _win


def test_version():
    assert capturekarma.__version__.startswith("2.")


def test_high_res_timer_is_a_context_manager():
    with _win.high_res_timer():
        pass


def test_set_dpi_awareness_returns_bool():
    assert isinstance(_win.set_dpi_awareness(), bool)


def test_scene_package_exports_names_not_submodules():
    import capturekarma.scene as scene_pkg

    assert "loader" not in scene_pkg.__all__ and "model" not in scene_pkg.__all__
    for name in ("Scene", "SceneError", "load_scene", "dump_scene", "parse_scene", "scene_to_dict",
                 "Target", "Region", "StepTarget", "EASING_NAMES"):
        assert name in scene_pkg.__all__
    for name in scene_pkg.__all__:
        assert hasattr(scene_pkg, name), name


def test_is_remote_session_returns_bool():
    assert isinstance(_win.is_remote_session(), bool)
