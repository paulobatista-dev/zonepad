---
name: python-app-architecture
description: Define a arquitetura em camadas do ZonaPad, os contratos de dispositivo e o fluxo raw→normalizado→calibrado. Use ao criar módulos, revisar acoplamentos, planejar uma feature ou decidir onde uma regra deve morar.
metadata:
  owner: python-engineer
  version: "1.0"
---

# Python App Architecture

## Quando usar

Use esta skill para:

- criar a estrutura inicial do app;
- decidir em qual camada uma responsabilidade deve ficar;
- definir ou revisar portas de dispositivo, relógio e persistência;
- planejar concorrência entre leitura de hardware e UI;
- revisar acoplamentos e testabilidade.

Não use para decidir semântica de protocolo ou métricas de calibração; consulte `controller-protocols` e `calibration-metrics`.

## Camadas

```text
src/zonepad/
├── domain/          # modelos e regras puras
├── application/     # casos de uso e portas
├── infrastructure/  # SDL3/HID, arquivos, relógio real
└── interface/       # CLI, GUI, composição
```

Regra de dependência: `interface → application → domain`. `infrastructure` implementa portas definidas em `application`/`domain`; o domínio não importa nada de fora.

## Layout sugerido

```text
src/zonepad/
├── domain/
│   ├── device.py          # DeviceInfo, capabilities
│   ├── input.py           # RawFrame, NormalizedFrame, CalibratedFrame
│   ├── calibration.py     # transformações puras
│   ├── metrics.py         # métricas e estatísticas
│   └── profile.py         # perfil, versão, validação
├── application/
│   ├── ports.py           # DeviceBackend, DeviceSession, Clock, ProfileStore
│   ├── detect.py          # descoberta e seleção
│   ├── calibrate.py       # casos de uso do wizard
│   └── capture.py         # captura/replay
├── infrastructure/
│   ├── sdl3_backend.py
│   ├── hid_backend.py
│   ├── replay_backend.py
│   ├── system_clock.py
│   └── json_profile_store.py
└── interface/
    ├── cli.py
    └── gui/
```

## Portas

Defina contratos pequenos e explícitos:

```python
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from zonepad.domain.device import DeviceInfo
from zonepad.domain.input import InputFrame


class DeviceBackend(Protocol):
    def list_devices(self) -> Sequence[DeviceInfo]: ...
    def open(self, device_id: str) -> DeviceSession: ...


class DeviceSession(Protocol):
    @property
    def capabilities(self) -> frozenset[str]: ...

    def read(self, timeout_s: float) -> InputFrame | None: ...
    def close(self) -> None: ...


class Clock(Protocol):
    def now_ns(self) -> int: ...
```

Regras:

- A porta descreve o que o app precisa, não o que a biblioteca oferece.
- Não vaze tipos de SDL/HID para `application` ou `domain`.
- `None` em `read` significa timeout, não desconexão; use exceção tipada para desconexão.
- `capabilities` evita `hasattr` e condicionais espalhadas.

## Fluxo de dados

```text
backend → RawFrame → normalize() → NormalizedFrame → apply_profile() → CalibratedFrame → UI/métricas
```

- `RawFrame` preserva os valores originais e o timestamp do dispositivo.
- `NormalizedFrame` usa unidades documentadas: sticks em [-1, 1], triggers em [0, 1].
- `CalibratedFrame` aplica centro, range, deadzone, inversão e curva do perfil.
- Métricas de diagnóstico podem consumir `NormalizedFrame` ou `CalibratedFrame`, mas devem declarar qual.
- Nunca sobrescreva `RawFrame`; calibração é uma transformação, não uma mutação.

## Concorrência

O padrão é:

1. Um worker lê o dispositivo em loop, com timeout curto.
2. O worker publica snapshots imutáveis em uma fila limitada.
3. A UI consome o snapshot mais recente e descarta os antigos, se necessário.
4. Comandos da UI (iniciar/parar captura) viajam por uma fila de controle.

Regras:

- Não leia hardware na thread da UI.
- Prefira coalescência a bloquear o produtor.
- Registre a taxa efetiva de leitura e o número de amostras descartadas.
- Use `asyncio` quando o backend for assíncrono; use thread + fila quando for bloqueante. Não misture sem um adaptador claro.
- Hot-plug: trate desconexão como estado explícito, com reconexão e backoff.

## Persistência

- Perfis em JSON versionado, com `schema_version`.
- Validar antes de aplicar; rejeitar campos desconhecidos perigosos.
- Escrever de forma atômica (arquivo temporário + `replace`).
- Chave do perfil: identidade estável do dispositivo (VID/PID + GUID/serial quando disponível), não o index da porta.
- Migrações explícitas e testadas; nunca altere o significado de um campo sem nova versão.

## Erros

```python
class ZonaPadError(Exception): ...


class DeviceNotFoundError(ZonaPadError): ...


class DeviceDisconnectedError(ZonaPadError): ...


class InvalidProfileError(ZonaPadError): ...
```

- A camada que entende a falha a traduz; a UI só apresenta.
- Não capture `Exception` genérico sem re-lançar ou registrar contexto.
- Inclua contexto suficiente no log: dispositivo, operação, timeout.

## Testes

- Domínio: testes puros, property-based quando a matemática permitir.
- Aplicação: fakes de `DeviceBackend`/`Clock`/`ProfileStore`.
- Infraestrutura: testes de contrato com o mesmo conjunto de casos para cada backend.
- Interface: testes de view-model, não de pixels, quando possível.
- Replay: uma captura real vira fixture determinística.

## ADR

Registre decisões que mudam contratos ou dependências em `docs/adr/NNNN-titulo.md`:

```markdown
# NNNN — Título

## Contexto
## Decisão
## Consequências
## Alternativas consideradas
```

## Checklist

- [ ] O domínio não importa UI, SO ou biblioteca de dispositivo.
- [ ] Cada dependência externa está atrás de uma porta.
- [ ] O fluxo raw → normalizado → calibrado está explícito.
- [ ] A leitura não bloqueia a UI.
- [ ] Desconexão e timeout são estados distintos.
- [ ] Perfis são versionados e validados.
- [ ] Há fakes/replay para os testes.
- [ ] Decisões relevantes têm ADR.

<!-- Gerado por scripts/sync_ai_assets.py. Edite ai/skills/python-app-architecture/SKILL.md. -->
