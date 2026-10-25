---
name: python-quality
description: "Define o padrão de qualidade Python do ZonaPad: testes, lint, tipagem, CI, determinismo, performance e segurança. Use ao implementar, revisar ou configurar o projeto."
metadata:
  owner: python-engineer
  version: "1.0"
---

# Python Quality

## Quando usar

Use esta skill para:

- configurar ou revisar ferramentas de qualidade;
- escrever testes de domínio, aplicação e infraestrutura;
- investigar flakiness, lentidão ou comportamento não determinístico;
- preparar uma mudança para revisão ou CI.

## Ferramentas de referência

| Objetivo | Ferramenta | Observação |
| --- | --- | --- |
| Ambiente/deps | `asdf` + `virtualenv` + `pip` | Versão fixada em `.tool-versions`; extras em `pyproject.toml` (`.[dev]`). |
| Lint/format | `ruff` | Uma ferramenta para estilo e regras. |
| Tipos | `mypy` ou `pyright` | Escolha uma e mantenha no CI. |
| Testes | `pytest` | Fixtures, parametrização, `raises`. |
| Property-based | `hypothesis` | Útil para normalização e curvas. |
| Cobertura | `coverage.py` | Meça áreas críticas, não persiga 100%. |
| Performance | `pytest-benchmark` ou `time.perf_counter` | Meça antes de otimizar. |

Não adicione uma ferramenta sem um problema concreto que ela resolva.

## Pirâmide de testes

1. **Unitários (maioria)** — domínio puro: normalização, deadzone, curvas, métricas, validação de perfil.
2. **Integração** — casos de uso com fakes de dispositivo, relógio e store; contrato de cada backend.
3. **Smoke de hardware (manual/opcional)** — detecção e leitura real, fora da CI, com dispositivo conhecido.
4. **UI** — view-model e fluxos; evite testes frágeis de pixels.

Regras:

- Um teste deve falhar por um motivo claro.
- Sem `sleep` arbitrário; injete relógio ou use timeout determinístico.
- Prefira dados explícitos a fixtures mágicas.
- Nomeie pelo comportamento: `test_deadzone_radial_zera_centro`, não `test1`.
- Use `pytest.mark.parametrize` para tabelas de borda.
- Teste o contrato, não a implementação interna.

## Exemplo de teste de domínio

```python
from __future__ import annotations

import pytest

from zonepad.domain.calibration import apply_radial_deadzone


@pytest.mark.parametrize(
    ("x", "y", "deadzone", "expected"),
    [
        (0.0, 0.0, 0.1, (0.0, 0.0)),
        (0.05, 0.0, 0.1, (0.0, 0.0)),
        (0.2, 0.0, 0.1, (0.2, 0.0)),
    ],
)
def test_deadzone_radial(
    x: float, y: float, deadzone: float, expected: tuple[float, float]
) -> None:
    assert apply_radial_deadzone(x, y, deadzone) == pytest.approx(expected)
```

## Property-based

Use quando a regra tiver invariantes:

- normalização sempre finita e dentro do range;
- deadzone radial nunca aumenta a magnitude;
- curva monotônica preserva ordem;
- clamp é idempotente;
- perfil válido sobrevive a serializar/desserializar.

```python
from hypothesis import given, strategies as st


@given(st.floats(-1.0, 1.0), st.floats(0.0, 0.5))
def test_deadzone_nao_aumenta_magnitude(x: float, deadzone: float) -> None: ...
```

## Lint e tipos

- `ruff check .` no CI; `ruff format --check .` localmente até entrar na CI (ver CI mínima).
- Tipar APIs públicas e retornos; `Any` exige justificativa.
- Não use `# type: ignore` sem código de erro e motivo.
- Prefira `Protocol` a herança pesada.
- Rode tipos em `src/` e `scripts/`, não em código gerado.

## CI mínima

A CI usa Python 3.15.0, instala `.[dev]` e roda, nesta ordem:

```text
1. ruff check
2. mypy
3. pytest
4. python scripts/sync_ai_assets.py --check
```

O `ruff format --check` entra na CI quando `scripts/sync_ai_assets.py` passar nele sob `py315` (prompt 06).

A CI não deve depender de hardware real, rede instável ou credenciais.

## Performance

- Meça o caminho de leitura com taxa realista (125–1000 Hz).
- Evite criar objetos por amostra em loops críticos.
- Não otimize sem perfil; registre o antes/depois.
- Cuidado com logs por amostra: use amostragem ou nível debug.
- UI: atualize em taxa limitada (por exemplo, 30–60 Hz), não a cada frame do dispositivo.

## Segurança

- Valide JSON de perfil com schema e limites; rejeite tipos inesperados.
- Nunca `eval`/`exec` conteúdo de perfil ou captura.
- Não construa caminhos a partir de input sem normalizar e confinar.
- Não grave segredos ou paths absolutos de usuário em fixtures.
- Comandos destrutivos exigem confirmação e escopo explícito.

## Checklist

- [ ] Testes cobrem bordas e erros, não só o caminho feliz.
- [ ] Testes são determinísticos e não dependem de hardware.
- [ ] Lint e tipos passam.
- [ ] A CI roda testes + lint + tipos + sync check.
- [ ] Performance foi medida no caminho crítico.
- [ ] Perfis e capturas são validados antes do uso.
- [ ] Não há `print`, `eval` ou exceção silenciada.

<!-- Gerado por scripts/sync_ai_assets.py. Edite ai/skills/python-quality/SKILL.md. -->
