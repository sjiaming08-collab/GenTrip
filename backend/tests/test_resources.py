from pathlib import Path

from src.resources import fixture_path


def test_fixture_path_uses_source_tree_layout():
    assert fixture_path("geo_gazetteer.json").is_file()


def test_fixture_path_falls_back_to_runtime_workdir_for_installed_package(tmp_path):
    runtime_fixture = tmp_path / "app" / "fixtures" / "sample.json"
    runtime_fixture.parent.mkdir(parents=True)
    runtime_fixture.write_text("{}", encoding="utf-8")
    installed_module = tmp_path / "site-packages" / "src" / "resources.py"

    resolved = fixture_path(
        "sample.json",
        package_file=installed_module,
        working_dir=tmp_path / "app",
    )

    assert resolved == Path(runtime_fixture).resolve()
