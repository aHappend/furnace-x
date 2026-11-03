"""Fresh-source-only project reproduction, without original evidence/binaries."""

import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import Experiment, ROOT


def main():
    experiment = Experiment("portable-reproduction")
    try:
        experiment.command(["python3", "--version"], "python-version", version=True)
        project = experiment.path / f"project-{experiment.path.name.rsplit('-', 1)[1]}"
        project.mkdir()
        inventory = {}
        for pattern in ("rtl/*.sv", "design/*.md", "firmware/*", "tests/*",
                        "furnace_x2_reference/rtl/*.sv"):
            for source in sorted(ROOT.glob(pattern)):
                if not source.is_file():
                    continue
                relative = source.relative_to(ROOT)
                target = project / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                inventory[str(relative)] = hashlib.sha256(target.read_bytes()).hexdigest()
        (experiment.path / "copied-sources.json").write_text(json.dumps(inventory, indent=2) + "\n")
        output = experiment.command(["python3", "tests/x3_checks.py", "--engines", "--seed", "17"],
                                    "fresh-firmware-engine-smoke", cwd=project)
        if "X3_FIRMWARE_SMOKE_PASS" not in output:
            raise AssertionError("fresh source-only firmware/engine smoke did not compare")
        print("PORTABILITY_PASS fresh real firmware/crypto/ISP/DSP/tensor/DDR comparisons")
    except Exception as error:
        experiment.finish(error)
        raise
    experiment.finish()


if __name__ == "__main__":
    main()
