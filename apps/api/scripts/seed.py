"""Run the operational and financial seeds for the same test business."""

import argparse
import subprocess
import sys
from uuid import UUID

from scripts.seed_test_business import TEST_BUSINESS_ID


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Executa as seeds operacional e financeira de uma empresa de testes."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--business-id", type=UUID, help="UUID da empresa de testes existente."
    )
    target.add_argument(
        "--test-business",
        action="store_true",
        help=f"Cria a empresa fictícia {TEST_BUSINESS_ID}, se ausente, e a popula.",
    )
    args = parser.parse_args(argv)
    business_id = TEST_BUSINESS_ID if args.test_business else args.business_id
    commands = [
        [sys.executable, "-m", f"scripts.{module}", "--business-id", str(business_id)]
        for module in ("seed_operational", "seed_financial")
    ]
    if args.test_business:
        commands.insert(0, [sys.executable, "-m", "scripts.seed_test_business"])

    for command in commands:
        print(f"Executando {command[2].removeprefix('scripts.')}...", flush=True)
        result = subprocess.run(command, check=False)
        if result.returncode:
            print(
                "Execução interrompida. Seeds anteriores concluídas permanecem no banco.",
                file=sys.stderr,
            )
            return result.returncode if result.returncode > 0 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
