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
    res = interp.interpret_roles("I want to work in a restaurant")
    assert res.ok
    assert [r.label for r in res.roles] == ["kitchen hand", "dishwasher"]
    # non-curated label borrows venue types from a curated role
    assert res.roles[1].curated_key == "kitchen hand"


def test_drops_hallucinated_curated_key(monkeypatch) -> None:
    _use(monkeypatch, '{"roles": [{"label": "sommelier", "curated_key": "wine expert"}]}')
    res = interp.interpret_roles("wine")
    assert res.roles[0].curated_key is None  # "wine expert" isn't in role_mapping.yaml


def test_dedupes_and_lowercases(monkeypatch) -> None:
    _use(monkeypatch, '{"roles": [{"label": "Chef"}, {"label": "chef"}]}')
    assert [r.label for r in interp.interpret_roles("cooking").roles] == ["chef"]


def test_vague_input_warns_instead_of_guessing(monkeypatch) -> None:
    """Empty roles from the model => ask the user to rephrase, never invent a role."""
    _use(monkeypatch, '{"roles": []}')
    res = interp.interpret_roles("I need any job")
    assert not res.ok and res.roles == []
    assert "specific job roles" in res.message


def test_model_failure_warns_and_does_not_use_raw_text(monkeypatch) -> None:
    _use(monkeypatch, "sorry, I cannot help")
    res = interp.interpret_roles("i want to work as a software developer in my next role")
    assert not res.ok and res.roles == []
    # the user's sentence must NOT become a search term
    assert not any("i want to work" in r.label for r in res.roles)


def test_empty_text_warns(monkeypatch) -> None:
    res = interp.interpret_roles("  ")
    assert not res.ok and res.roles == []


def test_rolespec_mapping_key() -> None:
    assert RoleSpec(label="dishwasher", curated_key="kitchen hand").mapping_key == (
        "kitchen hand")
    assert RoleSpec(label="chef").mapping_key == "chef"
