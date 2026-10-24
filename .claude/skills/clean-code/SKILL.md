---
name: clean-code
description: "Aplica princípios de código limpo em Python: nomes que revelam intenção, funções pequenas, responsabilidade única, erros explícitos, baixo acoplamento e testes legíveis. Use ao implementar, refatorar ou revisar código."
metadata:
  owner: python-engineer
  version: "1.0"
---

# Clean Code

## Quando usar

Use esta skill ao:

- implementar uma feature ou corrigir um bug;
- refatorar código difícil de entender ou de mudar;
- revisar um diff;
- escrever nomes, docstrings, mensagens de erro ou testes.

Não use para discutir estilo que o formatador já resolve. `ruff` cuida de espaçamento, aspas e ordem de imports; esta skill cuida de **design e comunicação**.

## Princípio

Código limpo é código que outra pessoa consegue entender, testar e mudar com segurança. Legibilidade e baixo acoplamento são meios; comportamento correto é o fim.

## Nomes

- Revele intenção: `elapsed_ms`, `is_connected`, `profile_store`.
- Evite abreviações obscuras: `t`, `d`, `proc`, `mgr`.
- Booleanos devem soar como afirmações: `is_active`, `has_profile`, `can_reconnect`.
- Evite `data`, `info`, `manager`, `helper`, `utils` sem qualificador.
- Use o vocabulário do domínio: `deadzone`, `trigger`, `rest_center`.
- Mantenha o mesmo nome para o mesmo conceito em todo o projeto.

## Funções

- Faça uma coisa; se o nome tem "e", provavelmente são duas.
- Prefira poucos parâmetros; agrupe dados relacionados em um objeto de valor.
- Evite parâmetros de controle (`flag`) que mudam o comportamento.
- Separe comando de consulta: uma função que calcula não deve persistir; uma que persiste não deve esconder cálculo.
- Não esconda efeitos colaterais; nomeie-os (`save_`, `send_`, `apply_`).
- Retorne cedo para reduzir aninhamento.
- Prefira funções puras no domínio.

## Classes e módulos

- Uma classe deve ter uma responsabilidade e um motivo claro para mudar.
- Alta coesão: métodos usam o mesmo estado.
- Baixo acoplamento: dependa de abstrações estáveis, não de detalhes.
- Evite god objects e classes de conveniência sem domínio.
- Prefira composição a herança profunda.
- Exponha uma API pública pequena; o resto é detalhe.

## Comentários e docstrings

- Comente **por que**, restrições e decisões; não repita o código.
- Docstring em APIs públicas: propósito, parâmetros, retorno e exceções.
- Não deixe código comentado; o histórico versionado preserva.
- Atualize o comentário quando o código mudar; comentário errado é pior que ausente.

## Erros

- Use exceções explícitas do domínio: `DeviceDisconnectedError`, `InvalidProfileError`.
- Não capture `Exception` genérico sem re-lançar ou registrar contexto.
- Inclua o que falhou, onde e o que fazer.
- Falhe cedo nas bordas; mantenha invariantes no domínio.
- Não use exceção para controle de fluxo normal.
- Nunca silencie uma falha para "seguir em frente".

## Dados e tipos

- Prefira objetos de valor imutáveis (`@dataclass(frozen=True)`).
- Evite obsessão por primitivos: `DeviceId`, `ProfileId`, `NormalizedAxis`.
- Valide na fronteira; assuma invariantes no domínio.
- Não use argumentos default mutáveis.
- Tipar APIs públicas; evite `Any` sem justificativa.

## Duplicação e abstração

- Aplique a regra de três: só abstraia depois de ver o mesmo padrão três vezes.
- Duplicação é mais barata que uma abstração errada.
- Abstraia conceitos, não linhas parecidas.
- Remova código morto e caminhos não usados.

## Testes

- Nomeie pelo comportamento: `test_deadzone_radial_zera_centro`.
- Use arrange–act–assert.
- Um teste deve falhar por um motivo claro.
- Torne o teste determinístico: relógio injetado, sem `sleep`, sem rede.
- Cubra bordas e erros, não só o caminho feliz.
- Evite testar detalhes internos; teste o contrato.

## Refatoração

- Refatore em passos pequenos, com testes verdes.
- Separe refatoração de mudança de comportamento.
- Aplique a regra do escoteiro: deixe o código um pouco melhor do que encontrou.
- Se a mudança exige reescrever tudo, primeiro estabilize o comportamento com testes.

## Python idiomático

- `from __future__ import annotations` em módulos com hints.
- `pathlib.Path` em vez de manipulação de strings de caminho.
- Context managers para recursos.
- `enumerate`, `zip` e comprehensions quando deixam o código mais claro.
- `Protocol` para portas; `dataclass` para dados.
- Evite imports com `*` e estado global mutável.

## Exemplo

Antes:

```python
def p(d, f):
    r = []
    for x in d:
        if x[2]:
            r.append(x[1] * f)
    return r
```

Depois:

```python
from dataclasses import dataclass
from collections.abc import Iterable


@dataclass(frozen=True)
class Reading:
    axis: str
    value: float
    is_active: bool


def scale_active_readings(readings: Iterable[Reading], factor: float) -> list[float]:
    return [reading.value * factor for reading in readings if reading.is_active]
```

## Relação com outras skills

- `python-quality`: ferramentas, lint, tipos, CI e performance.
- `clean-architecture`: boundaries e direção de dependência.
- `python-app-architecture`: layout concreto do ZonaPad.

## Checklist

- [ ] Nomes revelam intenção e usam o vocabulário do domínio.
- [ ] Funções pequenas, com uma responsabilidade e sem efeitos escondidos.
- [ ] Classes coesas e com baixo acoplamento.
- [ ] Comentários explicam o porquê, não o quê.
- [ ] Erros são explícitos e acionáveis.
- [ ] Tipos e invariantes estão claros.
- [ ] Não há abstração prematura nem código morto.
- [ ] Testes são legíveis e determinísticos.
- [ ] A mudança é pequena e verificável.

<!-- Gerado por scripts/sync_ai_assets.py. Edite ai/skills/clean-code/SKILL.md. -->
