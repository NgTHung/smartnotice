"""Load versioned Vietnamese audience cues and their source hash."""

from hashlib import sha256
from pathlib import Path
from typing import Literal
from unicodedata import normalize

from pydantic import Field, ValidationError, model_validator
from smartnotice.schemas import DegreeLevel, Record, StudentStatus

DEFAULT_LEXICON_PATH = Path("config/applicability_lexicon.json")


def fold_text(value: str) -> str:
    """Return NFC text with case and whitespace folded, preserving diacritics."""
    return " ".join(normalize("NFC", value.casefold()).split())


class Lexicon(Record):
    """Map versioned surface forms to audience cues and profile codes."""

    version: str = Field(min_length=1)
    majors: dict[str, list[str]]
    programs: dict[str, list[str]]
    degrees: dict[DegreeLevel | Literal["graduate"], list[str]]
    statuses: dict[StudentStatus, list[str]]
    exclusion: list[str]
    all_students: list[str]
    outside_population: list[str]
    student_terms: list[str]
    unrepresented: list[str]
    condition: list[str]

    @model_validator(mode="after")
    def _normalize_forms(self) -> "Lexicon":
        for key in type(self).model_fields.keys() - {"version"}:
            value = getattr(self, key)
            groups = value.values() if isinstance(value, dict) else (value,)
            for forms in groups:
                forms[:] = [fold_text(form) for form in forms]
                if "" in forms:
                    raise ValueError(f"{key} contains a blank surface form")
        return self


def load_lexicon(path: Path) -> tuple[Lexicon, str]:
    """Return validated cues and the SHA-256 of the original UTF-8 file."""
    content = path.read_bytes()
    try:
        lexicon = Lexicon.model_validate_json(content)
    except ValidationError as exc:
        details = ", ".join(
            f"{'.'.join(map(str, error['loc'])) or 'lexicon'} ({error['msg']})"
            for error in exc.errors(include_input=False)
        )
        raise ValueError(f"Invalid applicability lexicon {path}: {details}") from None
    return lexicon, sha256(content).hexdigest()
