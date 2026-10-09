"""cutover_plan.py holds the pure parts of the cutover: dates, the Chicago time guard and the command order.
Why the order matters (learned in the 2026-10-09 cutover): `kg-packs run-metrics` in the CLI has no resolver for
mode=file, so the target metrics (store_targets) are only recomputed by the server-side run that a targets upload
triggers. Uploading only BEFORE set-as-of leaves retail.target_* on the old month and RET-SALES-001 silent."""
from datetime import date, datetime, timezone

import pytest

import cutover_plan as P
import shift_dates as S


def test_plan_dates_come_from_the_shifted_and_original_packages(tmp_path):
    shifted = tmp_path / "s"
    shifted.mkdir()
    (shifted / "transactions.csv").write_text("transaction_id,transaction_datetime\nT1,2026-10-09 21:05:22\n")
    original = tmp_path / "o"
    original.mkdir()
    (original / "transactions.csv").write_text("transaction_id,transaction_datetime\nT1,2025-08-01 08:02:46\n")
    plan = P.make_plan(shifted, original)
    assert (plan.as_of, plan.metrics_from, plan.metrics_to) == (date(2026, 10, 9), date(2025, 8, 1), date(2026, 10, 10))


@pytest.mark.parametrize("utc, early", [
    (datetime(2026, 10, 9, 3, 35, tzinfo=timezone.utc), True),    # 10:35 Vietnam = 22:35 Chicago on the 8th
    (datetime(2026, 10, 9, 4, 59, tzinfo=timezone.utc), True),
    (datetime(2026, 10, 9, 5, 0, tzinfo=timezone.utc), False),    # 12:00 Vietnam = 00:00 Chicago
    (datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc), False),
])
def test_set_as_of_is_too_early_until_the_day_starts_in_chicago(utc, early):
    assert P.too_early(date(2026, 10, 9), utc) is early


def _steps(plan):
    return [step for step, _ in P.cutover_commands(plan, shifted_dir="demo_mockdata_shifted_70", backup="b.dump")]


def test_targets_are_uploaded_again_after_run_metrics():
    steps = _steps(P.Plan(date(2026, 10, 9), date(2025, 8, 1), date(2026, 10, 10)))
    assert steps.index("load") < steps.index("resync") < steps.index("upload_targets")
    assert steps.index("upload_targets") < steps.index("set_as_of") < steps.index("run_metrics")
    assert steps.index("run_metrics") < steps.index("reupload_targets") < steps.index("wait_targets_current")
    assert steps.index("wait_targets_current") < steps.index("laam_as_of") < steps.index("laam_run")
    assert steps[-1] == "check_latest_run"


def test_commands_carry_the_plan_dates_and_write_mode_replace():
    cmds = dict(P.cutover_commands(P.Plan(date(2026, 10, 9), date(2025, 8, 1), date(2026, 10, 10)),
                                   shifted_dir="demo_mockdata_shifted_70", backup="b.dump"))
    assert "--date 2026-10-09" in cmds["set_as_of"]
    assert "--from 2025-08-01 --to 2026-10-10" in cmds["run_metrics"]
    for key in ("upload_targets", "reupload_targets"):
        assert "write_mode=replace" in cmds[key] and "demo_mockdata_shifted_70/targets.xlsx" in cmds[key]
    assert "--findings-json" in cmds["check_latest_run"]


def test_real_package_plan():
    if not (S.DEFAULT_INPUT / "transactions.csv").exists():
        pytest.skip("demo_mockdata not present")
    assert P.make_plan(S.DEFAULT_INPUT, S.DEFAULT_INPUT).metrics_from == date(2025, 8, 1)


SCRIPTS = S.HERE


@pytest.mark.parametrize("name", ["cutover.sh", "refresh_demo.sh", "load_pharmacy_demo.sh"])
def test_shell_scripts_parse(name):
    import subprocess

    assert subprocess.run(["bash", "-n", str(SCRIPTS / name)]).returncode == 0


@pytest.mark.parametrize("args", [[], ["bogus", "x"], ["part1", "demo_mockdata_shifted_70"]])
def test_cutover_refuses_before_touching_anything(args, monkeypatch):
    """No part, an unknown part, or part1 without backup + CONFIRM_LIVE_RELOAD=yes: exit 1 before any docker call."""
    import subprocess

    monkeypatch.delenv("CONFIRM_LIVE_RELOAD", raising=False)
    env = {"PATH": "/usr/bin:/bin"}   # no docker on PATH: reaching a docker call would fail differently
    res = subprocess.run(["bash", str(SCRIPTS / "cutover.sh"), *args], capture_output=True, text=True, env=env)
    assert res.returncode == 1, res.stderr
    assert "usage" in res.stderr or "CONFIRM_LIVE_RELOAD" in res.stderr


def test_print_commands_lists_the_second_upload(capsys, tmp_path):
    shifted = tmp_path / "s"
    shifted.mkdir()
    (shifted / "transactions.csv").write_text("transaction_id,transaction_datetime\nT1,2026-10-09 21:05:22\n")
    assert P.main(["--data", str(shifted), "--original", str(S.DEFAULT_INPUT), "--print-commands"]) == 0
    out = capsys.readouterr().out
    assert out.index("[run_metrics]") < out.index("[reupload_targets]") < out.index("[laam_as_of]")
