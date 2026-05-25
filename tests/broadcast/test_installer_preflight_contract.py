from pathlib import Path


def test_deploy_installer_runs_create_app_preflight_and_ws_gfs_assertion():
    src = Path("deploy/install.sh").read_text(encoding="utf-8")
    assert "preflight_runtime()" in src
    assert "from server.app_factory import create_app; app=create_app(); assert app is not None" in src
    assert "assert '/ws/gfs' in rules" in src
