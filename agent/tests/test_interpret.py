"""Role interpretation tests with a stubbed provider (no network)."""
import fmaj_agent.interpret as interp
from fmaj_agent.models import RoleSpec
from fmaj_agent.providers import Turn


class StubProvider:
    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, *a, **kw) -> Turn:
        return Turn(text=self.text)


def _use(monkeypatch, text: str) -> None:
    monkeypatch.setattr(interp, "get_provider", lambda: StubProvider(text))


def test_parses_suggestions(monkeypatch) -> None:
    _use(monkeypatch, '{"roles": [{"label": "Kitchen Hand", "curated_key": "kitchen hand",'
                      ' "why": "entry level"}, {"label": "dishwasher",'
                      ' "curated_key": "kitchen hand", "why": "same venues"}]}')
    out = interp.interpret_roles("I want to work in a restaurant")
    assert [r.label for r in out] == ["kitchen hand", "dishwasher"]
    # non-curated label borrows venue types from a curated role
    assert out[1].curated_key == "kitchen hand"


def test_drops_hallucinated_curated_key(monkeypatch) -> None:
    _use(monkeypatch, '{"roles": [{"label": "sommelier", "curated_key": "wine expert"}]}')
    out = interp.interpret_roles("wine")
    assert out[0].curated_key is None  # "wine expert" isn't in role_mapping.yaml


def test_dedupes_and_lowercases(monkeypatch) -> None:
    _use(monkeypatch, '{"roles": [{"label": "Chef"}, {"label": "chef"}]}')
    assert [r.label for r in interp.interpret_roles("cooking")] == ["chef"]


def test_falls_back_to_raw_text_on_bad_json(monkeypatch) -> None:
    _use(monkeypatch, "sorry, I cannot help")
    out = interp.interpret_roles("something unusual")
    assert len(out) == 1 and out[0].label == "something unusual"


def test_empty_text_returns_nothing(monkeypatch) -> None:
    assert interp.interpret_roles("  ") == []


def test_rolespec_mapping_key() -> None:
    assert RoleSpec(label="dishwasher", curated_key="kitchen hand").mapping_key == (
        "kitchen hand")
    assert RoleSpec(label="chef").mapping_key == "chef"
