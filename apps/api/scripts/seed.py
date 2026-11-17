"""Run the operational and financial seeds for the same test business."""

import argparse
import subprocess
import sys
from uuid import UUID


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Executa as seeds operacional e financeira de uma empresa de testes."
    )
    parser.add_argument(
        "--business-id", type=UUID, required=True, help="UUID da empresa de testes existente."
    )
    args = parser.parse_args(argv)

    for module in ("seed_operational", "seed_financial"):
        print(f"Executando {module}...", flush=True)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                f"scripts.{module}",
                "--business-id",
                str(args.business_id),
            ],
            check=False,
        )
        if result.returncode:
            print(
                "Execução interrompida. Seeds anteriores concluídas permanecem no banco.",
                file=sys.stderr,
            )
            return result.returncode if result.returncode > 0 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
