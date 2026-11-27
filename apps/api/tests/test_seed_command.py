import subprocess
import sys
from unittest.mock import patch

import pytest

from scripts.seed import main
from scripts.seed_test_business import TEST_BUSINESS_ID

BUSINESS_ID = "b4702959-3238-41aa-8b48-01f3de05dd8e"


@pytest.mark.parametrize("return_codes", [(0, 0), (1,), (0, 2), (-15,)])
def test_seed_execution_order_and_failure(return_codes: tuple[int, ...]) -> None:
    with patch("scripts.seed.subprocess.run") as run:
        run.side_effect = [subprocess.CompletedProcess([], code) for code in return_codes]

        result = main(["--business-id", BUSINESS_ID])

    expected_code = 1 if return_codes[-1] < 0 else return_codes[-1]
    assert result == expected_code
    assert run.call_count == len(return_codes)
    for call, module in zip(
        run.call_args_list, ("seed_operational", "seed_financial"), strict=False
    ):
        assert call.args[0] == [
            sys.executable, "-m", f"scripts.{module}", "--business-id", BUSINESS_ID
        ]
        assert call.kwargs == {"check": False}


@pytest.mark.parametrize("arguments", [[], ["--business-id", "invalid"]])
def test_invalid_arguments_do_not_run_seeds(arguments: list[str]) -> None:
    with patch("scripts.seed.subprocess.run") as run, pytest.raises(SystemExit) as exc:
        main(arguments)
    assert exc.value.code == 2
    run.assert_not_called()


def test_test_business_is_created_before_the_seeds() -> None:
    with patch("scripts.seed.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], 0)

        assert main(["--test-business"]) == 0

    assert [call.args[0][2] for call in run.call_args_list] == [
        "scripts.seed_test_business",
        "scripts.seed_operational",
        "scripts.seed_financial",
    ]
    assert run.call_args_list[1].args[0][-1] == str(TEST_BUSINESS_ID)


def test_business_id_and_test_business_are_exclusive() -> None:
    with patch("scripts.seed.subprocess.run") as run, pytest.raises(SystemExit) as exc:
        main(["--test-business", "--business-id", BUSINESS_ID])
    assert exc.value.code == 2
    run.assert_not_called()
