from dataclasses import dataclass
from pathlib import Path

from deliciousmap.registry import Target


@dataclass(frozen=True)
class Paths:
    repository: Path
    raw_root: Path
    data_root: Path
    output_root: Path

    def validate(self) -> None:
        if self.raw_root.resolve().is_relative_to(self.repository.resolve()):
            raise ValueError("raw-root must be outside the repository")

    def city_dir(self, target: Target) -> Path:
        base = self.data_root / target.city.slug
        return base / "orgs" / target.org if target.org else base

    def manual(self, target: Target, name: str) -> Path:
        """사람 보정·상호 복원·업소 확인은 의미가 다르므로 파일을 나눈다."""
        if name not in {"classify", "restore", "geocode"}:
            raise ValueError("unknown manual review input")
        return self.data_root / "manual" / target.city.slug / f"{name}.jsonl"

    def shared(self, name: str) -> Path:
        if name not in {"headermap", "classify"}:
            raise ValueError("unknown shared cache")
        return self.data_root / "_shared" / f"{name}.jsonl"
