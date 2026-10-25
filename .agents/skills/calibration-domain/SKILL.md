---
name: calibration-domain
description: "Define o modelo de domínio do ZonaPad: frames raw, normalizados e calibrados, ordem das transformações e schema versionado de perfil. Use ao implementar ou revisar calibração, persistência ou contratos entre hardware e aplicação."
metadata:
  owner: python-engineer
  version: "1.0"
---

# Calibration Domain

## Quando usar

Use esta skill para:

- definir ou revisar os tipos de frame;
- decidir a ordem de centro, range, deadzone, curva e inversão;
- criar ou migrar o schema de perfil;
- garantir que hardware e aplicação usem a mesma semântica;
- escrever testes de invariantes.

Não use para escolher backend ou interpretar um relatório HID; consulte `controller-protocols`.

## Modelo de dados

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping


@dataclass(frozen=True)
class RawFrame:
    device_id: str
    timestamp_ns: int
    axes: Mapping[str, int]
    triggers: Mapping[str, int]
    buttons: frozenset[str]


@dataclass(frozen=True)
class NormalizedFrame:
    device_id: str
    timestamp_ns: int
    axes: Mapping[str, float]  # sticks em [-1, 1]
    triggers: Mapping[str, float]  # triggers em [0, 1]
    buttons: frozenset[str]


@dataclass(frozen=True)
class CalibratedFrame:
    device_id: str
    timestamp_ns: int
    axes: Mapping[str, float]
    triggers: Mapping[str, float]
    buttons: frozenset[str]
    profile_id: str
```

Regras:

- `RawFrame` é imutável e preserva os counts originais.
- `NormalizedFrame` é independente do dispositivo, mas ainda não é personalizado.
- `CalibratedFrame` é o resultado do perfil do usuário.
- Não use `dict` mutável compartilhado entre threads; congele ou copie.
- Nomes de eixos são estáveis (`lx`, `ly`, `rx`, `ry`), não índices.

## Pipeline

```text
raw
  → normalize (range do dispositivo)
  → center (repouso medido)
  → range (escala para o curso útil)
  → deadzone (radial, cut ou rescale)
  → curve (linear, exponencial ou LUT)
  → invert (opcional)
  → clamp
```

Ordem obrigatória. Mudar a ordem muda o resultado; registre no perfil.

### Normalização de stick

Para um eixo com `min`, `max` e centro `c`:

```text
se x >= c: n = (x - c) / (max - c)
senão:     n = (x - c) / (c - min)
n = clamp(n, -1, 1)
```

Isso trata ranges assimétricos e centros deslocados.

### Normalização de trigger

```text
n = (x - rest) / (max - rest)
n = clamp(n, 0, 1)
```

Se `max == rest`, o trigger é inválido; reporte em vez de dividir.

### Deadzone radial

```text
r = hypot(x, y)
se r <= dz: (0, 0)
senão cut:     (x, y)
senão rescale: f = (r - dz) / (1 - dz); (x/r*f, y/r*f)
```

O perfil registra `mode` (`cut` ou `rescale`) e `value`.

### Curvas

- `linear`: identidade.
- `exponential`: `sign(x) * abs(x) ** gamma`, com `gamma > 0`.
- `lut`: pontos `(entrada, saída)` monotônicos, interpolação linear, clamp nas pontas.

Curvas devem ser monotônicas e mapear 0 → 0 (exceto se documentado). Não aplique curva antes da deadzone.

## Perfil

Exemplo abreviado. O schema completo, com os dois sticks e os dois triggers, está em `references/profile-schema.md`.

```json
{
  "schema_version": 1,
  "profile_id": "uuid",
  "device": {
    "name": "DualSense",
    "vid": "0x054c",
    "pid": "0x0ce6",
    "guid": "optional",
    "serial": "optional"
  },
  "sticks": {
    "left": {
      "center": [0.0, 0.0],
      "range": {"min": [-1.0, -1.0], "max": [1.0, 1.0]},
      "deadzone": {"mode": "cut", "value": 0.08},
      "curve": {"type": "linear"},
      "invert": [false, false]
    },
    "right": {}
  },
  "triggers": {
    "left": {
      "rest": 0.0,
      "max": 1.0,
      "deadzone": 0.02,
      "curve": {"type": "linear"},
      "invert": false
    },
    "right": {}
  },
  "created_at": "2026-10-24T00:00:00Z",
  "app_version": "0.1.0",
  "notes": ""
}
```

Detalhes e regras de validação em `references/profile-schema.md`.

## Invariantes

Teste estas propriedades:

1. Todo valor normalizado/calibrado é finito.
2. Sticks ficam em [-1, 1]; triggers em [0, 1].
3. O centro calibrado produz (0, 0) ou 0.
4. A deadzone não aumenta a magnitude do vetor.
5. Curvas monotônicas preservam a ordem.
6. Inversão troca o sinal sem alterar a magnitude.
7. Serializar e desserializar um perfil válido preserva os valores.
8. Um perfil com `schema_version` desconhecida é rejeitado, não interpretado.

## Versionamento

- `schema_version` é inteiro e incrementa em mudanças incompatíveis.
- Migrações são funções puras `migrate_vN_to_vN+1(profile) -> profile`.
- Nunca altere o significado de um campo existente sem nova versão.
- Perfis antigos devem ser lidos ou rejeitados com mensagem clara.
- Guarde `app_version` para diagnóstico, mas não dependa dele para lógica.

## Checklist

- [ ] Os três tipos de frame estão definidos e imutáveis.
- [ ] A ordem das transformações está documentada.
- [ ] Normalização trata ranges assimétricos.
- [ ] Triggers usam o repouso medido.
- [ ] Deadzone tem modo explícito.
- [ ] Curvas são monotônicas e validadas.
- [ ] O perfil tem `schema_version` e validação.
- [ ] As invariantes têm testes.

<!-- Gerado por scripts/sync_ai_assets.py. Edite ai/skills/calibration-domain/SKILL.md. -->
