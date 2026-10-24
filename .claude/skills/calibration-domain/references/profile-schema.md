# Schema de perfil — regras de validação

## Estrutura

```json
{
  "schema_version": 1,
  "profile_id": "550e8400-e29b-41d4-a716-446655440000",
  "device": {
    "name": "DualSense",
    "vid": "0x054c",
    "pid": "0x0ce6",
    "guid": null,
    "serial": null
  },
  "sticks": {
    "left": {
      "center": [0.0, 0.0],
      "range": {"min": [-1.0, -1.0], "max": [1.0, 1.0]},
      "deadzone": {"mode": "cut", "value": 0.08},
      "curve": {"type": "linear"},
      "invert": [false, false]
    },
    "right": {
      "center": [0.0, 0.0],
      "range": {"min": [-1.0, -1.0], "max": [1.0, 1.0]},
      "deadzone": {"mode": "cut", "value": 0.08},
      "curve": {"type": "linear"},
      "invert": [false, false]
    }
  },
  "triggers": {
    "left": {
      "rest": 0.0,
      "max": 1.0,
      "deadzone": 0.02,
      "curve": {"type": "linear"},
      "invert": false
    },
    "right": {
      "rest": 0.0,
      "max": 1.0,
      "deadzone": 0.02,
      "curve": {"type": "linear"},
      "invert": false
    }
  },
  "created_at": "2026-10-24T00:00:00Z",
  "app_version": "0.1.0",
  "notes": ""
}
```

## Regras

### Raiz

| Campo | Tipo | Regra |
| --- | --- | --- |
| `schema_version` | int | 1..N suportado; desconhecido → rejeitar |
| `profile_id` | string | UUID v4; único |
| `device` | object | Obrigatório |
| `sticks` | object | `left` e `right` obrigatórios |
| `triggers` | object | `left` e `right` obrigatórios |
| `created_at` | string | ISO 8601 UTC |
| `app_version` | string | Semver |
| `notes` | string | Até 2.000 caracteres |

### Device

| Campo | Tipo | Regra |
| --- | --- | --- |
| `name` | string | 1..200 caracteres |
| `vid` | string | `0x` + 4 hex |
| `pid` | string | `0x` + 4 hex |
| `guid` | string/null | Opcional |
| `serial` | string/null | Opcional; não logar em claro |

### Stick

| Campo | Tipo | Regra |
| --- | --- | --- |
| `center` | [float, float] | Cada eixo em [-1, 1] |
| `range.min` | [float, float] | Cada eixo em [-1, 1] |
| `range.max` | [float, float] | Cada eixo em [-1, 1] |
| `deadzone.mode` | `"cut"`/`"rescale"` | Obrigatório |
| `deadzone.value` | float | [0, 0.95] |
| `curve.type` | `"linear"`/`"exponential"`/`"lut"` | Obrigatório |
| `curve.gamma` | float | > 0; obrigatório se exponencial |
| `curve.lut` | array | ≥ 2 pontos monotônicos; obrigatório se LUT |
| `invert` | [bool, bool] | Inversão por eixo |

### Trigger

| Campo | Tipo | Regra |
| --- | --- | --- |
| `rest` | float | [0, 1] |
| `max` | float | (rest, 1] |
| `deadzone` | float | [0, 0.95] |
| `curve` | object | Mesmas regras do stick |
| `invert` | bool | Inversão |

## Validação

- Rejeite campos desconhecidos em objetos críticos ou ignore com aviso explícito.
- Rejeite `NaN` e infinito.
- Verifique `range.min < range.max` por eixo.
- Verifique `rest < max`.
- Verifique monotonicidade da LUT.
- Normalize e limite strings antes de exibir.
- Não use `eval`/`exec`.
- Se o perfil for de outra versão, aplique migração ou rejeite; nunca "adivinhe".

## Migração

```python
def migrate_v1_to_v2(profile: dict) -> dict: ...
```

- Migrações são puras e testadas com fixtures reais.
- Migre uma versão por vez.
- Preserve campos desconhecidos apenas se forem inofensivos e documentados.
- Registre a migração no changelog do schema.
